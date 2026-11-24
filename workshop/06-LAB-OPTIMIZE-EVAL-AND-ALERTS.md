# Lab 6: Evaluation, Observability, Quality Alerts & Prompt Optimization

Your coding agent is live on Agent Runtime and emitting OpenTelemetry traces. In this lab you'll grade it with split offline datasets and simulated users, validate telemetry for Online Evaluation Monitors, build Cloud Monitoring quality alerts, and close the loop with automated prompt and skill updates.

**Duration:** 40 min (Full-Day) | 15 min (Fast-Track Instructor Demo) | **Previous:** [Lab 5: Deploy on Agent Runtime](./05-LAB-DEPLOY-RUNTIME-TERRAFORM.md) | **Next:** [Lab 7 (Optional): Security & Governance](./07-LAB-OPTIONAL-SECURITY-AND-GOVERNANCE.md) or [Lab 8: Agent Runtime vs. GKE](./08-ARCHITECTURE-AGENT-RUNTIME-VS-GKE.md)

## Files You Will Edit

| Step | File | Where to edit | What you're adding |
|---|---|---|---|
| Step 1 | [starter/eval/run_offline_eval.py](../starter/eval/run_offline_eval.py) | `evaluate_split_datasets()`, `run_loss_clustering()` (`# TODO(lab-6)`) | Separate single-turn and multi-turn `evaluate()` passes plus `global` failure clustering |
| Step 2 | [starter/eval/run_simulated_eval.py](../starter/eval/run_simulated_eval.py) | `generate_scenarios()`, `run_user_simulation()` (`# TODO(lab-6)`) | 2-step persona synthesis and multi-turn user simulation |
| Step 3 | [starter/eval/setup_online_monitor.py](../starter/eval/setup_online_monitor.py) | `validate_otel_prerequisites()` (`# TODO(lab-6)`) | OTel GenAI v1.37+ env var and `EVAL_LOCATION` validator |
| Step 4 | [starter/eval/setup_quality_alerts.py](../starter/eval/setup_quality_alerts.py) | `build_alert_policy_dict()` (`# TODO(lab-6)`) | Cloud Monitoring `online_evaluator/scores` alert policy dict |
| Step 5 | [starter/eval/optimize_prompt.py](../starter/eval/optimize_prompt.py) | `run_prompt_optimization()`, `publish_updated_skill()` (`# TODO(lab-6)`) | Non-mutating ADK prompt/skill optimization and zero-redeploy Skill Registry hot-update |

**Already built for you (no edits needed):** [starter/eval/eval_config.yaml](../starter/eval/eval_config.yaml), [starter/eval/sampler_config.json](../starter/eval/sampler_config.json), [starter/coding_agent/train_eval_set.evalset.json](../starter/coding_agent/train_eval_set.evalset.json), datasets in [starter/eval/datasets/](../starter/eval/datasets/) (`coding_agent_single_turn.json`, `coding_agent_multi_turn.json`, `coding_agent_eval.jsonl`), plus `expand_agent_toolsets()`, `build_eval_client()`, `register_custom_coding_metrics()`, `grade_simulated_traces()`, `cluster_simulation_failures()`, `build_online_monitor_spec()`, `verify_deployed_runtime()`, `create_alert_policy()`, `fetch_negative_feedback()`, and `build_adk_sampler_and_optimizer()`.

**Need a hand or fell behind?** Ask Antigravity to use [`.agents/skills/agent-platform-optimize-and-eval`](../.agents/skills/agent-platform-optimize-and-eval/SKILL.md), or run `make fast-forward LAB=6` to sync Lab 6 from `solution/` without touching Lab 8.

---

## Step 1: Run Split Offline Evaluation and Loss Clustering

**File:** [starter/eval/run_offline_eval.py](../starter/eval/run_offline_eval.py) (`evaluate_split_datasets()`, `run_loss_clustering()`, `# TODO(lab-6)`)

The Vertex AI Evaluation Service applies every metric in a call to every case, so mixing single-turn metrics with multi-turn traces fails with HTTP 400. We use `EVAL_LOCATION=global` because the Evaluation Service does not run in `asia-southeast1`/`asia-southeast3` and `generate_loss_clusters` only exists in `global`. You'll grade the 5 single-turn cases and 3 multi-turn traces separately, then wire global failure clustering.

- **`evaluate_split_datasets()`:** Resolve `types = get_eval_types()` and pin `safety_v1 = types.RubricMetric.SAFETY(version="v1")` (in `v1`, `1.0` means safe; `safety_v3` flips polarity to `1.0` = violated).
- **Single-turn pass:** When `run_inference=True`, strip pre-recorded `"responses"`, wrap cases in `types.EvaluationDataset` (never a raw dict), flatten ADK toolsets via `expand_agent_toolsets(root_agent)`, run `client.evals.run_inference(...)`, and grade with `FINAL_RESPONSE_QUALITY`, `TOOL_USE_QUALITY`, `HALLUCINATION`, and `safety_v1`. For static cases (`has_agent_trace_fields(...)` is `False`), grade with `GENERAL_QUALITY`, `FINAL_RESPONSE_MATCH`, and `safety_v1`. Always pass `dataset=` (not `traces=`) to `client.evals.evaluate(...)`.
- **Multi-turn pass:** Grade `{"eval_cases": multi_turn_cases}` strictly with `MULTI_TURN_TASK_SUCCESS`, `MULTI_TURN_TOOL_USE_QUALITY`, and `MULTI_TURN_TRAJECTORY_QUALITY`.
- **`run_loss_clustering()`:** Create a `global` client via `build_eval_client(project_id=project_id, location="global")` and pass `metric=` explicitly (required whenever `eval_result` contains multiple metrics).

