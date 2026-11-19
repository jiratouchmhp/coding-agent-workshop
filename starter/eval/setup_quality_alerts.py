"""Cloud Monitoring Quality Alerts for Online Evaluation Metrics (Lab 6 — Starter).

Complete the ``# TODO(lab-6)`` blocks following ``workshop/06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md``:
1. Construct a Cloud Monitoring ``AlertPolicy`` dictionary targeting
   ``aiplatform.googleapis.com/online_evaluator/scores`` with
   ``COMPARISON_LT``, ``ALIGN_MEAN``, and ``ConditionCombinerType.OR``.
2. Create the alerting policy via ``google.cloud.monitoring_v3.AlertPolicyServiceClient``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

TRACK_ROOT = Path(__file__).resolve().parents[1]
if str(TRACK_ROOT) not in sys.path:
    sys.path.insert(0, str(TRACK_ROOT))

from coding_agent.config import get_settings  # noqa: E402

logger = logging.getLogger(__name__)

ONLINE_EVAL_SCORES_METRIC = "aiplatform.googleapis.com/online_evaluator/scores"


def build_metric_filter(
    *,
    metric_name: str = "task_success",
    agent_resource_name: str | None = None,
    runtime_revision_id: str | None = None,
) -> str:
    """Build a Cloud Monitoring filter expression for ``online_evaluator/scores``."""
    clauses = [f'metric.type="{ONLINE_EVAL_SCORES_METRIC}"']
    if metric_name:
        clauses.append(f'metric.labels.evaluation_metric_name="{metric_name}"')
    if agent_resource_name:
        clauses.append(f'metric.labels.agent_resource_name="{agent_resource_name}"')
    if runtime_revision_id:
        clauses.append(f'metric.labels.runtime_revision_id="{runtime_revision_id}"')
    return " AND ".join(clauses)


def build_alert_policy_dict(
    *,
    display_name: str,
    metric_name: str = "task_success",
    threshold: float = 0.80,
    duration_seconds: int = 1800,
    alignment_period_seconds: int = 60,
    agent_resource_name: str | None = None,
    runtime_revision_id: str | None = None,
    notification_channels: list[str] | None = None,
) -> dict[str, Any]:
    """Construct a ``google.cloud.monitoring_v3`` alert policy dict."""
    # TODO(lab-6): Build the AlertPolicy dictionary using `monitoring_v3.ComparisonType.COMPARISON_LT`,
    # `monitoring_v3.Aggregation.Aligner.ALIGN_MEAN`, and
    # `monitoring_v3.AlertPolicy.ConditionCombinerType.OR` (with string fallbacks if
    # `google.cloud.monitoring_v3` is not imported during dry-run).
    # Use `build_metric_filter(...)`, `threshold_value=threshold`,
    # `duration={"seconds": duration_seconds}`, `alignment_period={"seconds": alignment_period_seconds}`,
    # and include `notification_channels` only if non-empty.
    raise NotImplementedError(
        f"TODO(lab-6): Build monitoring_v3 AlertPolicy dict for display_name={display_name!r}, "
        f"metric={metric_name!r}, threshold={threshold}, duration={duration_seconds}s, "
        f"alignment={alignment_period_seconds}s, agent={agent_resource_name!r}, "
        f"revision={runtime_revision_id!r}, channels={notification_channels!r}."
    )


def render_gcloud_policy_yaml(
    *,
    display_name: str,
    metric_name: str = "task_success",
    threshold: float = 0.80,
    duration_seconds: int = 1800,
    alignment_period_seconds: int = 60,
    agent_resource_name: str | None = None,
    runtime_revision_id: str | None = None,
    notification_channels: list[str] | None = None,
) -> str:
    """Render the equivalent ``gcloud monitoring policies create`` YAML file."""
    metric_filter = build_metric_filter(
        metric_name=metric_name,
        agent_resource_name=agent_resource_name,
        runtime_revision_id=runtime_revision_id,
    )
    lines = [
        f'displayName: "{display_name}"',
        "conditions:",
        f'- displayName: "Online {metric_name} < {threshold:.2f}"',
        "  conditionThreshold:",
        "    filter: >",
        f"      {metric_filter}",
        "    comparison: COMPARISON_LT",
        f"    thresholdValue: {threshold}",
        f"    duration: {duration_seconds}s",
        "    aggregations:",
        f"    - alignmentPeriod: {alignment_period_seconds}s",
        "      perSeriesAligner: ALIGN_MEAN",
        "combiner: OR",
        "enabled: true",
    ]
    if notification_channels:
        lines.append("notificationChannels:")
        for channel in notification_channels:
            lines.append(f'- "{channel}"')
    else:
        lines.append(
            "# notificationChannels omitted so incidents record quietly in Monitoring > Alerting."
        )
    return "\n".join(lines) + "\n"


def create_alert_policy(project_id: str, policy: dict[str, Any]) -> str:
    """Create the alerting policy in Cloud Monitoring via ``monitoring_v3``."""
    # TODO(lab-6): Instantiate `client = monitoring_v3.AlertPolicyServiceClient()`
    # and call `client.create_alert_policy(name=f"projects/{project_id}", alert_policy=policy)`.
    # Return `str(response.name)`.
    raise NotImplementedError(
        f"TODO(lab-6): Create Cloud Monitoring alert policy in projects/{project_id} "
        f"with keys={sorted(policy.keys())}."
    )


def _parse_notification_channels(cli_channels: list[str] | None) -> list[str]:
    channels: list[str] = []
    if cli_channels:
        channels.extend(c.strip() for c in cli_channels if c.strip())
    env_raw = os.environ.get("ALERT_NOTIFICATION_CHANNELS", "").strip()
    if env_raw and not channels:
        channels.extend(c.strip() for c in env_raw.split(",") if c.strip())
    return channels


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create Cloud Monitoring Quality Alerts on Online Evaluator scores.",
    )
    parser.add_argument("--project", help="GCP project ID (defaults to GOOGLE_CLOUD_PROJECT).")
    parser.add_argument("--display-name", default=None)
    parser.add_argument("--metric-name", default="task_success")
    parser.add_argument("--threshold", type=float, default=0.80)
    parser.add_argument("--duration-seconds", type=int, default=1800)
    parser.add_argument("--alignment-period-seconds", type=int, default=60)
    parser.add_argument("--agent-resource-name", default=None)
    parser.add_argument("--runtime-revision-id", default=None)
    parser.add_argument("--notification-channel", action="append", default=None)
    parser.add_argument("--write-yaml", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_arg_parser().parse_args(argv)
    settings = get_settings()

    project_id = args.project or settings.google_cloud_project
    agent_resource_name = args.agent_resource_name or settings.reasoning_engine_name or None
    channels = _parse_notification_channels(args.notification_channel)
    display_name = (
        args.display_name
        or f"Coding Agent Quality Drift — {args.metric_name.replace('_', ' ').title()}"
    )

    yaml_text = render_gcloud_policy_yaml(
        display_name=display_name,
        metric_name=args.metric_name,
        threshold=args.threshold,
        duration_seconds=args.duration_seconds,
        alignment_period_seconds=args.alignment_period_seconds,
        agent_resource_name=agent_resource_name,
        runtime_revision_id=args.runtime_revision_id,
        notification_channels=channels,
    )
    yaml_target = args.write_yaml or Path("policy.yaml")
    if args.write_yaml is not None:
        args.write_yaml.parent.mkdir(parents=True, exist_ok=True)
        args.write_yaml.write_text(yaml_text, encoding="utf-8")

    gcloud_cmd = (
        f'gcloud monitoring policies create --policy-from-file="{yaml_target}" '
        f'--project="{project_id or "YOUR_PROJECT_ID"}"'
    )
    print("=== Equivalent gcloud policy.yaml ===")
    print(yaml_text.rstrip())
    print("\n=== Equivalent gcloud command ===")
    print(gcloud_cmd)

    policy = build_alert_policy_dict(
        display_name=display_name,
        metric_name=args.metric_name,
        threshold=args.threshold,
        duration_seconds=args.duration_seconds,
        alignment_period_seconds=args.alignment_period_seconds,
        agent_resource_name=agent_resource_name,
        runtime_revision_id=args.runtime_revision_id,
        notification_channels=channels,
    )

    if args.dry_run:
        print("\n=== Python monitoring_v3 payload (dry-run) ===")
        print(json.dumps(policy, indent=2, default=str))
        return 0

    if not project_id:
        settings.require_gcp_project()

    policy_name = create_alert_policy(project_id=project_id, policy=policy)
    print(f"\nCreated Cloud Monitoring alerting policy: {policy_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
