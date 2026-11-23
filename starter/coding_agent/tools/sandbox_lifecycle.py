"""Managed Sandbox Lifecycle Manager & CLI (starter track — Lab 2).

Focused Lab 2 exercises in this module (4 core lifecycle operations):
- ``SandboxLifecycleManager.create_template()`` — provision a reusable BYOC / Shell /
  Computer Use ``SandboxEnvironmentTemplate`` with pre-warmed pool creation.
- ``SandboxLifecycleManager.create_sandbox()`` — provision a ``SandboxEnvironment``
  from a template, direct ``spec``, or snapshot with an explicit ``ttl``.
- ``SandboxLifecycleManager.pause_sandbox()`` — pause a running sandbox to release
  compute while preserving disk state and connection ID.
- ``SandboxLifecycleManager.snapshot_sandbox()`` — snapshot disk, installed libraries,
  and memory state to managed GCS, resolving ``snapshot_name`` dynamically.

All remaining CRUD/query helpers (get, list, update, resume, delete for templates,
sandboxes, and snapshots) are pre-filled so you can focus on the core lifecycle APIs.

Verified SDK & operational rules (from official Scale Sandbox docs):
1. Always pass ``http_options={"api_version": "v1beta1"}`` for BYOC templates,
   PSC-I/PSC-E networking, and CMEK parent instances.
2. Prefer plain Python ``dict`` payloads over internal ``agentplatform._genai`` types.
3. Always capture resource names dynamically from ``operation.response.name`` or
   ``.list()`` responses — never hardcode template or snapshot paths.
4. Reuse templates across sandboxes: omitting ``sandbox_environment_template`` creates
   a new orphan template on every ``sandboxes.create()``, and deleting a sandbox does
   not delete its backing template.
5. Always set an explicit ``ttl`` (default is 2h if omitted; max 7d BYOC / 14d code exec).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from coding_agent.config import Settings, get_settings

logger = logging.getLogger(__name__)

TemplateKind = Literal["byoc", "shell", "computer_use"]
SandboxCreateMode = Literal["byoc", "shell", "code_execution", "snapshot"]

DEFAULT_CONTAINER_CATEGORIES: dict[str, str] = {
    "shell": "DEFAULT_CONTAINER_CATEGORY_SHELL_SANDBOX",
    "computer_use": "DEFAULT_CONTAINER_CATEGORY_COMPUTER_USE",
}


# ---------------------------------------------------------------------------
# Typed Data Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemplateResourceConfig:
    """CPU and memory requests/limits for a BYOC ``custom_container_environment``."""

    cpu_request: str = "1"
    memory_request: str = "1Gi"
    cpu_limit: str = "2"
    memory_limit: str = "2Gi"

    def to_payload(self) -> dict[str, dict[str, str]]:
        return {
            "requests": {"cpu": self.cpu_request, "memory": self.memory_request},
            "limits": {"cpu": self.cpu_limit, "memory": self.memory_limit},
        }


@dataclass(frozen=True)
class TemplatePortConfig:
    """TCP port declared on a BYOC ``SandboxEnvironmentTemplate``."""

    port: int = 8080
    protocol: str = "TCP"

    def to_payload(self) -> dict[str, Any]:
        return {"port": self.port, "protocol": self.protocol}


@dataclass(frozen=True)
class EgressControlConfig:
    """Egress posture for a ``SandboxEnvironmentTemplate``.

    Managed Sandboxes have NO built-in domain allowlist field:
    - Default-deny air-gapped: ``internet_access=False`` (recommended when tools are baked in).
    - Direct public internet: ``internet_access=True`` (blocks RFC 1918 & ``169.254.0.0/16``).
    - Enterprise FQDN/URL allowlisting: attach PSC-I ``customer_vpc_network`` +
      ``network_attachment`` (min ``/28`` subnet) and enforce Cloud NGFW / SWP in your VPC.
    """

    internet_access: bool = False
    customer_vpc_network: str | None = None
    network_attachment: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"internet_access": self.internet_access}
        if self.customer_vpc_network:
            payload["customer_vpc_network"] = self.customer_vpc_network
        if self.network_attachment:
            payload["network_attachment"] = self.network_attachment
        return payload


@dataclass(frozen=True)
class TemplateSummary:
    """Normalized view of a ``SandboxEnvironmentTemplate`` resource."""

    name: str
    display_name: str = ""
    raw: Any = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "display_name": self.display_name}


@dataclass(frozen=True)
class SandboxSummary:
    """Normalized view of a ``SandboxEnvironment`` resource."""

    name: str
    display_name: str = ""
    state: str = ""
    template_name: str = ""
    expire_time: str = ""
    service_attachment: str = ""
    raw: Any = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "state": self.state,
            "template_name": self.template_name,
            "expire_time": self.expire_time,
            "service_attachment": self.service_attachment,
        }


@dataclass(frozen=True)
class SnapshotSummary:
    """Normalized view of a ``SandboxEnvironmentSnapshot`` resource."""

    name: str
    display_name: str = ""
    raw: Any = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "display_name": self.display_name}


# ---------------------------------------------------------------------------
# Defensive SDK Client Compatibility Helpers (agentplatform + vertexai)
# ---------------------------------------------------------------------------


def build_platform_client(
    project_id: str,
    location: str,
    api_version: str | None = "v1beta1",
) -> Any:
    """Construct an ``agentplatform.Client`` (falling back to ``vertexai.Client``).

    Always passes ``http_options={"api_version": "v1beta1"}`` by default, which is
    required for BYOC ``SandboxEnvironmentTemplate``, PSC-I/PSC-E, and CMEK APIs.
    """
    http_options = {"api_version": api_version} if api_version else None
    try:
        import agentplatform

        return agentplatform.Client(
            project=project_id,
            location=location,
            http_options=http_options,
        )
    except ImportError:
        import vertexai

        return vertexai.Client(
            project=project_id,
            location=location,
            http_options=http_options,
        )


def get_runtimes_namespace(client: Any) -> Any:
    """Resolve ``client.runtimes`` (``agentplatform``) or ``client.agent_engines`` (``vertexai``)."""
    runtimes = getattr(client, "runtimes", None)
    if runtimes is not None:
        return runtimes
    return client.agent_engines


def get_sandboxes_namespace(client: Any) -> Any:
    """Resolve ``client.sandboxes`` (``agentplatform``) or ``client.agent_engines.sandboxes``."""
    sandboxes = getattr(client, "sandboxes", None)
    if sandboxes is not None:
        return sandboxes
    return client.agent_engines.sandboxes


def _extract_response(operation_or_resource: Any) -> Any:
    """Return ``operation.response`` if this is an LRO, otherwise the resource itself."""
    resp = getattr(operation_or_resource, "response", None)
    return resp if resp is not None else operation_or_resource


def _summarize_template(resource: Any) -> TemplateSummary:
    return TemplateSummary(
        name=str(getattr(resource, "name", "")),
        display_name=str(getattr(resource, "display_name", "") or ""),
        raw=resource,
    )


def _summarize_sandbox(resource: Any) -> SandboxSummary:
    connection_info = getattr(resource, "connection_info", None)
    service_attachment = str(getattr(connection_info, "service_attachment", "") or "")
    return SandboxSummary(
        name=str(getattr(resource, "name", "")),
        display_name=str(getattr(resource, "display_name", "") or ""),
        state=str(getattr(resource, "state", "") or ""),
        template_name=str(getattr(resource, "sandbox_environment_template", "") or ""),
        expire_time=str(getattr(resource, "expire_time", "") or ""),
        service_attachment=service_attachment,
        raw=resource,
    )


def _summarize_snapshot(resource: Any) -> SnapshotSummary:
    return SnapshotSummary(
        name=str(getattr(resource, "name", "")),
        display_name=str(getattr(resource, "display_name", "") or ""),
        raw=resource,
    )


def _infer_parent_instance(resource_name: str) -> str:
    """Extract ``projects/.../locations/.../reasoningEngines/{id}`` from a child resource name."""
    for marker in (
        "/sandboxEnvironments/",
        "/sandboxEnvironmentTemplates/",
        "/sandboxEnvironmentSnapshots/",
    ):
        if marker in resource_name:
            return resource_name.split(marker, 1)[0]
    return ""


def _is_not_found_error(exc: Exception) -> bool:
    """Return True when an API exception represents HTTP 404 / NOT_FOUND."""
    code = getattr(exc, "code", None)
    status_code = getattr(exc, "status_code", None)
    if code == 404 or status_code == 404:
        return True
    msg = str(exc).upper()
    return "NOT_FOUND" in msg or "404" in msg


def _is_transient_delete_precondition_error(exc: Exception) -> bool:
    """Return True for transient ``FAILED_PRECONDITION`` while child resources finalize."""
    msg = str(exc).upper()
    return any(
        token in msg
        for token in (
            "FAILED_PRECONDITION",
            "IN PROGRESS",
            "STILL IN USE",
            "BEING DELETED",
            "CANNOT BE DELETED",
        )
    )


# ---------------------------------------------------------------------------
# Sandbox Lifecycle Manager
# ---------------------------------------------------------------------------


class SandboxLifecycleManager:
    """End-to-end lifecycle manager for Agent Platform Templates, Sandboxes & Snapshots."""

    def __init__(
        self,
        *,
        project_id: str,
        location: str = "asia-southeast1",
        instance_name: str | None = None,
        api_version: str = "v1beta1",
        client: Any | None = None,
    ) -> None:
        self.project_id = project_id
        self.location = location
        self.instance_name = (instance_name or "").strip()
        self.api_version = api_version
        self._client = client

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> SandboxLifecycleManager:
        """Create a manager initialized from environment ``Settings``."""
        cfg = settings or get_settings()
        return cls(
            project_id=cfg.require_gcp_project(),
            location=cfg.google_cloud_location,
            instance_name=cfg.reasoning_engine_name or None,
        )

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = build_platform_client(
                project_id=self.project_id,
                location=self.location,
                api_version=self.api_version,
            )
        return self._client

    @property
    def sandboxes(self) -> Any:
        return get_sandboxes_namespace(self.client)

    def _require_instance_name(self, instance_name: str | None = None) -> str:
        resolved = (instance_name or self.instance_name).strip()
        if not resolved:
            raise ValueError(
                "Parent Agent Platform instance_name (REASONING_ENGINE_NAME) is required. "
                "Set REASONING_ENGINE_NAME in `.env` or call ensure_parent_instance()."
            )
        return resolved

    def ensure_parent_instance(
        self,
        *,
        display_name: str | None = None,
        kms_key_name: str | None = None,
    ) -> str:
        """Return existing parent ``ReasoningEngine`` resource name or create an empty one.

        Scale Sandboxes do NOT require deploying agent code to Agent Runtime — an empty
        parent instance takes only seconds to provision. CMEK (single-region KMS key)
        must be configured here if required, because encryption_spec is immutable.
        """
        if self.instance_name:
            return self.instance_name

        runtimes_ns = get_runtimes_namespace(self.client)
        config: dict[str, Any] = {}
        if display_name:
            config["display_name"] = display_name
        if kms_key_name:
            config["encryption_spec"] = {"kms_key_name": kms_key_name}

        remote_agent = runtimes_ns.create(config=config) if config else runtimes_ns.create()
        api_resource = getattr(remote_agent, "api_resource", remote_agent)
        self.instance_name = str(api_resource.name)
        logger.info("Created parent Agent Platform instance: %s", self.instance_name)
        return self.instance_name

    # -- Payload Builders (ready to use in starter & solution) ---------------

    @staticmethod
    def build_byoc_template_config(
        *,
        image_uri: str,
        resources: TemplateResourceConfig | None = None,
        ports: list[TemplatePortConfig] | None = None,
        egress: EgressControlConfig | None = None,
        enable_private_ingress: bool = False,
    ) -> dict[str, Any]:
        """Build a verified ``custom_container_environment`` template config dict."""
        res = resources or TemplateResourceConfig()
        port_list = ports or [TemplatePortConfig(port=8080, protocol="TCP")]
        egress_cfg = egress or EgressControlConfig(internet_access=False)

        config: dict[str, Any] = {
            "custom_container_environment": {
                "custom_container_spec": {"image_uri": image_uri},
                "resources": res.to_payload(),
                "ports": [p.to_payload() for p in port_list],
            },
            "egress_control_config": egress_cfg.to_payload(),
        }
        if enable_private_ingress:
            config["ingress_control_config"] = {
                "private_service_connect_config": {
                    "enable_private_service_connect": True,
                }
            }
        return config

    @staticmethod
    def build_default_container_template_config(
        *,
        category: Literal["shell", "computer_use"] = "shell",
        egress: EgressControlConfig | None = None,
    ) -> dict[str, Any]:
        """Build a reusable Shell or Computer Use ``default_container_environment`` dict."""
        if category not in DEFAULT_CONTAINER_CATEGORIES:
            raise ValueError(f"Unsupported default container category: {category!r}")
        egress_cfg = egress or EgressControlConfig(internet_access=False)
        return {
            "default_container_environment": {
                "default_container_category": DEFAULT_CONTAINER_CATEGORIES[category],
            },
            "egress_control_config": egress_cfg.to_payload(),
        }

    def _wait_for_delete_operation(
        self,
        operation: Any,
        *,
        resource_name: str,
        namespace_obj: Any = None,
        get_operation_fn: Callable[..., Any] | None = None,
        get_resource_fn: Callable[..., Any] | None = None,
        poll_interval_seconds: float = 1.0,
        timeout_seconds: float = 180.0,
    ) -> None:
        """Poll a sandbox/snapshot/template delete LRO until terminal completion."""
        if operation is None:
            return
        if getattr(operation, "done", None) is True:
            op_err = getattr(operation, "error", None)
            if op_err:
                raise RuntimeError(f"Delete operation failed for {resource_name}: {op_err}")
            return

        op_name = str(getattr(operation, "name", "") or "")
        if not op_name:
            return

        api_client = getattr(namespace_obj, "_api_client", None) or getattr(
            self.sandboxes, "_api_client", None
        )
        deadline = time.monotonic() + timeout_seconds
        use_typed_getter = callable(get_operation_fn)

        while True:
            done = False
            op_error: Any = None
            polled_via_lro = False

            if use_typed_getter and callable(get_operation_fn):
                try:
                    polled = get_operation_fn(operation_name=op_name)
                    done = bool(getattr(polled, "done", False))
                    op_error = getattr(polled, "error", None)
                    polled_via_lro = True
                except Exception as exc:
                    if _is_not_found_error(exc):
                        return
                    # Delete LROs return google.protobuf.Empty in `response`, which
                    # typed create-operation models can reject on strict validation.
                    use_typed_getter = False
                    logger.debug(
                        "Falling back from typed LRO getter for %s (%s).",
                        op_name,
                        exc,
                    )

            if not polled_via_lro and api_client is not None and callable(getattr(api_client, "request", None)):
                try:
                    raw_resp = api_client.request("get", op_name, {}, None)
                    body = getattr(raw_resp, "body", "") or ""
                    parsed = json.loads(body) if body else {}
                    done = bool(parsed.get("done", False))
                    op_error = parsed.get("error")
                    polled_via_lro = True
                except Exception as exc:
                    if _is_not_found_error(exc):
                        return
                    logger.debug("Raw LRO poll failed for %s (%s).", op_name, exc)

            if not polled_via_lro and callable(get_resource_fn):
                try:
                    get_resource_fn(name=resource_name)
                except Exception as exc:
                    if _is_not_found_error(exc):
                        return
                    raise

            if done:
                if op_error:
                    raise RuntimeError(f"Delete operation {op_name} failed: {op_error}")
                return

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out after {timeout_seconds:.0f}s waiting for delete LRO "
                    f"{op_name} ({resource_name})."
                )
            time.sleep(poll_interval_seconds)

    def _delete_with_retry(
        self,
        delete_fn: Callable[..., Any],
        *,
        resource_name: str,
        resource_kind: str,
        namespace_obj: Any = None,
        get_operation_fn: Callable[..., Any] | None = None,
        get_resource_fn: Callable[..., Any] | None = None,
        wait_for_completion: bool = True,
        max_attempts: int = 6,
        initial_backoff_seconds: float = 2.0,
        timeout_seconds: float = 180.0,
    ) -> None:
        """Delete a resource, polling its LRO and retrying transient ``FAILED_PRECONDITION``."""
        for attempt in range(1, max_attempts + 1):
            try:
                operation = delete_fn(name=resource_name)
                if wait_for_completion:
                    self._wait_for_delete_operation(
                        operation,
                        resource_name=resource_name,
                        namespace_obj=namespace_obj,
                        get_operation_fn=get_operation_fn,
                        get_resource_fn=get_resource_fn,
                        timeout_seconds=timeout_seconds,
                    )
                return
            except Exception as exc:
                if _is_not_found_error(exc):
                    logger.info("%s already deleted: %s", resource_kind, resource_name)
                    return
                if _is_transient_delete_precondition_error(exc) and attempt < max_attempts:
                    delay = min(initial_backoff_seconds * attempt, 15.0)
                    logger.info(
                        "Transient FAILED_PRECONDITION deleting %s %s (attempt %d/%d); "
                        "retrying in %.1fs while child resources finalize...",
                        resource_kind,
                        resource_name,
                        attempt,
                        max_attempts,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                raise

    # -- Template Lifecycle (Create / Get / List / Update / Delete) ----------

    def create_template(
        self,
        *,
        display_name: str,
        kind: TemplateKind = "byoc",
        image_uri: str | None = None,
        resources: TemplateResourceConfig | None = None,
        ports: list[TemplatePortConfig] | None = None,
        egress: EgressControlConfig | None = None,
        enable_private_ingress: bool = False,
        instance_name: str | None = None,
    ) -> TemplateSummary:
        """Create a reusable ``SandboxEnvironmentTemplate`` (BYOC, Shell, or Computer Use).

        Creating a template triggers pre-warmed pool creation so subsequent sandboxes
        spin up in seconds instead of up to 2 minutes. Always capture the returned
        ``operation.response.name`` dynamically.
        """
        parent_name = self._require_instance_name(instance_name)
        if kind == "byoc":
            if not image_uri:
                raise ValueError("image_uri is required when creating a BYOC template.")
            config = self.build_byoc_template_config(
                image_uri=image_uri,
                resources=resources,
                ports=ports,
                egress=egress,
                enable_private_ingress=enable_private_ingress,
            )
        else:
            config = self.build_default_container_template_config(
                category=kind,
                egress=egress,
            )

        # TODO(lab-2): Call ``self.sandboxes.templates.create(name=parent_name,
        # display_name=display_name, config=config)``, extract ``_extract_response(op)``,
        # and return ``_summarize_template(resource)``.
        _ = (parent_name, display_name, config)
        raise NotImplementedError("Complete TODO(lab-2): SandboxLifecycleManager.create_template")

    def get_template(self, template_name: str) -> TemplateSummary:
        """Fetch metadata and configuration for a single ``SandboxEnvironmentTemplate``."""
        # Pre-filled boilerplate helper (already working for the workshop)
        resource = self.sandboxes.templates.get(name=template_name)
        return _summarize_template(resource)

    def list_templates(self, instance_name: str | None = None) -> list[TemplateSummary]:
        """List all ``SandboxEnvironmentTemplate`` resources under the parent instance."""
        # Pre-filled boilerplate helper (already working for the workshop)
        parent_name = self._require_instance_name(instance_name)
        response = self.sandboxes.templates.list(name=parent_name)
        items = getattr(response, "sandbox_environment_templates", response) or []
        return [_summarize_template(tpl) for tpl in items]

    def update_template(
        self,
        old_template_name: str,
        *,
        display_name: str,
        kind: TemplateKind = "byoc",
        image_uri: str | None = None,
        resources: TemplateResourceConfig | None = None,
        ports: list[TemplatePortConfig] | None = None,
        egress: EgressControlConfig | None = None,
        enable_private_ingress: bool = False,
        instance_name: str | None = None,
    ) -> TemplateSummary:
        """Update a template via the documented delete-and-recreate pattern.

        Per ``scale/sandbox/manage-templates``, no in-place SDK update method is
        documented: delete the existing template (fails if warm pool or sandbox
        creation is actively in progress) and create a new template with the updated
        configuration.
        """
        # Pre-filled boilerplate helper (already working for the workshop)
        parent = instance_name or self.instance_name or _infer_parent_instance(old_template_name)
        self.delete_template(old_template_name, wait_for_completion=True)
        return self.create_template(
            display_name=display_name,
            kind=kind,
            image_uri=image_uri,
            resources=resources,
            ports=ports,
            egress=egress,
            enable_private_ingress=enable_private_ingress,
            instance_name=parent or None,
        )

    def delete_template(
        self,
        template_name: str,
        *,
        wait_for_completion: bool = True,
    ) -> None:
        """Delete a ``SandboxEnvironmentTemplate`` and wait for LRO completion by default."""
        # Pre-filled boilerplate helper (already working for the workshop)
        self._delete_with_retry(
            self.sandboxes.templates.delete,
            resource_name=template_name,
            resource_kind="sandbox template",
            namespace_obj=self.sandboxes.templates,
            get_operation_fn=getattr(
                self.sandboxes.templates,
                "get_sandbox_environment_template_operation",
                None,
            ),
            get_resource_fn=getattr(self.sandboxes.templates, "get", None),
            wait_for_completion=wait_for_completion,
        )
        logger.info("Deleted sandbox template: %s", template_name)

    # -- Sandbox Lifecycle (Create / Get / List / Pause / Resume / Snapshot / Delete) --

    def create_sandbox(
        self,
        *,
        display_name: str = "coding-agent-sandbox",
        template_name: str | None = None,
        snapshot_name: str | None = None,
        spec: dict[str, Any] | None = None,
        ttl: str = "3600s",
        wait_for_completion: bool = True,
        instance_name: str | None = None,
    ) -> SandboxSummary:
        """Provision a Managed Sandbox from a template, direct ``spec``, or snapshot.

        Must supply at least one of ``spec`` (e.g. ``{"shell_environment": {}}`` or
        ``{"code_execution_environment": {"code_language": "LANGUAGE_PYTHON"}}``),
        ``template_name``, or ``snapshot_name``.
        """
        parent_name = self._require_instance_name(instance_name)
        if not any((spec, template_name, snapshot_name)):
            raise ValueError(
                "create_sandbox() requires at least one of `spec`, `template_name`, "
                "or `snapshot_name`."
            )

        config: dict[str, Any] = {
            "display_name": display_name,
            "ttl": ttl,
            "wait_for_completion": wait_for_completion,
        }
        if template_name:
            config["sandbox_environment_template"] = template_name
        if snapshot_name:
            config["sandbox_environment_snapshot"] = snapshot_name

        # TODO(lab-2): Call ``self.sandboxes.create(name=parent_name, spec=spec, config=config)``
        # (omit ``spec`` when ``spec is None``), extract ``_extract_response(op)``, and return
        # ``_summarize_sandbox(sandbox)``.
        _ = (parent_name, spec, config)
        raise NotImplementedError("Complete TODO(lab-2): SandboxLifecycleManager.create_sandbox")

    def get_sandbox(self, sandbox_name: str) -> SandboxSummary:
        """Fetch live state, template link, expiry, and optional PSC-E service attachment."""
        # Pre-filled boilerplate helper (already working for the workshop)
        resource = self.sandboxes.get(name=sandbox_name)
        return _summarize_sandbox(resource)

    def list_sandboxes(self, instance_name: str | None = None) -> list[SandboxSummary]:
        """List all ``SandboxEnvironment`` instances under the parent Agent Platform instance."""
        # Pre-filled boilerplate helper (already working for the workshop)
        parent_name = self._require_instance_name(instance_name)
        response = self.sandboxes.list(name=parent_name)
        items = getattr(response, "sandbox_environments", response) or []
        return [_summarize_sandbox(sb) for sb in items]

    def pause_sandbox(
        self,
        sandbox_name: str,
        *,
        wait_for_completion: bool = True,
    ) -> SandboxSummary:
        """Pause a running sandbox to release compute while keeping disk state & connection ID."""
        # TODO(lab-2): Call ``self.sandboxes.pause(name=sandbox_name,
        # config={"wait_for_completion": wait_for_completion})``, extract response,
        # and return ``_summarize_sandbox(paused)``.
        _ = (sandbox_name, wait_for_completion)
        raise NotImplementedError("Complete TODO(lab-2): SandboxLifecycleManager.pause_sandbox")

    def resume_sandbox(
        self,
        sandbox_name: str,
        *,
        wait_for_completion: bool = True,
    ) -> SandboxSummary:
        """Resume a ``STATE_PAUSED`` sandbox back to ``STATE_RUNNING`` in seconds.

        NOTE: Calling ``resume()`` on an already-running sandbox raises ``FAILED_PRECONDITION``.
        """
        # Pre-filled boilerplate helper (already working for the workshop)
        operation = self.sandboxes.resume(
            name=sandbox_name,
            config={"wait_for_completion": wait_for_completion},
        )
        summary = _summarize_sandbox(_extract_response(operation))
        logger.info("Resumed sandbox: %s (state=%s)", summary.name or sandbox_name, summary.state)
        return summary

    def snapshot_sandbox(
        self,
        sandbox_name: str,
        *,
        display_name: str,
        ttl: str = "3600s",
        wait_for_completion: bool = True,
        instance_name: str | None = None,
    ) -> SnapshotSummary:
        """Snapshot disk, installed libraries, and memory state to managed GCS.

        Constraints:
        - NOT supported for Code Execution sandboxes.
        - Restoring from a snapshot fails if CPU architecture, runtime version, or
          container ``image_uri`` differs.
        - Always resolve ``snapshot_name`` dynamically from ``snap_op.response.name``
          or by matching ``display_name`` via ``list_snapshots()`` (never hardcode paths).
        """
        # TODO(lab-2): Call ``self.sandboxes.snapshots.create(
        # source_sandbox_environment_name=sandbox_name,
        # config={"display_name": display_name, "ttl": ttl,
        #         "wait_for_completion": wait_for_completion})``,
        # resolve the snapshot resource name dynamically from ``op.response.name`` (falling back
        # to matching ``display_name`` in ``self.list_snapshots(instance_name)``), and return
        # ``SnapshotSummary``.
        _ = (sandbox_name, display_name, ttl, wait_for_completion, instance_name)
        raise NotImplementedError("Complete TODO(lab-2): SandboxLifecycleManager.snapshot_sandbox")

    def delete_sandbox(
        self,
        sandbox_name: str,
        *,
        wait_for_completion: bool = True,
    ) -> None:
        """Delete a sandbox to stop billing (does NOT delete its backing template)."""
        # Pre-filled boilerplate helper (already working for the workshop)
        self._delete_with_retry(
            self.sandboxes.delete,
            resource_name=sandbox_name,
            resource_kind="sandbox",
            namespace_obj=self.sandboxes,
            get_operation_fn=getattr(self.sandboxes, "_get_sandbox_operation", None),
            get_resource_fn=getattr(self.sandboxes, "get", None),
            wait_for_completion=wait_for_completion,
        )
        logger.info("Deleted sandbox: %s", sandbox_name)

    # -- Snapshot Lifecycle (List / Get / Delete) ----------------------------

    def list_snapshots(self, instance_name: str | None = None) -> list[SnapshotSummary]:
        """List all ``SandboxEnvironmentSnapshot`` resources under the parent instance."""
        # Pre-filled boilerplate helper (already working for the workshop)
        parent_name = self._require_instance_name(instance_name)
        response = self.sandboxes.snapshots.list(name=parent_name)
        items = getattr(response, "sandbox_environment_snapshots", response) or []
        return [_summarize_snapshot(snap) for snap in items]

    def get_snapshot(self, snapshot_name: str) -> SnapshotSummary:
        """Fetch metadata for a specific ``SandboxEnvironmentSnapshot``."""
        # Pre-filled boilerplate helper (already working for the workshop)
        resource = self.sandboxes.snapshots.get(name=snapshot_name)
        return _summarize_snapshot(resource)

    def delete_snapshot(
        self,
        snapshot_name: str,
        *,
        wait_for_completion: bool = True,
    ) -> None:
        """Delete a ``SandboxEnvironmentSnapshot`` prior to its TTL expiration."""
        # Pre-filled boilerplate helper (already working for the workshop)
        self._delete_with_retry(
            self.sandboxes.snapshots.delete,
            resource_name=snapshot_name,
            resource_kind="snapshot",
            namespace_obj=self.sandboxes.snapshots,
            get_operation_fn=getattr(
                self.sandboxes.snapshots,
                "get_sandbox_snapshot_operation",
                None,
            ),
            get_resource_fn=getattr(self.sandboxes.snapshots, "get", None),
            wait_for_completion=wait_for_completion,
        )
        logger.info("Deleted snapshot: %s", snapshot_name)

    # -- End-to-End Lifecycle Demo & Cleanup ---------------------------------

    def run_lifecycle_demo(
        self,
        *,
        mode: Literal["shell", "byoc", "code_execution"] = "shell",
        ttl: str = "1800s",
        image_uri: str | None = None,
        keep_resources: bool = False,
    ) -> dict[str, Any]:
        """Execute a complete Template -> Create -> Pause -> Resume -> Snapshot -> Cleanup demo."""
        parent = self.ensure_parent_instance(display_name="workshop-sandbox-parent")
        report: dict[str, Any] = {"instance_name": parent, "mode": mode, "steps": []}

        template: TemplateSummary | None = None
        sandbox: SandboxSummary | None = None
        branched: SandboxSummary | None = None
        snapshot: SnapshotSummary | None = None

        try:
            t0 = time.monotonic()
            if mode == "byoc":
                if not image_uri:
                    raise ValueError("--image-uri (or SANDBOX_IMAGE_URI) is required for BYOC demo.")
                template = self.create_template(
                    display_name="workshop-byoc-demo-template",
                    kind="byoc",
                    image_uri=image_uri,
                )
                report["steps"].append(
                    {"step": "create_template", "name": template.name, "elapsed_s": round(time.monotonic() - t0, 2)}
                )
                t1 = time.monotonic()
                sandbox = self.create_sandbox(
                    display_name="workshop-byoc-demo-sandbox",
                    template_name=template.name,
                    ttl=ttl,
                )
            elif mode == "shell":
                template = self.create_template(
                    display_name="workshop-shell-demo-template",
                    kind="shell",
                )
                report["steps"].append(
                    {"step": "create_template", "name": template.name, "elapsed_s": round(time.monotonic() - t0, 2)}
                )
                t1 = time.monotonic()
                sandbox = self.create_sandbox(
                    display_name="workshop-shell-demo-sandbox",
                    template_name=template.name,
                    spec={"shell_environment": {}},
                    ttl=ttl,
                )
            else:
                t1 = time.monotonic()
                sandbox = self.create_sandbox(
                    display_name="workshop-code-exec-demo-sandbox",
                    spec={
                        "code_execution_environment": {
                            "code_language": "LANGUAGE_PYTHON",
                            "machine_config": "MACHINE_CONFIG_VCPU4_RAM4GIB",
                        }
                    },
                    ttl=ttl,
                )
            report["steps"].append(
                {
                    "step": "create_sandbox",
                    "name": sandbox.name,
                    "state": sandbox.state,
                    "elapsed_s": round(time.monotonic() - t1, 2),
                }
            )

            fetched = self.get_sandbox(sandbox.name)
            report["steps"].append({"step": "get_sandbox", "state": fetched.state})

            if mode != "code_execution":
                t_pause = time.monotonic()
                paused = self.pause_sandbox(sandbox.name, wait_for_completion=True)
                report["steps"].append(
                    {"step": "pause_sandbox", "state": paused.state, "elapsed_s": round(time.monotonic() - t_pause, 2)}
                )

                t_resume = time.monotonic()
                resumed = self.resume_sandbox(sandbox.name, wait_for_completion=True)
                report["steps"].append(
                    {"step": "resume_sandbox", "state": resumed.state, "elapsed_s": round(time.monotonic() - t_resume, 2)}
                )

                t_snap = time.monotonic()
                snapshot = self.snapshot_sandbox(
                    sandbox.name,
                    display_name=f"workshop-demo-snap-{int(time.time())}",
                    ttl=ttl,
                )
                report["steps"].append(
                    {"step": "snapshot_sandbox", "name": snapshot.name, "elapsed_s": round(time.monotonic() - t_snap, 2)}
                )

                t_branch = time.monotonic()
                branched = self.create_sandbox(
                    display_name="workshop-demo-branched-sandbox",
                    snapshot_name=snapshot.name,
                    ttl=ttl,
                )
                report["steps"].append(
                    {
                        "step": "restore_from_snapshot",
                        "name": branched.name,
                        "state": branched.state,
                        "elapsed_s": round(time.monotonic() - t_branch, 2),
                    }
                )
        finally:
            if not keep_resources:
                # Delete strictly sequentially with LRO completion: sandboxes -> snapshots -> templates
                for sb in (branched, sandbox):
                    if sb is not None:
                        try:
                            self.delete_sandbox(sb.name, wait_for_completion=True)
                            report["steps"].append({"step": "delete_sandbox", "name": sb.name})
                        except Exception as exc:
                            logger.warning("Cleanup delete_sandbox(%s) failed: %s", sb.name, exc)
                if snapshot is not None:
                    try:
                        self.delete_snapshot(snapshot.name, wait_for_completion=True)
                        report["steps"].append({"step": "delete_snapshot", "name": snapshot.name})
                    except Exception as exc:
                        logger.warning("Cleanup delete_snapshot(%s) failed: %s", snapshot.name, exc)
                if template is not None:
                    try:
                        self.delete_template(template.name, wait_for_completion=True)
                        report["steps"].append({"step": "delete_template", "name": template.name})
                    except Exception as exc:
                        logger.warning("Cleanup delete_template(%s) failed: %s", template.name, exc)

        return report

    def cleanup_all(self, *, include_templates: bool = False) -> dict[str, int]:
        """Delete all sandboxes and snapshots (and optionally templates) sequentially."""
        deleted = {"sandboxes": 0, "snapshots": 0, "templates": 0}
        for sb in self.list_sandboxes():
            self.delete_sandbox(sb.name, wait_for_completion=True)
            deleted["sandboxes"] += 1
        for snap in self.list_snapshots():
            self.delete_snapshot(snap.name, wait_for_completion=True)
            deleted["snapshots"] += 1
        if include_templates:
            for tpl in self.list_templates():
                self.delete_template(tpl.name, wait_for_completion=True)
                deleted["templates"] += 1
        return deleted


# ---------------------------------------------------------------------------
# Runnable CLI (`python -m coding_agent.tools.sandbox_lifecycle ...`)
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m coding_agent.tools.sandbox_lifecycle",
        description="Manage Gemini Enterprise Agent Platform Sandbox Templates, Sandboxes, and Snapshots.",
    )
    parser.add_argument("--project", help="GCP project ID (defaults to GOOGLE_CLOUD_PROJECT).")
    parser.add_argument("--location", help="GCP region (defaults to GOOGLE_CLOUD_LOCATION).")
    parser.add_argument("--instance", help="Parent ReasoningEngine resource name.")
    sub = parser.add_subparsers(dest="command", required=True)

    # demo
    p_demo = sub.add_parser("demo", help="Run full template -> sandbox -> pause/resume -> snapshot -> delete demo.")
    p_demo.add_argument("--mode", choices=["shell", "byoc", "code_execution"], default="shell")
    p_demo.add_argument("--ttl", default="1800s")
    p_demo.add_argument("--image-uri", default=None)
    p_demo.add_argument("--keep", action="store_true", help="Keep demo resources instead of cleaning up.")

    # create-instance
    p_inst = sub.add_parser("create-instance", help="Create an empty parent Agent Platform instance.")
    p_inst.add_argument("--display-name", default="workshop-sandbox-parent")
    p_inst.add_argument("--kms-key", default=None, help="Optional single-region CMEK KMS cryptoKey name.")

    # templates
    p_ct = sub.add_parser("create-template", help="Create a BYOC, Shell, or Computer Use template.")
    p_ct.add_argument("--kind", choices=["byoc", "shell", "computer_use"], default="byoc")
    p_ct.add_argument("--display-name", required=True)
    p_ct.add_argument("--image-uri", default=None)
    p_ct.add_argument("--port", type=int, default=8080)
    p_ct.add_argument("--cpu-request", default="1")
    p_ct.add_argument("--memory-request", default="1Gi")
    p_ct.add_argument("--cpu-limit", default="2")
    p_ct.add_argument("--memory-limit", default="2Gi")
    p_ct.add_argument("--internet-access", action="store_true")
    p_ct.add_argument("--vpc-network", default=None)
    p_ct.add_argument("--network-attachment", default=None)
    p_ct.add_argument("--enable-psc-e", action="store_true")

    sub.add_parser("list-templates", help="List sandbox templates.")
    p_gt = sub.add_parser("get-template", help="Get sandbox template details.")
    p_gt.add_argument("--name", required=True)

    p_ut = sub.add_parser("update-template", help="Delete and recreate a sandbox template.")
    p_ut.add_argument("--old-name", required=True)
    p_ut.add_argument("--kind", choices=["byoc", "shell", "computer_use"], default="byoc")
    p_ut.add_argument("--display-name", required=True)
    p_ut.add_argument("--image-uri", default=None)
    p_ut.add_argument("--port", type=int, default=8080)
    p_ut.add_argument("--internet-access", action="store_true")

    p_dt = sub.add_parser("delete-template", help="Delete a sandbox template.")
    p_dt.add_argument("--name", required=True)

    # sandboxes
    p_cs = sub.add_parser("create-sandbox", help="Create a sandbox environment.")
    p_cs.add_argument("--mode", choices=["shell", "byoc", "code_execution", "snapshot"], default="shell")
    p_cs.add_argument("--display-name", default="coding-agent-sandbox")
    p_cs.add_argument("--template", default=None)
    p_cs.add_argument("--snapshot", default=None)
    p_cs.add_argument("--language", choices=["LANGUAGE_PYTHON", "LANGUAGE_JAVASCRIPT"], default="LANGUAGE_PYTHON")
    p_cs.add_argument("--ttl", default="3600s")

    sub.add_parser("list-sandboxes", help="List sandboxes under parent instance.")
    p_gs = sub.add_parser("get-sandbox", help="Get sandbox details.")
    p_gs.add_argument("--name", required=True)
    p_ps = sub.add_parser("pause-sandbox", help="Pause a running sandbox.")
    p_ps.add_argument("--name", required=True)
    p_rs = sub.add_parser("resume-sandbox", help="Resume a paused sandbox.")
    p_rs.add_argument("--name", required=True)
    p_ds = sub.add_parser("delete-sandbox", help="Delete a sandbox.")
    p_ds.add_argument("--name", required=True)

    # snapshots
    p_sn = sub.add_parser("snapshot-sandbox", help="Snapshot a sandbox environment.")
    p_sn.add_argument("--name", required=True)
    p_sn.add_argument("--display-name", required=True)
    p_sn.add_argument("--ttl", default="3600s")

    sub.add_parser("list-snapshots", help="List snapshots under parent instance.")
    p_gsn = sub.add_parser("get-snapshot", help="Get snapshot details.")
    p_gsn.add_argument("--name", required=True)
    p_dsn = sub.add_parser("delete-snapshot", help="Delete a snapshot.")
    p_dsn.add_argument("--name", required=True)

    # cleanup-all
    p_clean = sub.add_parser("cleanup-all", help="Delete all sandboxes and snapshots under parent instance.")
    p_clean.add_argument("--include-templates", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_arg_parser().parse_args(argv)
    settings = get_settings()

    project_id = args.project or settings.require_gcp_project()
    location = args.location or settings.google_cloud_location
    instance_name = args.instance or settings.reasoning_engine_name or None
    manager = SandboxLifecycleManager(
        project_id=project_id,
        location=location,
        instance_name=instance_name,
    )

    output: Any
    if args.command == "demo":
        output = manager.run_lifecycle_demo(
            mode=args.mode,
            ttl=args.ttl,
            image_uri=args.image_uri or settings.sandbox_image_uri or None,
            keep_resources=args.keep,
        )
    elif args.command == "create-instance":
        output = {
            "instance_name": manager.ensure_parent_instance(
                display_name=args.display_name,
                kms_key_name=args.kms_key,
            )
        }
    elif args.command == "create-template":
        output = manager.create_template(
            display_name=args.display_name,
            kind=args.kind,
            image_uri=args.image_uri or settings.sandbox_image_uri or None,
            resources=TemplateResourceConfig(
                cpu_request=args.cpu_request,
                memory_request=args.memory_request,
                cpu_limit=args.cpu_limit,
                memory_limit=args.memory_limit,
            ),
            ports=[TemplatePortConfig(port=args.port, protocol="TCP")],
            egress=EgressControlConfig(
                internet_access=args.internet_access,
                customer_vpc_network=args.vpc_network,
                network_attachment=args.network_attachment,
            ),
            enable_private_ingress=args.enable_psc_e,
        ).to_dict()
    elif args.command == "list-templates":
        output = [t.to_dict() for t in manager.list_templates()]
    elif args.command == "get-template":
        output = manager.get_template(args.name).to_dict()
    elif args.command == "update-template":
        output = manager.update_template(
            args.old_name,
            display_name=args.display_name,
            kind=args.kind,
            image_uri=args.image_uri or settings.sandbox_image_uri or None,
            ports=[TemplatePortConfig(port=args.port, protocol="TCP")],
            egress=EgressControlConfig(internet_access=args.internet_access),
        ).to_dict()
    elif args.command == "delete-template":
        manager.delete_template(args.name)
        output = {"deleted_template": args.name}
    elif args.command == "create-sandbox":
        template_name = args.template or (settings.sandbox_template_name if args.mode == "byoc" else None) or None
        spec: dict[str, Any] | None = None
        if template_name is None and args.snapshot is None:
            if args.mode == "shell":
                spec = {"shell_environment": {}}
            elif args.mode == "code_execution":
                spec = {
                    "code_execution_environment": {
                        "code_language": args.language,
                        "machine_config": "MACHINE_CONFIG_VCPU4_RAM4GIB",
                    }
                }
        output = manager.create_sandbox(
            display_name=args.display_name,
            template_name=template_name,
            snapshot_name=args.snapshot,
            spec=spec,
            ttl=args.ttl,
        ).to_dict()
    elif args.command == "list-sandboxes":
        output = [s.to_dict() for s in manager.list_sandboxes()]
    elif args.command == "get-sandbox":
        output = manager.get_sandbox(args.name).to_dict()
    elif args.command == "pause-sandbox":
        output = manager.pause_sandbox(args.name).to_dict()
    elif args.command == "resume-sandbox":
        output = manager.resume_sandbox(args.name).to_dict()
    elif args.command == "delete-sandbox":
        manager.delete_sandbox(args.name)
        output = {"deleted_sandbox": args.name}
    elif args.command == "snapshot-sandbox":
        output = manager.snapshot_sandbox(
            args.name,
            display_name=args.display_name,
            ttl=args.ttl,
        ).to_dict()
    elif args.command == "list-snapshots":
        output = [s.to_dict() for s in manager.list_snapshots()]
    elif args.command == "get-snapshot":
        output = manager.get_snapshot(args.name).to_dict()
    elif args.command == "delete-snapshot":
        manager.delete_snapshot(args.name)
        output = {"deleted_snapshot": args.name}
    elif args.command == "cleanup-all":
        output = manager.cleanup_all(include_templates=args.include_templates)
    else:
        raise ValueError(f"Unknown command: {args.command}")

    print(json.dumps(output, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