<details>
<summary>Stuck? Peek at the code</summary>

```python
def evaluate_split_datasets(
    client: Any, single_turn_cases: list[dict[str, Any]], multi_turn_cases: list[dict[str, Any]], *, run_inference: bool = False,
) -> dict[str, Any]:
    types = get_eval_types()
    results: dict[str, Any] = {"single_turn": None, "multi_turn": None}
    if single_turn_cases:
        safety_v1 = types.RubricMetric.SAFETY(version="v1")
        agent_metrics = [
            types.RubricMetric.FINAL_RESPONSE_QUALITY, types.RubricMetric.TOOL_USE_QUALITY,
            types.RubricMetric.HALLUCINATION, safety_v1,
        ]
        if run_inference:
            from coding_agent.agent import root_agent
            inf_cases = [{k: v for k, v in c.items() if k != "responses"} for c in single_turn_cases]
            inf_src = (
                types.EvaluationDataset.model_validate({"eval_cases": inf_cases})
                if hasattr(types.EvaluationDataset, "model_validate")
                else types.EvaluationDataset(eval_cases=inf_cases)
            )
            single_ds: Any = client.evals.run_inference(agent=expand_agent_toolsets(root_agent), src=inf_src)
            single_metrics = agent_metrics
        elif has_agent_trace_fields(single_turn_cases):
            single_ds, single_metrics = {"eval_cases": single_turn_cases}, agent_metrics
        else:
            single_ds = {"eval_cases": single_turn_cases}
            single_metrics = [types.RubricMetric.GENERAL_QUALITY, types.RubricMetric.FINAL_RESPONSE_MATCH, safety_v1]
        results["single_turn"] = client.evals.evaluate(dataset=single_ds, metrics=single_metrics)

    if multi_turn_cases:
        results["multi_turn"] = client.evals.evaluate(
            dataset={"eval_cases": multi_turn_cases},
            metrics=[
                types.RubricMetric.MULTI_TURN_TASK_SUCCESS,
                types.RubricMetric.MULTI_TURN_TOOL_USE_QUALITY,
                types.RubricMetric.MULTI_TURN_TRAJECTORY_QUALITY,
            ],
        )
    return results

def run_loss_clustering(project_id: str, eval_result: Any, metric_name: str = "multi_turn_task_success") -> Any:
    types = get_eval_types()
    metric_map = {
        "multi_turn_task_success": types.RubricMetric.MULTI_TURN_TASK_SUCCESS,
        "multi_turn_tool_use_quality": types.RubricMetric.MULTI_TURN_TOOL_USE_QUALITY,
    }
    if metric_name not in metric_map:
        raise ValueError(f"Unsupported clustering metric {metric_name!r}; choose from {sorted(metric_map)}.")
    global_client = build_eval_client(project_id=project_id, location="global")
    return global_client.evals.generate_loss_clusters(eval_result=eval_result, metric=metric_map[metric_name])
```

Full reference file: [`solution/eval/run_offline_eval.py`](../solution/eval/run_offline_eval.py).

</details>

**Check it works:**

```bash
(cd starter && uv run python eval/run_offline_eval.py --dry-run)
make eval-offline
```

Expected output: `--dry-run` prints 5 `single_turn_case_ids` and 3 `multi_turn_case_ids` cleanly separated; `make eval-offline` returns `single_turn_summary` and `multi_turn_summary`. For CI gating with `agents-cli` (inside `starter/`), grade pre-recorded multi-turn traces directly via `eval grade --traces`:

```bash
cd starter
agents-cli eval run --dataset eval/datasets/coding_agent_single_turn.json \
  --metrics final_response_quality,tool_use_quality,hallucination,safety \
  --fail-under final_response_quality=0.8 --output artifacts/grade_results_single_turn/
agents-cli eval grade --traces eval/datasets/coding_agent_multi_turn.json \
  --metrics multi_turn_task_success,multi_turn_tool_use_quality,multi_turn_trajectory_quality \
  --fail-under multi_turn_task_success=0.8 --output artifacts/grade_results_multi_turn/
```

---

## Step 2: Run 2-Step Simulated User Evaluation

**File:** [starter/eval/run_simulated_eval.py](../starter/eval/run_simulated_eval.py) (`generate_scenarios()`, `run_user_simulation()`, `# TODO(lab-6)`)

Static tests miss bugs that show up when a developer pastes a traceback on turn 2 or embeds prompt injection in a PR comment. Here you'll synthesize personas from your agent's instructions and tools, then let the User Simulator LLM run multi-turn sessions capped at `max_turn`. Downstream grading (`grade_simulated_traces()`) and clustering (`cluster_simulation_failures()`) are pre-filled.

