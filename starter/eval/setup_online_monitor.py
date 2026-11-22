"""Online Evaluation Monitor Prerequisite Validator & Spec Generator (Lab 6 — Starter).

Complete the ``# TODO(lab-6)`` blocks following ``workshop/06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md``.
Note: Official ``evaluate-online`` documentation creates ``OnlineEvaluator`` monitors
through the Cloud Console (no verified Python SDK creation method is published yet).
This script validates OTel telemetry prerequisites and emits the monitor spec +
Logs Explorer diagnostic queries.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

TRACK_ROOT = Path(__file__).resolve().parents[1]
if str(TRACK_ROOT) not in sys.path:
    sys.path.insert(0, str(TRACK_ROOT))

from coding_agent.config import get_settings  # noqa: E402
from eval.run_offline_eval import SUPPORTED_EVAL_LOCATIONS  # noqa: E402

logger = logging.getLogger(__name__)

VALID_PYTHON_CAPTURE_ENUMS: frozenset[str] = frozenset(
    {"NO_CONTENT", "EVENT_ONLY", "SPAN_ONLY", "SPAN_AND_EVENT"}
)

REQUIRED_OTEL_SIGNALS: dict[str, list[str]] = {
    "invoke_agent_span_attributes": [
        "gen_ai.agent.name",
        "gen_ai.agent.description",
        "gen_ai.conversation.id",
    ],
    "inference_event_attributes (gen_ai.client.inference.operation.details)": [
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "gen_ai.system_instructions",
        "gen_ai.tool.definitions",
    ],
}

DEFAULT_ONLINE_METRICS: list[str] = [
    "task_success",
    "tool_use_quality",
    "hallucination",
    "safety",
]


@dataclass(frozen=True)
class TelemetryCheckResult:
    """Validation outcome for Online Evaluation Monitor OTel prerequisites."""

    passed: bool
    errors: list[str]
    warnings: list[str]
    observed_env: dict[str, str]


def validate_otel_prerequisites(env: dict[str, str] | None = None) -> TelemetryCheckResult:
    """Validate mandatory OpenTelemetry GenAI v1.37.0+ env vars for ADK Python."""
    source = env if env is not None else dict(os.environ)
    # TODO(lab-6): Validate:
    # 1. GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY == "true"
    # 2. OTEL_SEMCONV_STABILITY_OPT_IN == "gen_ai_latest_experimental"
    # 3. OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT is in VALID_PYTHON_CAPTURE_ENUMS
    #    (explicitly reject boolean strings like "true"/"false" because ADK Python silently
    #    falls back to NO_CONTENT!).
    # 4. EVAL_LOCATION (defaulting to "global" when unset — never falling back to
    #    GOOGLE_CLOUD_LOCATION such as asia-southeast1) is in SUPPORTED_EVAL_LOCATIONS.
    # Return TelemetryCheckResult(passed=not errors, errors=..., warnings=..., observed_env=...).
    raise NotImplementedError(
        f"TODO(lab-6): Validate OTel prerequisites against {len(source)} env entries "
        f"(supported locations={len(SUPPORTED_EVAL_LOCATIONS)}, enums={sorted(VALID_PYTHON_CAPTURE_ENUMS)})."
    )


def build_online_monitor_spec(
    *,
    project_id: str,
    location: str,
    reasoning_engine_name: str,
    runtime_location: str | None = None,
    sampling_rate: float = 0.20,
    max_samples_per_run: int = 25,
    trace_filter: str = "ALL_TRACES",
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    """Build a verified Online Evaluation Monitor specification and ops runbook."""
    # TODO(lab-6): Validate sampling_rate in (0.0, 1.0] and max_samples_per_run > 0, then return
    # a dict documenting:
    # - Console provisioning URL (`https://console.cloud.google.com/agent-platform/agent-evaluation`)
    # - `target_agent_engine` using `runtime_location` (e.g., asia-southeast1) as fallback region
    # - 10-minute cadence, sampling_percentage, max_samples_per_run, trace_filter, metrics
    # - Exported Cloud Monitoring metrics (`aiplatform.googleapis.com/online_evaluator/scores`
    #   and `aiplatform.googleapis.com/online_evaluator/evaluations_count`)
    # - Operational warnings (first-monitor transient Failed up to 30m; P4SA project scope)
    # - Logs Explorer queries (`resource.labels.online_evaluator` in eval `location`, `labels.reasoning_engine_id`, `labels.trace`)
    raise NotImplementedError(
        f"TODO(lab-6): Build Online Monitor spec for project={project_id!r}, "
        f"eval_location={location!r}, runtime_location={runtime_location!r}, "
        f"engine={reasoning_engine_name!r}, rate={sampling_rate}, "
        f"max_samples={max_samples_per_run}, filter={trace_filter!r}, metrics={metrics!r}."
    )


def verify_deployed_runtime(project_id: str, location: str, reasoning_engine_name: str) -> dict[str, Any]:
    """Verify that the target ReasoningEngine exists using ``agentplatform`` or ``vertexai``."""
    client: Any
    sdk_used: str
    try:
        import agentplatform

        client = agentplatform.Client(project=project_id, location=location)
        sdk_used = "agentplatform"
        deployed = client.runtimes.get(name=reasoning_engine_name)
    except ImportError:
        from vertexai import Client

        client = Client(project=project_id, location=location)
        sdk_used = "vertexai"
        deployed = client.agent_engines.get(name=reasoning_engine_name)

    api_resource = getattr(deployed, "api_resource", deployed)
    spec = getattr(api_resource, "spec", None)
    return {
        "sdk_used": sdk_used,
        "name": getattr(api_resource, "name", reasoning_engine_name),
        "display_name": getattr(api_resource, "display_name", ""),
        "effective_identity": getattr(spec, "effective_identity", ""),
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate OTel telemetry prerequisites and generate Online Evaluation Monitor config.",
    )
    parser.add_argument("--project", help="GCP project ID (defaults to GOOGLE_CLOUD_PROJECT).")
    parser.add_argument(
        "--location",
        help="Eval region (14 supported US/EU regions or global; defaults to EVAL_LOCATION / 'global').",
    )
    parser.add_argument(
        "--runtime-location",
        help="Agent Runtime region for --verify-runtime and target_agent_engine fallback (defaults to GOOGLE_CLOUD_LOCATION).",
    )
    parser.add_argument("--agent-resource-name", help="Full ReasoningEngine resource name.")
    parser.add_argument(
        "--sampling-rate",
        type=float,
        default=float(os.environ.get("ONLINE_MONITOR_SAMPLING_RATE", "0.2")),
    )
    parser.add_argument(
        "--max-samples-per-run",
        type=int,
        default=int(os.environ.get("ONLINE_MONITOR_MAX_SAMPLES_PER_RUN", "25")),
    )
    parser.add_argument("--trace-filter", default="ALL_TRACES")
    parser.add_argument("--metrics", default=",".join(DEFAULT_ONLINE_METRICS))
    parser.add_argument(
        "--verify-runtime",
        action="store_true",
        help="Call Agent Platform API to verify the deployed ReasoningEngine resource.",
    )
    parser.add_argument("--strict-env", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_arg_parser().parse_args(argv)
    settings = get_settings()

    project_id = args.project or settings.google_cloud_project
    runtime_location = (args.runtime_location or "").strip() or settings.google_cloud_location
    eval_location = (
        (args.location or "").strip()
        or os.environ.get("EVAL_LOCATION", "").strip()
        or settings.eval_location
    )
    runtime_name = args.agent_resource_name or settings.reasoning_engine_name
    metrics = [m.strip() for m in args.metrics.split(",") if m.strip()]

    otel_check = validate_otel_prerequisites()
    monitor_spec = build_online_monitor_spec(
        project_id=project_id,
        location=eval_location,
        runtime_location=runtime_location,
        reasoning_engine_name=runtime_name,
        sampling_rate=args.sampling_rate,
        max_samples_per_run=args.max_samples_per_run,
        trace_filter=args.trace_filter,
        metrics=metrics,
    )

    output: dict[str, Any] = {
        "otel_prerequisite_check": asdict(otel_check),
        "online_monitor_spec": monitor_spec,
    }

    if args.verify_runtime:
        if not project_id or not runtime_name:
            raise ValueError("--verify-runtime requires GOOGLE_CLOUD_PROJECT and REASONING_ENGINE_NAME.")
        output["runtime_verification"] = verify_deployed_runtime(
            project_id, runtime_location, runtime_name
        )

    print(json.dumps(output, indent=2))
    if args.strict_env and not otel_check.passed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
