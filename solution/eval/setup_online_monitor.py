"""Online Evaluation Monitor Prerequisite Validator & Spec Generator (Lab 6 — Solution).

Verified API Transparency Note (from official ``evaluate-online`` docs):
Google Cloud currently documents creating and managing ``OnlineEvaluator``
monitors via the Cloud Console (``Agent Platform -> Agents -> Evaluation ->
Online monitors``) without a published Python SDK ``create_online_monitor()``
signature. Rather than inventing an undocumented SDK call, this script:
1. Validates all mandatory OpenTelemetry GenAI Semantic Convention (v1.37.0+)
   environment prerequisites — including catching the ADK Python boolean vs.
   enum trap on ``OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT``.
2. Optionally verifies the deployed ``ReasoningEngine`` resource in GCP.
3. Emits a complete Online Monitor specification (sampling rate, max samples
   per 10-minute cycle, trace filters, metrics, exported Cloud Monitoring
   descriptors, operational P4SA warnings, and Logs Explorer diagnostic queries).
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
    errors: list[str] = []
    warnings: list[str] = []

    enable_telemetry = source.get("GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY", "").strip()
    semconv_opt_in = source.get("OTEL_SEMCONV_STABILITY_OPT_IN", "").strip()
    capture_mode = source.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "").strip()
    upload_hook = source.get("OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK", "").strip()
    upload_base = source.get("OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH", "").strip()
    eval_location = (
        source.get("EVAL_LOCATION") or source.get("GOOGLE_CLOUD_LOCATION") or "us-central1"
    ).strip()

    if enable_telemetry.lower() != "true":
        errors.append(
            "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY must be 'true' "
            f"(observed: {enable_telemetry!r}). Replaces deprecated enable_tracing=True."
        )

    if semconv_opt_in != "gen_ai_latest_experimental":
        errors.append(
            "OTEL_SEMCONV_STABILITY_OPT_IN must be 'gen_ai_latest_experimental' "
            f"(observed: {semconv_opt_in!r}) to emit OTel GenAI v1.37.0+ spans/events."
        )

    if capture_mode.lower() in {"true", "false", "1", "0"}:
        errors.append(
            f"ADK Python trap: OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT={capture_mode!r} "
            "is invalid in Python and silently falls back to NO_CONTENT! "
            "Use one of: EVENT_ONLY, SPAN_ONLY, SPAN_AND_EVENT, or NO_CONTENT (with GCS upload)."
        )
    elif capture_mode not in VALID_PYTHON_CAPTURE_ENUMS:
        errors.append(
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT must be one of "
            f"{sorted(VALID_PYTHON_CAPTURE_ENUMS)} (observed: {capture_mode!r})."
        )
    elif capture_mode == "NO_CONTENT" and not (upload_hook == "upload" and upload_base.startswith("gs://")):
        warnings.append(
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT is NO_CONTENT without "
            "GCS completion offloading (OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK=upload + "
            "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH=gs://...). Online Monitors will "
            "have no prompt/response content to grade; set EVENT_ONLY for Cloud Logging capture."
        )

    if eval_location not in SUPPORTED_EVAL_LOCATIONS:
        errors.append(
            f"Evaluation location {eval_location!r} is not in the 15 supported regions + global."
        )

    if upload_hook == "upload" and not upload_base.startswith("gs://"):
        errors.append(
            "OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK='upload' requires "
            "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH='gs://<bucket>/<prefix>'."
        )

    observed_env = {
        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": enable_telemetry,
        "OTEL_SEMCONV_STABILITY_OPT_IN": semconv_opt_in,
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": capture_mode,
        "OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK": upload_hook,
        "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH": upload_base,
        "EVAL_LOCATION": eval_location,
    }
    return TelemetryCheckResult(
        passed=not errors,
        errors=errors,
        warnings=warnings,
        observed_env=observed_env,
    )


def build_online_monitor_spec(
    *,
    project_id: str,
    location: str,
    reasoning_engine_name: str,
    sampling_rate: float = 0.20,
    max_samples_per_run: int = 25,
    trace_filter: str = "ALL_TRACES",
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    """Build a verified Online Evaluation Monitor specification and ops runbook."""
    if not (0.0 < sampling_rate <= 1.0):
        raise ValueError(f"sampling_rate must be in (0.0, 1.0], got {sampling_rate}")
    if max_samples_per_run <= 0:
        raise ValueError(f"max_samples_per_run must be positive, got {max_samples_per_run}")

    selected_metrics = metrics or list(DEFAULT_ONLINE_METRICS)
    engine_id = reasoning_engine_name.rstrip("/").split("/")[-1] if reasoning_engine_name else "<REASONING_ENGINE_ID>"
    proj = project_id or "<YOUR_PROJECT_ID>"

    return {
        "monitor_display_name": "coding-agent-online-quality-monitor",
        "provisioning_channel": "Google Cloud Console (Agent Platform > Agents > Evaluation > Online monitors)",
        "console_url": f"https://console.cloud.google.com/agent-platform/agent-evaluation?project={proj}",
        "target_agent_engine": reasoning_engine_name or f"projects/{proj}/locations/{location}/reasoningEngines/{engine_id}",
        "schedule_cadence": "Approximately every 10 minutes (Query -> Evaluate -> Report)",
        "sampling_config": {
            "sampling_percentage": round(sampling_rate * 100, 2),
            "max_samples_per_run": max_samples_per_run,
            "trace_filter": trace_filter,
        },
        "metrics": selected_metrics,
        "required_otel_signals": REQUIRED_OTEL_SIGNALS,
        "exported_cloud_monitoring_metrics": {
            "monitored_resource": "aiplatform.googleapis.com/OnlineEvaluator",
            "descriptors": [
                {
                    "metric_type": "aiplatform.googleapis.com/online_evaluator/scores",
                    "kind": "DELTA",
                    "value_type": "DISTRIBUTION",
                    "labels": ["agent_resource_name", "evaluation_metric_name", "runtime_revision_id"],
                },
                {
                    "metric_type": "aiplatform.googleapis.com/online_evaluator/evaluations_count",
                    "kind": "DELTA",
                    "value_type": "INT64",
                    "labels": [
                        "agent_resource_name",
                        "evaluation_metric_name",
                        "evaluation_status",
                        "runtime_revision_id",
                    ],
                },
            ],
        },
        "operational_warnings": [
            (
                "First-Monitor Transient Failed Status: The first Online Monitor in a project "
                "often shows Failed ('permission denied') while P4SA IAM propagates. Do NOT "
                "delete it; it retries automatically every ~10 minutes and becomes Active. "
                "Troubleshoot IAM only if still Failed after 30 minutes."
            ),
            (
                "P4SA Privilege Boundary: Online Evaluators execute under the project-level "
                "service account (P4SA), so any user permitted to create an OnlineEvaluator "
                "can attach it to any agent in the same project. Restrict creation to admins."
            ),
        ],
        "logs_explorer_diagnostic_queries": {
            "by_monitor_id": (
                f'resource.labels.online_evaluator="projects/{proj}/locations/{location}'
                '/onlineEvaluators/YOUR_MONITOR_ID"'
            ),
            "by_agent_id": f'labels.reasoning_engine_id="{engine_id}"',
            "by_trace_id": 'labels.trace="YOUR_TRACE_ID"',
            "inference_events": 'labels."event.name"="gen_ai.client.inference.operation.details"',
        },
    }


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
    parser.add_argument("--location", help="Eval region (defaults to EVAL_LOCATION or GOOGLE_CLOUD_LOCATION).")
    parser.add_argument(
        "--agent-resource-name",
        help="Full ReasoningEngine resource name (defaults to REASONING_ENGINE_NAME).",
    )
    parser.add_argument(
        "--sampling-rate",
        type=float,
        default=float(os.environ.get("ONLINE_MONITOR_SAMPLING_RATE", "0.2")),
        help="Fraction of live traces to evaluate (0.0 < rate <= 1.0; default 0.2 = 20%%).",
    )
    parser.add_argument(
        "--max-samples-per-run",
        type=int,
        default=int(os.environ.get("ONLINE_MONITOR_MAX_SAMPLES_PER_RUN", "25")),
        help="Hard per-10-minute-cycle sample cap to bound evaluation spend.",
    )
    parser.add_argument(
        "--trace-filter",
        default="ALL_TRACES",
        help="Trace selection criteria (e.g., 'ALL_TRACES' or 'Duration > 2').",
    )
    parser.add_argument(
        "--metrics",
        default=",".join(DEFAULT_ONLINE_METRICS),
        help="Comma-separated evaluation metrics to attach to the Online Monitor.",
    )
    parser.add_argument(
        "--verify-runtime",
        action="store_true",
        help="Call Agent Platform API to verify the deployed ReasoningEngine resource.",
    )
    parser.add_argument(
        "--strict-env",
        action="store_true",
        help="Exit non-zero if local shell env lacks the mandatory OTel env vars.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_arg_parser().parse_args(argv)
    settings = get_settings()

    project_id = args.project or settings.google_cloud_project
    location = args.location or os.environ.get("EVAL_LOCATION") or settings.google_cloud_location
    runtime_name = args.agent_resource_name or settings.reasoning_engine_name
    metrics = [m.strip() for m in args.metrics.split(",") if m.strip()]

    otel_check = validate_otel_prerequisites()
    monitor_spec = build_online_monitor_spec(
        project_id=project_id,
        location=location,
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
        output["runtime_verification"] = verify_deployed_runtime(project_id, location, runtime_name)

    print(json.dumps(output, indent=2))
    if args.strict_env and not otel_check.passed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