- **Toolset quirk:** `types.evals.AgentInfo.load_from_agent()` crashes with `TypeError` on raw ADK `BaseToolset` objects (`EnvironmentToolset`, `SkillToolset`). Call the pre-filled `expand_agent_toolsets(agent)` before passing the agent to `load_from_agent()` and `run_inference()`.
- **`generate_scenarios()`:** Load `agent_info = types.evals.AgentInfo.load_from_agent(agent=prepared_agent)` and call `client.evals.generate_conversation_scenarios(...)`.
- **`run_user_simulation()`:** Call `client.evals.run_inference(agent=prepared_agent, src=scenario_dataset, config={"user_simulator_config": {"max_turn": max_turns}})`.

<details>
<summary>Stuck? Peek at the code</summary>

```python
def generate_scenarios(
    client: Any, agent: Any, *, count: int = 5,
    generation_instruction: str = DEFAULT_GENERATION_INSTRUCTION,
    environment_context: str = DEFAULT_ENVIRONMENT_CONTEXT,
) -> Any:
    types = get_eval_types()
    agent_info = types.evals.AgentInfo.load_from_agent(agent=expand_agent_toolsets(agent))
    return client.evals.generate_conversation_scenarios(
        agent_info=agent_info,
        config={"count": count, "generation_instruction": generation_instruction, "environment_context": environment_context},
    )

def run_user_simulation(client: Any, agent: Any, scenario_dataset: Any, *, max_turns: int = 5) -> Any:
    return client.evals.run_inference(
        agent=expand_agent_toolsets(agent),
        src=scenario_dataset,
        config={"user_simulator_config": {"max_turn": max_turns}},
    )
```

Full reference file: [`solution/eval/run_simulated_eval.py`](../solution/eval/run_simulated_eval.py).

</details>

**Check it works:**

```bash
(cd starter && uv run python eval/run_simulated_eval.py --dry-run)
make eval-simulated
```

Expected output: `--dry-run` prints `count: 5` and `max_turn: 5` in `global`; `make eval-simulated` prints multi-turn `summary_metrics` and `loss_clusters`.

---

## Step 3: Validate Telemetry and Set Up an Online Monitor

**File:** [starter/eval/setup_online_monitor.py](../starter/eval/setup_online_monitor.py) (`validate_otel_prerequisites()`, `# TODO(lab-6)`)

Online Evaluation Monitors sample live production traces every ~10 minutes. Because `OnlineEvaluator` monitors are created in the Cloud Console (no Python creation SDK is published yet), this script checks your deployed Lab 5 runtime's OTel env vars in `asia-southeast1` while validating your eval config in `global`, then outputs the monitor spec and Logs Explorer queries.

- Check `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY == "true"` and `OTEL_SEMCONV_STABILITY_OPT_IN == "gen_ai_latest_experimental"`.
- Validate `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` against `VALID_PYTHON_CAPTURE_ENUMS` (`NO_CONTENT`, `EVENT_ONLY`, `SPAN_ONLY`, `SPAN_AND_EVENT`), explicitly rejecting booleans (`"true"`, `"false"`, `"1"`, `"0"`). Warn if `NO_CONTENT` is set without `OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK == "upload"` and a `gs://` upload base path.
- Default `EVAL_LOCATION` to `"global"` when unset (never `GOOGLE_CLOUD_LOCATION`), confirm it is in `SUPPORTED_EVAL_LOCATIONS`, and return `TelemetryCheckResult(passed=not errors, errors=errors, warnings=warnings, observed_env=observed_env)`.

> [!WARNING]
> **Two Online Monitor gotchas:** In ADK Python, passing `"true"` to `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` silently falls back to `NO_CONTENT` and leaves monitors with nothing to grade; always use `EVENT_ONLY` (or `NO_CONTENT` with GCS offload). Also, the first Online Monitor created in a GCP project often transitions to `Failed` (`permission denied`) while P4SA IAM propagates. Do not delete it: it retries every ~10 minutes and turns `Active`.

<details>
<summary>Stuck? Peek at the code</summary>

```python
def validate_otel_prerequisites(env: dict[str, str] | None = None) -> TelemetryCheckResult:
    source = env if env is not None else dict(os.environ)
    errors: list[str] = []
    warnings: list[str] = []
    enable_telemetry = source.get("GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY", "").strip()
    semconv_opt_in = source.get("OTEL_SEMCONV_STABILITY_OPT_IN", "").strip()
    capture_mode = source.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "").strip()
    upload_hook = source.get("OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK", "").strip()
    upload_base = source.get("OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH", "").strip()
    eval_location = (source.get("EVAL_LOCATION") or "").strip() or "global"

    if enable_telemetry.lower() != "true":
        errors.append(f"GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY must be 'true' (got {enable_telemetry!r}).")
    if semconv_opt_in != "gen_ai_latest_experimental":
        errors.append(f"OTEL_SEMCONV_STABILITY_OPT_IN must be 'gen_ai_latest_experimental' (got {semconv_opt_in!r}).")
    if capture_mode.lower() in {"true", "false", "1", "0"}:
        errors.append(f"ADK Python rejects boolean {capture_mode!r}; use EVENT_ONLY, SPAN_ONLY, SPAN_AND_EVENT, or NO_CONTENT.")
    elif capture_mode not in VALID_PYTHON_CAPTURE_ENUMS:
        errors.append(f"OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT must be one of {sorted(VALID_PYTHON_CAPTURE_ENUMS)}.")
    elif capture_mode == "NO_CONTENT" and not (upload_hook == "upload" and upload_base.startswith("gs://")):
        warnings.append("NO_CONTENT without GCS upload leaves Online Monitors without content; use EVENT_ONLY.")
    if eval_location not in SUPPORTED_EVAL_LOCATIONS:
        errors.append(f"Unsupported evaluation location {eval_location!r}.")
    if upload_hook == "upload" and not upload_base.startswith("gs://"):
        errors.append("OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK='upload' requires a gs:// upload base path.")

    observed = {
        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": enable_telemetry,
        "OTEL_SEMCONV_STABILITY_OPT_IN": semconv_opt_in,
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": capture_mode,
        "OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK": upload_hook,
        "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH": upload_base,
        "EVAL_LOCATION": eval_location,
    }
    return TelemetryCheckResult(passed=not errors, errors=errors, warnings=warnings, observed_env=observed)
```

Full reference file: [`solution/eval/setup_online_monitor.py`](../solution/eval/setup_online_monitor.py).

</details>

**Check it works:**

```bash
source .env
(cd starter && uv run python eval/setup_online_monitor.py --verify-runtime --strict-env)
```

Expected output: JSON with `"otel_env_source": "deployed_runtime_deployment_spec"`, `"passed": true`, `"runtime_location": "asia-southeast1"`, and `"eval_location": "global"` (drop `--verify-runtime` if you haven't deployed Lab 5 yet). Next, open **Agent Platform -> Agents -> Evaluation -> Online monitors -> New monitor**, pick your Lab 5 runtime, select **Task Success**, **Tool Use Quality**, **Hallucination**, and **Safety**, set sampling (`100%` for workshop, `20%` for prod) and max samples (`25`), and click **Create**.

---

## Step 4: Build a Cloud Monitoring Quality Alert Policy

**File:** [starter/eval/setup_quality_alerts.py](../starter/eval/setup_quality_alerts.py) (`build_alert_policy_dict()`, `# TODO(lab-6)`)

Online Monitors export scores to Cloud Monitoring under `aiplatform.googleapis.com/online_evaluator/scores`. You'll build the `monitoring_v3` alert policy dict so Cloud Monitoring opens an incident if median (`p50`) `task_success` stays below `0.80` for 30 minutes (`1800s`). Policy submission (`create_alert_policy()`) and `gcloud` YAML rendering are pre-filled.

- Validate `comparison` against `VALID_COMPARISON_TYPES` (`COMPARISON_LT` for standard scores; `COMPARISON_GT` for inverted-polarity metrics like `safety_v3`).
- Build the filter with `build_metric_filter(...)` (includes the mandatory `resource.type="aiplatform.googleapis.com/OnlineEvaluator"` clause).
- Set `per_series_aligner` to **`ALIGN_PERCENTILE_50`** (not `ALIGN_MEAN`: `online_evaluator/scores` is `DELTA` / `DISTRIBUTION`, and Cloud Monitoring rejects `ALIGN_MEAN` with HTTP 400). Fall back to enum string names when `monitoring_v3` is absent during offline dry runs.

<details>
<summary>Stuck? Peek at the code</summary>

```python
def build_alert_policy_dict(
    *, display_name: str, metric_name: str = "task_success", threshold: float = 0.80,
    comparison: str = "COMPARISON_LT", duration_seconds: int = 1800, alignment_period_seconds: int = 60,
    agent_resource_name: str | None = None, runtime_revision_id: str | None = None,
    notification_channels: list[str] | None = None,
) -> dict[str, Any]:
    normalized = comparison.strip().upper()
    if normalized not in VALID_COMPARISON_TYPES:
        raise ValueError(f"Unsupported comparison {comparison!r}; expected {sorted(VALID_COMPARISON_TYPES)}.")
    try:
        from google.cloud import monitoring_v3
        cmp_val: Any = getattr(monitoring_v3.ComparisonType, normalized)
        aligner: Any = monitoring_v3.Aggregation.Aligner.ALIGN_PERCENTILE_50
        combiner: Any = monitoring_v3.AlertPolicy.ConditionCombinerType.OR
    except ImportError:
        cmp_val, aligner, combiner = normalized, "ALIGN_PERCENTILE_50", "OR"

    policy: dict[str, Any] = {
        "display_name": display_name,
        "conditions": [{
            "display_name": f"Online {metric_name} {VALID_COMPARISON_TYPES[normalized]} {threshold:.2f}",
            "condition_threshold": {
                "filter": build_metric_filter(
                    metric_name=metric_name,
                    agent_resource_name=agent_resource_name,
                    runtime_revision_id=runtime_revision_id,
                ),
                "comparison": cmp_val,
                "threshold_value": threshold,
                "duration": {"seconds": duration_seconds},
                "aggregations": [{"alignment_period": {"seconds": alignment_period_seconds}, "per_series_aligner": aligner}],
            },
        }],
        "combiner": combiner,
        "enabled": True,
    }
    if notification_channels:
        policy["notification_channels"] = notification_channels
    return policy
```

Full reference file: [`solution/eval/setup_quality_alerts.py`](../solution/eval/setup_quality_alerts.py).

</details>

**Check it works:**

```bash
(cd starter && uv run python eval/setup_quality_alerts.py --dry-run)
# Optional: create the live alert policy in Cloud Monitoring
(cd starter && uv run python eval/setup_quality_alerts.py)
```

Expected output: `--dry-run` prints `perSeriesAligner: ALIGN_PERCENTILE_50`, the equivalent `gcloud monitoring policies create` command, and the `monitoring_v3` JSON payload.

---

## Step 5: Optimize Prompts and Hot-Update Skills Without Redeploying

**File:** [starter/eval/optimize_prompt.py](../starter/eval/optimize_prompt.py) (`run_prompt_optimization()`, `publish_updated_skill()`, `# TODO(lab-6)`)

When failure clusters or `THUMBS_DOWN` feedback reveal a recurring miss, root-prompt edits require rebuilding and canary-rolling out a new revision, while domain-skill edits update `SKILL.md` in Skill Registry or Agent Registry with zero container rebuild. You'll complete both functions here.

- **`run_prompt_optimization()`:** Import `root_agent` from `coding_agent.agent`, verify `.instruction` with `_extract_root_instruction(...)`, and attach local `skill_dir` via `_attach_local_skill_for_gepa(root_agent, skill_dir)` when `optimizer_choice == "gepa-skills"` (`GEPARootAgentOptimizer` inspects local `SkillToolset.skills`, not lazy remote registry handles). Call `build_adk_sampler_and_optimizer(...)`, `await optimizer.optimize(target_agent, sampler)`, pick `best_idx`, extract frontmatter-preserved skills via `_extract_optimized_skills(...)`, compute `difflib.unified_diff(...)`, and return the candidate dict.
- **`publish_updated_skill()`:** Validate all 16 Skill Registry rules by invoking `scripts/package_registry_skill.py` (`--dry-run` or `--output dist/<skill_id>.zip`), and when not `dry_run`, call `agentplatform.Client(project=project_id, location=skill_location).skills.update(...)` passing **`local_path: str(resolved_skill_dir)`**.

> [!IMPORTANT]
> **Two skill update traps:** (1) Vertex AI Skill Registry (`client.skills.update` in `us-central1`) zips `local_path` internally and raises `ValueError: Path is not a directory` if given a `.zip`. (2) Agent Registry standalone skills (`gcloud alpha agent-registry skills` in `global`) require **`--target-state=active`** when promoting `--default-revision` to `rev-2`, or `GCPSkillRegistry.get_skill()` fails with HTTP 400 on `STATE_DRAFT`; under `ENABLED_BLOCKING`, wait for `revisions describe rev-2` to show `SUCCEEDED` first.

<details>
<summary>Stuck? Peek at the code</summary>

```python
async def run_prompt_optimization(
    *, sampler_config_path: Path, agents_dir: Path, optimizer_choice: OptimizerChoice = "simple",
    iterations: int = 2, batch_size: int = 4, optimizer_model: str = "gemini-4-hydrogen", skill_dir: Path | None = None,
) -> dict[str, Any]:
    from coding_agent.agent import root_agent
    orig_inst = _extract_root_instruction(root_agent, agent_architecture=get_settings().agent_architecture)
    target = _attach_local_skill_for_gepa(root_agent, skill_dir) if optimizer_choice == "gepa-skills" else root_agent
    sampler, optimizer = build_adk_sampler_and_optimizer(
        sampler_config_path=sampler_config_path, agents_dir=agents_dir, optimizer_choice=optimizer_choice,
        iterations=iterations, batch_size=batch_size, optimizer_model=optimizer_model,
    )
    result = await optimizer.optimize(target, sampler)
    best_idx, gepa_cand = 0, None
    gepa_res = getattr(result, "gepa_result", None)
    if isinstance(gepa_res, dict) and "best_idx" in gepa_res:
        best_idx = int(gepa_res["best_idx"])
        cands = gepa_res.get("candidates")
        if isinstance(cands, list) and 0 <= best_idx < len(cands) and isinstance(cands[best_idx], dict):
            gepa_cand = cands[best_idx]
    elif getattr(result, "optimized_agents", None):
        scores = [float(getattr(x, "overall_score", 0.0) or 0.0) for x in result.optimized_agents]
        best_idx = max(range(len(scores)), key=lambda i: scores[i])
    best = result.optimized_agents[best_idx]
    opt_inst = str(getattr(best.optimized_agent, "instruction", ""))
    opt_skills = (
        _extract_optimized_skills(
            original_skill_dir=skill_dir,
            optimized_agent=best.optimized_agent,
            gepa_candidate=gepa_cand,
        )
        if optimizer_choice == "gepa-skills"
        else {}
    )
    diff = "".join(
        difflib.unified_diff(
            orig_inst.splitlines(keepends=True),
            opt_inst.splitlines(keepends=True),
            fromfile="before",
            tofile="candidate",
        )
    )
    return {
        "optimizer": optimizer_choice,
        "best_idx": best_idx,
        "overall_score": getattr(best, "overall_score", None),
        "original_instruction": orig_inst,
        "optimized_instruction": opt_inst,
        "unified_diff": diff,
        "optimized_skills": opt_skills,
    }

def publish_updated_skill(
    *, project_id: str, skill_location: str, skill_id: str, skill_dir: Path,
    display_name: str | None = None, description: str | None = None, zip_output_path: Path | None = None, dry_run: bool = False,
) -> dict[str, Any]:
    import subprocess
    resolved = skill_dir.resolve()
    if not resolved.is_dir() or not (resolved / "SKILL.md").is_file():
        raise ValueError(f"local_path must be a skill directory containing SKILL.md: {resolved}")
    d_name, d_desc = _read_skill_metadata(resolved)
    final_name, final_desc = display_name or d_name, description or d_desc
    res_name = f"projects/{project_id or 'PROJECT_ID'}/locations/{skill_location}/skills/{skill_id}"
    zip_path = zip_output_path or (REPO_ROOT / "dist" / f"{skill_id}.zip")
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "package_registry_skill.py"), str(resolved)]
    cmd += ["--dry-run"] if dry_run else ["--output", str(zip_path)]
    if not dry_run:
        zip_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"16-rule skill validation failed:\n{proc.stdout}\n{proc.stderr}")
    if dry_run:
        return {
            "dry_run": True,
            "validation_passed": True,
            "zero_agent_container_rebuild": True,
            "skill_resource_name": res_name,
            "local_path": str(resolved),
        }
    os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "TRUE"
    import agentplatform
    client = agentplatform.Client(project=project_id, location=skill_location)
    updated = client.skills.update(
        name=res_name,
        config={"display_name": final_name, "description": final_desc, "local_path": str(resolved)},
    )
    return {
        "dry_run": False,
        "validation_passed": True,
        "zero_agent_container_rebuild": True,
        "skill_resource_name": getattr(updated, "name", res_name),
        "local_path": str(resolved),
        "zip_path": str(zip_path),
    }
```

Full reference file: [`solution/eval/optimize_prompt.py`](../solution/eval/optimize_prompt.py).

</details>

**Check it works:**

```bash
# 1. Offline dry-runs (prompt optimizer + 16-rule skill validation)
(cd starter && uv run python eval/optimize_prompt.py --dry-run)
(cd starter && uv run python eval/optimize_prompt.py --optimizer gepa-skills --publish-skill --dry-run)

# 2. Live prompt optimization (prefix GOOGLE_CLOUD_LOCATION=global for Gemini 4 optimizer calls)
(cd starter && GOOGLE_CLOUD_LOCATION="${MODEL_LOCATION:-global}" uv run python eval/optimize_prompt.py --iterations 2 --batch-size 4)
```

To push an approved skill edit with zero container rebuild, run `--publish-skill` (Vertex AI Skill Registry in `us-central1`) or promote `rev-2` in Agent Registry (`global`):

```bash
# Option A: Vertex AI Skill Registry hot-update (us-central1)
(cd starter && uv run python eval/optimize_prompt.py --publish-skill --skill-dir skills_to_register/secure-code-review --skill-id secure-code-review)

# Option B: Agent Registry immutable rev-2 promotion (global)
python3 scripts/package_registry_skill.py starter/skills_to_register/secure-code-review --output dist/secure-code-review.zip
gcloud alpha agent-registry skills revisions create rev-2 --skill=private-secure-code-review \
  --project="${GOOGLE_CLOUD_PROJECT}" --location="${AGENT_REGISTRY_SKILLS_LOCATION:-global}" --payload="dist/secure-code-review.zip"
gcloud alpha agent-registry skills update private-secure-code-review \
  --project="${GOOGLE_CLOUD_PROJECT}" --location="${AGENT_REGISTRY_SKILLS_LOCATION:-global}" --target-state=active \
  --default-revision="projects/${GOOGLE_CLOUD_PROJECT}/locations/${AGENT_REGISTRY_SKILLS_LOCATION:-global}/skills/private-secure-code-review/revisions/rev-2"
```

Expected output: `--publish-skill --dry-run` prints `"validation_passed": true` and `"zero_agent_container_rebuild": true`; live optimization writes `starter/artifacts/optimized_instruction.txt`.

---

## Lab 6 Checkpoint

Run the automated Lab 6 verification from the repo root:

```bash
make verify-lab LAB=6
```

This checks all 5 scripts in `starter/eval/` for zero `# TODO(lab-6)` markers, dataset separation, `SAFETY(version="v1")`, `global` loss clustering, `ALIGN_PERCENTILE_50`, and all 6 `--dry-run` / `--strict-env` smoke passes.

- **Security & Governance track:** Continue to [Lab 7 (Optional): Enterprise Security & Governance Hardening](./07-LAB-OPTIONAL-SECURITY-AND-GOVERNANCE.md).
- **Fast-Track / Architecture track:** Skip Lab 7 cleanly and jump to [Lab 8: Agent Runtime vs. Self-Hosted GKE](./08-ARCHITECTURE-AGENT-RUNTIME-VS-GKE.md).
- **Finished with the workshop?** Run `make cleanup` from the repo root to delete sandboxes, alert policies, and Agent Runtime instances.

---

## Optional Reference & Deep Dive

<details>
<summary>OpenTelemetry GenAI SemConv Attributes, Dashboard Views & GCS Multimodal Offload</summary>

- **Mandatory OTel GenAI (`v1.37.0+`) Signals:** Invoke-agent span attributes (`gen_ai.agent.name`, `gen_ai.agent.description`, `gen_ai.conversation.id`) and inference event attributes on `gen_ai.client.inference.operation.details` (`gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`, `gen_ai.tool.definitions`). Note: ADK Python requires enum strings (`EVENT_ONLY`, `NO_CONTENT`, `SPAN_ONLY`, `SPAN_AND_EVENT`), whereas ADK Go expects `"1"`/`"true"`.
- **Console Observability & Traces:** Open **Agent Platform -> Agent Registry -> your agent -> Observability** (Overview, Evaluation, Models, Tools, Usage & Logs, Topology) and **Traces** (Session view by `gen_ai.conversation.id`, Trace view `invoke_workflow -> invoke_agent -> call_llm / execute_tool`, and Span view including Model Armor spans).
- **GCS Multimodal Payload Offload:** To avoid Cloud Logging entry size limits on large diffs or screenshots (requires `google-adk>=2.0.0`, `opentelemetry-instrumentation-google-genai>=0.4b0`, `fsspec[gcs]==2025.10.0`), set `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`, `OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT=jsonl`, `OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK=upload`, `OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH="gs://${EVAL_GCS_BUCKET}/otel-completions"`, `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT`, and `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true`. Grant the runtime SA `roles/storage.objectUser` on the bucket plus `logging.logWriter`, `monitoring.metricWriter`, and `telemetry.tracesWriter`.
- **Logs Explorer Filters:** `resource.labels.online_evaluator="projects/${GOOGLE_CLOUD_PROJECT}/locations/${EVAL_LOCATION:-global}/onlineEvaluators/YOUR_MONITOR_ID"`, `labels.reasoning_engine_id="${REASONING_ENGINE_ID}"`, or `labels.trace="YOUR_TRACE_ID"`.

</details>

<details>
<summary>Predefined Metrics, Traces vs. Sessions & Additional agents-cli Eval Commands</summary>

| Target | Graded Unit | Allowed Metrics |
|---|---|---|
| **Trace (single-turn)** | Single prompt -> tools -> response | `FINAL_RESPONSE_QUALITY`, `TOOL_USE_QUALITY`, `HALLUCINATION`, `SAFETY(version="v1")` (or `GENERAL_QUALITY` / `FINAL_RESPONSE_MATCH` for static responses) |
| **Session (multi-turn)** | Full multi-turn conversation | **Only** `MULTI_TURN_TASK_SUCCESS`, `MULTI_TURN_TOOL_USE_QUALITY`, `MULTI_TURN_TRAJECTORY_QUALITY` |

`agents-cli eval`'s `safety` maps to `safety_v1` (`1.0` = safe), whereas Python `types.RubricMetric.SAFETY` defaults to `safety_v3` (`1.0` = violated; alert with `COMPARISON_GT`, e.g. `> 0.05`).

```bash
# Run from starter/
agents-cli eval generate --dataset eval/datasets/coding_agent_single_turn.json -o artifacts/traces/
agents-cli eval grade --traces artifacts/traces/ --config eval/eval_config.yaml --qps 5 --region "${EVAL_LOCATION:-global}"
agents-cli eval submit --dataset eval/datasets/coding_agent_single_turn.json --dest "gs://${EVAL_GCS_BUCKET}/eval-runs" \
  --resource-name "${REASONING_ENGINE_NAME}" --region "${EVAL_LOCATION:-global}"
GOOGLE_CLOUD_LOCATION="${EVAL_LOCATION:-global}" agents-cli eval dataset synthesize --count 6 \
  --instruction "Fix failing unit tests and handle mid-session requirement changes." \
  --environment-context "Python 3.12 repo inside /workspace with pytest and ruff." -o artifacts/traces/synth_traces.json
agents-cli eval grade --traces artifacts/traces/synth_traces.json --region "${EVAL_LOCATION:-global}" \
  --metrics multi_turn_task_success,multi_turn_tool_use_quality,multi_turn_trajectory_quality
agents-cli eval analyze --eval-result artifacts/grade_results/results_latest.json --metric multi_turn_task_success
```

</details>

<details>
<summary>13-Pattern Failure Taxonomies & Failure-to-Fix Quick Map</summary>

- **`multi_turn_task_success_v1` (13):** *Hallucination:* `Hallucination of Action`, `Hallucination of Missing Information`, `Hallucination of Tool or Capability`. *Instruction Following:* `Constraint Violation`, `Futile Action (Under-Punting)`, `Incomplete Execution`, `Over-Punting`. *Tool Calling:* `Incorrect Tool Selection`, `Semantically Incorrect Tool Parameters`, `Syntactically Incorrect Tool Call`. *Tool Output:* `Incorrect Tool Output Processing`, `Insufficient Tool Output`, `Tool Failure`.
- **`multi_turn_tool_use_quality_v1` (13):** *Hallucination:* `Hallucination of Parameter Value`, `Hallucination of Tool`. *Tool Calling:* `Failure to Set Parameter`, `Incorrect Parameter Data Type`, `Incorrect Parameter Mapping`, `Incorrect Parameter Value`, `Incorrect Tool Selection`, `Invalid Tool Call Syntax`, `Non-Existent Parameter`, `Omission of Required Tool Call`, `Under-Punting`. *Tool Response:* `Irrelevant Tool Response`, `Tool Error`.

| Pattern / Low Metric | Targeted Fix |
|---|---|
| `Incomplete Execution`, `Hallucination of Action` | Require `Execute` (`pytest`/`ruff`) in system instructions before reporting success. |
| Low `multi_turn_trajectory_quality` | Clarify tool ordering and remove redundant `ReadFile` / `Execute` loops. |
| `Incorrect Parameter Mapping`, `Omission of Required Tool Call` | Tighten tool docstrings/schemas; set `tool_config` (`mode="ANY"`) if needed. |
| `Hallucination of Missing Information` | Cite only verified tool output and check `max_output_chars` truncation. |
| `Constraint Violation` in domain audits | Optimize `skills_to_register/secure-code-review/SKILL.md` with `--optimizer gepa-skills` and hot-update the registry. |
| Noisy judge scores | Enable `judge_model_sampling_count: 3` and pin `THINKING_LEVEL` (never lower thresholds to hide flakes). |

</details>

<details>
<summary>Optimizers, Example Store, adk optimize CLI & Canary Rollout / Rollback</summary>

| Strategy | Scope | Notes |
|---|---|---|
| **`SimplePromptOptimizer`** | Root `instruction` | Non-mutating Execute -> Evaluate -> Critique -> Rewrite loop; fast workshop default. |
| **`GEPARootAgentPromptOptimizer`** | Root `instruction` | Pareto-frontier evolutionary reflection (`adk optimize` default). |
| **`GEPARootAgentOptimizer`** | Root `instruction` + local `SkillToolset.skills` | Co-optimizes root prompt and `SKILL.md` body (`--optimizer gepa-skills`; preserves YAML frontmatter). |
| **Example Store (Preview)** | Dynamic few-shot examples (no redeploy) | Cosine similarity retrieval with optional tool-name filter (max 50 stores/region/project). |

**Running `adk optimize` directly with Gemini 4:** ADK 2.15 optimizers default to `thinking_budget=10240`, which Gemini 4 rejects with HTTP 400. Pass `--optimizer_config_file_path` with `thinking_level` (`{"optimizer_model": "gemini-4-hydrogen", "model_configuration": {"thinking_config": {"include_thoughts": true, "thinking_level": "MEDIUM"}}, "max_metric_calls": 20, "reflection_minibatch_size": 3}`) and run `GOOGLE_CLOUD_LOCATION="${MODEL_LOCATION:-global}" uv run adk optimize coding_agent --sampler_config_file_path eval/sampler_config.json --optimizer_config_file_path artifacts/optimizer_config.json --print_detailed_results`. You can also run `agents-cli eval optimize --dataset eval/datasets/coding_agent_single_turn.json --target-metric final_response_quality` once after manual iteration.

**Holdout Diff & 90/10 Canary Rollout (Track A: Root Prompt Fixes):**

```bash
agents-cli eval compare artifacts/grade_results/results_before.json artifacts/grade_results/results_after.json
curl -X PATCH -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json" \
  "https://${GOOGLE_CLOUD_LOCATION}-aiplatform.googleapis.com/v1beta1/${REASONING_ENGINE_NAME}?update_mask=traffic_config" \
  -d '{"trafficConfig":{"trafficSplitManual":{"targets":[{"runtimeRevisionName":"'"${STABLE_REVISION_NAME}"'","percent":90},{"runtimeRevisionName":"'"${CANARY_REVISION_NAME}"'","percent":10}]}}}'
```

Watch `online_evaluator/scores` by `runtime_revision_id`: roll back to 100% `${STABLE_REVISION_NAME}` if alerts fire, or promote to 100% (restoring `trafficSplitAlwaysLatest: {}` before Agent Gateway edits). For **Track B (Agent Registry skills)**, roll back in one command by setting `--default-revision` back to `.../revisions/rev-1` with `--target-state=active` (for teardown, run `--clear-default-revision --target-state=disabled` and delete revisions before deleting the skill).

**Official Docs:** [Observability](https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/observability/overview) | [Evaluation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/agent-evaluation) | [View Results & Clusters](https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/view-results) | [Quality Alerts](https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/quality-alerts) | [Optimize Agent](https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/optimize-agent) | [Example Store](https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/example-store/overview) | [Agent Registry Skill Revisions](https://docs.cloud.google.com/agent-registry/manage-skill-revisions)

</details>
