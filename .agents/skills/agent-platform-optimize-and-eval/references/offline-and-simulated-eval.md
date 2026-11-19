# Offline Evaluation, Metrics Registry & Simulated User Evaluation

Production reference for evaluating agents before production rollout or on historical traces: **Traces vs. Sessions**, supported regions, the complete **Managed Rubric Metric Registry** (including exact model call multipliers and the `safety_v3` polarity flip), **Vertex AI GenAI Client (`vertexai._genai.evals.Evals`)**, **Simulated User Evaluation**, and **`agents-cli eval`** local/CI gating workflows.

---

## 1. Core Concepts, Cadence & Supported Regions

### Traces vs. Sessions

- **Trace:** Factual, immutable record of a single execution path (model inputs, intermediate tool calls/responses, final response).
- **Session:** Complete multi-turn conversation between user and agent; evaluates context retention, goal fulfillment, and conversational flow across turns.

### Evaluation Cadences

| Evaluation Type | Primary Use Case | Cadence |
|---|---|---|
| **Rapid Evaluation** | Validating new prompts, agent logic, or model upgrades locally | Frequent (Development) |
| **Test Case Evaluation** | Deterministic regression gating against a fixed golden/synthetic dataset | Scheduled (CI/CD) |
| **Online Monitoring** | Continuous live production quality drift tracking | Continuous (~10-minute loop) |

### Supported Gen AI Evaluation Service Regions (15 Total)

- **US (7):** `us-central1`, `us-east1`, `us-east4`, `us-east5`, `us-south1`, `us-west1`, `us-west4`
- **Europe (7):** `europe-central2`, `europe-north1`, `europe-southwest1`, `europe-west1`, `europe-west4`, `europe-west8`, `europe-west9`
- **Global (1):** `global` *(default endpoint for `agents-cli eval run/grade/submit`; required for `generate_loss_clusters` and `eval analyze`)*

> **Unsupported Region Error & Data-Residency Fallback:** Passing any other region fails with `400 FAILED_PRECONDITION: Unsupported region for Vertex Evaluation Service: <region>`. When no supported region meets data residency requirements, grade in-process via `agents-cli eval` local custom metrics (`custom_function`, default `execution: local`) — your Python function can call a compliant regional Gemini endpoint directly as a judge.

---

## 2. Metrics Taxonomy & Complete Managed Metric Matrix

Four metric categories are supported across Console, SDK, and `agents-cli`:

1. **Adaptive Rubrics (Recommended):** Dynamically generates tailored per-prompt pass/fail unit tests from agent instructions, tools, and user intent, then validates each rubric with a verdict + natural-language rationale (`score` = pass rate).
2. **Static Rubrics:** Fixed scoring criteria applied identically across all cases (e.g., Hallucination, Safety, Grounding, Final Response Match).
3. **Computation-Based Metrics:** Deterministic algorithms (`ROUGE`, `BLEU`, exact match) requiring ground-truth `reference`.
4. **Custom Metrics (Registry / SDK / CLI):** Custom Judge LLM (`types.LLMMetric` / `prompt_template`) or Python code (`types.CodeExecutionMetric` / `custom_function`).

### Predefined Agent & Core Managed Rubric Metrics (Verified `rubric-metric-details`)

| Metric | Latest Version | Type | Python SDK Accessor (`types.RubricMetric.*`) | `agents-cli` Name | Required Inputs | Judge LLM Calls / Case |
|---|---|---|---|---|---|---|
| **Agent Final Response Quality** | `final_response_quality_v2` | Adaptive | `FINAL_RESPONSE_QUALITY` | `final_response_quality` | `prompt`, `response`, `developer_instruction`, `tool_declarations`, `intermediate_events`, opt `rubric_groups` | 5× Gemini 3.5 Flash + 1× Gemini 3.1 Pro |
| **Agent Tool Use Quality** | `tool_use_quality_v2` | Adaptive | `TOOL_USE_QUALITY` | `tool_use_quality` | `prompt`, `developer_instruction`, `tool_declarations`, `intermediate_events`, opt `rubric_groups` | 5× Gemini 3.5 Flash + 1× Gemini 3.1 Pro |
| **Agent Hallucination** | `hallucination_v2` | Static | `HALLUCINATION` | `hallucination` | `response`, `developer_instruction`, `tool_declarations`, `intermediate_events`, opt `evaluate_intermediate_nl_responses` (`False`) | 2× Gemini 3.5 Flash |
| **Safety** | `safety_v3` *(see polarity warning!)* | Static | `SAFETY` | `safety` | `prompt`, `response` | **31× Gemini 3.5 Flash** (`v1`: 10× 2.5 Flash) |
| **Agent Multi-turn Task Success** | `multi_turn_task_success_v1` | Adaptive | `MULTI_TURN_TASK_SUCCESS` | `multi_turn_task_success` | `agent_eval_data` (multi-turn trace) | 2× Gemini 3.1 Pro + 5× Gemini 3 Flash |
| **Agent Multi-turn Tool Use Quality** | `multi_turn_tool_use_quality_v1` | Adaptive | `MULTI_TURN_TOOL_USE_QUALITY` | `multi_turn_tool_use_quality` | `agent_eval_data` (multi-turn trace) | 2× Gemini 3.1 Pro + 5× Gemini 3 Flash |
| **Agent Multi-turn Trajectory Quality** | `multi_turn_trajectory_quality_v1` | Adaptive | `MULTI_TURN_TRAJECTORY_QUALITY` | `multi_turn_trajectory_quality` | `agent_eval_data` (multi-turn trace) | 2× Gemini 3.1 Pro + 5× Gemini 3 Flash |
| **Agent Final Response Match** | `final_response_match_v3` | Static | `FINAL_RESPONSE_MATCH` | `final_response_match` | `prompt`, `response`, **`reference`** | 5× Gemini 3.5 Flash (`1`=match, `0`=mismatch) |
| **Agent Final Response Ref-Free** | `final_response_reference_free_v2` | Adaptive | `FINAL_RESPONSE_REFERENCE_FREE` | `final_response_reference_free` | `prompt`, `response`, **`rubric_groups`** (no auto-gen) | 5× Gemini 3.5 Flash |
| **General / Text / Instr Following** | `*_v2` | Adaptive | `GENERAL_QUALITY`, `TEXT_QUALITY`, `INSTRUCTION_FOLLOWING` | `general_quality`, `text_quality`, `instruction_following` | `prompt`, `response`, opt `rubric_groups` | 6× Gemini 3.5 Flash |
| **Grounding** | `grounding_v2` | Static | `GROUNDING` | `grounding` | `prompt`, `response`, **`context`** | 1× Gemini 3.5 Flash (`0` if any sentence `unsupported`/`contradictory`) |
| **Gecko T2I / T2V** | `gecko_text2image_v2` / `text2video_v2` | Adaptive | `GECKO_TEXT2IMAGE`, `GECKO_TEXT2VIDEO` | — | `prompt`, image/video file `response` | 2× Gemini 3.5 Flash |

### Critical Metric Rules & Gotchas

1. **SAFETY SCORE POLARITY FLIP (`safety_v3` vs `safety_v1`):**
   - **`safety_v3` (latest default):** **`1` = UNSAFE** (at least one policy violated: `hate_harassment`, `sexual_content`, `violence_gore`, `medical_advice`, `dangerous_content`, `csae`) and **`0` = SAFE**.
   - **`safety_v1` (legacy):** **`0` = UNSAFE** and **`1` = SAFE** (checks PII/demographic, hate speech, dangerous content, harassment, sexually explicit).
   - Always verify which version is active before setting CI thresholds or Cloud Monitoring alerts!
2. **Multi-Turn 400 Restriction:** **ONLY** the 3 `multi_turn_*` metrics (`multi_turn_task_success`, `multi_turn_tool_use_quality`, `multi_turn_trajectory_quality`) accept multi-turn agent traces; every other built-in metric rejects them with HTTP 400 (`Single-turn metric '<name>' received agent_eval_data with N turns`). Split single-turn and multi-turn cases into separate dataset + config pairs.
3. **Version Pinning for Regional Judge Availability:** Latest metric versions require **Gemini 3.5 Flash** availability. In regions without Gemini 3.5 Flash, pin to the prior Gemini 2.5 version:
   ```python
   from vertexai import types
   general_v1 = types.RubricMetric.GENERAL_QUALITY(version="v1")
   safety_v1 = types.RubricMetric.SAFETY(version="v1")
   ```
4. **Legacy Pointwise Compatibility:** Pointwise templates (`types.RubricMetric.COHERENCE`, `types.RubricMetric.FLUENCY`) still work in the GenAI Client; pairwise metrics are unsupported (compare multiple candidates in one evaluation instead).

---

## 3. Console Workflows for Offline Evaluation & Metric Registry

**Prerequisites:** Deployed Agent Runtime with Cloud Trace + required OTel GenAI signals (`OTEL_SEMCONV_STABILITY_OPT_IN='gen_ai_latest_experimental'`, `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT='EVENT_ONLY'`, plus optional GCS upload env vars for multimodal) and a GCS bucket for `Output private data path` (auto-remembered after first run).

- **Path A — Batch Evaluation from Registry:**
  1. Open `Agent Platform > Agents > Evaluation` (`https://console.cloud.google.com/agent-platform/agent-evaluation`) -> **New evaluation**.
  2. Choose **Traces** or **Sessions** tab -> filter by **Version** or timeframe (e.g., `"Last 2 weeks"`) -> select target IDs -> **Continue**.
  3. Set **Evaluation name** and **Output private data path** (`gs://...`).
  4. Review metrics (all 4 core single-turn metrics are pre-selected; add/remove predefined or custom registry metrics) -> **Evaluate agent**.
- **Path B — Ad-Hoc Single Trace or Session Evaluation:**
  1. Open `Agent Platform > Agents > Deployments` (`https://console.cloud.google.com/agent-platform/runtimes`) -> select agent -> **Traces** tab -> **Session view** or **Trace view**.
  2. Select a row -> open **Evaluation** tab in the Details pane -> click **Evaluate**.
- **Path C — Console Metric Registry:**
  1. Open `Evaluation -> Metrics` tab -> **New metric** -> choose **Custom LLM metric** (use **Sample** buttons for Clarity/Excitement starter rubrics) or **Custom code metric**.
  2. Click any registered metric to view read-only, or open **More options** to **Duplicate** or **Delete**.

---

## 4. Python SDK Workflow (`vertexai._genai.evals.Evals`, `google-cloud-aiplatform>=1.153.1`)

> **SDK Naming & Interface Warning:** Evaluation docs refer to the **"Agent Platform SDK"** in prose, yet **every evaluation Python workflow installs `google-cloud-aiplatform[adk,evaluation]` and imports `from vertexai import Client, evals, types`** (uppercase `Client`). The GenAI Client (`Preview`) supersedes legacy GA `from vertexai.evaluation import EvalTask` (which lacks adaptive rubrics). Always pass **`dataset=`** to `client.evals.evaluate(...)` — ignore the `traces=` typo in high-level overview docs.

### Core Offline Evaluation, Rubric Generation, Batch Runs & Metric Registry CRUD

```python
# pip install "google-cloud-aiplatform[adk,evaluation]"
from vertexai import Client, types

client = Client(project="YOUR_PROJECT_ID", location="us-central1")

# 1. Synchronous offline evaluation (verified signature: dataset=, NOT traces=)
result = client.evals.evaluate(
    dataset=eval_dataset,  # pd.DataFrame, EvaluationDataset, dict, or list for multi-candidate
    metrics=[
        types.RubricMetric.FINAL_RESPONSE_QUALITY,
        types.RubricMetric.TOOL_USE_QUALITY,
        types.RubricMetric.HALLUCINATION,
        types.RubricMetric.SAFETY,
    ],
)
result.show()  # Interactive Colab/Jupyter summary + expandable per-case rubric verdicts

# 2. Optional: Pre-generate rubrics separately so multiple candidates share identical tests
dataset_with_rubrics = client.evals.generate_rubrics(
    src=eval_dataset,
    rubric_group_name="core_agent_checks",
    predefined_spec_name=types.RubricMetric.FINAL_RESPONSE_QUALITY,
)

# 3. Cloud-side managed EvaluationRun (supports server-side agent inference, loss analysis & red teaming)
eval_run = client.evals.create_evaluation_run(
    dataset=eval_dataset,
    dest="gs://YOUR_BUCKET/eval-runs/run-001",
    display_name="nightly-regression-run",
    metrics=[types.RubricMetric.MULTI_TURN_TASK_SUCCESS],
    agent="projects/YOUR_PROJECT_ID/locations/us-central1/reasoningEngines/ENGINE_ID",
    loss_analysis_metrics=[types.RubricMetric.MULTI_TURN_TASK_SUCCESS],
)
fetched_run = client.evals.get_evaluation_run(name=eval_run.name, include_evaluation_items=True)

# 4. Large-scale async batch evaluation LRO
batch_op = client.evals.batch_evaluate(
    dataset=eval_dataset,
    metrics=[types.RubricMetric.GENERAL_QUALITY],
    dest="gs://YOUR_BUCKET/eval-batch/output",
)

# 5. Register Custom LLM Metric in Metric Registry
tone_metric = types.LLMMetric(
    name="tone_check",
    prompt_template="Analyze the tone of the response for {prompt}: {response}. Return JSON.",
    result_parsing_function="""
import json
def parse_results(responses):
    response = json.loads(responses[0])
    return {
        "score": response.get("score", 0.0),
        "explanation": response.get("explanation", "default explanation"),
    }
""",
)
tone_metric_resource = client.evals.create_evaluation_metric(metric=tone_metric)

# 6. Register Custom Code Metric in Metric Registry
accuracy_metric = types.CodeExecutionMetric(
    name="multi_turn_accuracy",
    custom_function="""
def evaluate(instance: dict) -> float:
    turns = instance.get("agent_eval_data", {}).get("turns", [])
    return 1.0 if turns else 0.0
""",
)
code_metric_resource = client.evals.create_evaluation_metric(metric=accuracy_metric)

# Registry inspection & cleanup
all_metrics = client.evals.list_evaluation_metrics()
metric_obj = client.evals.get_evaluation_metric(metric_resource_name=tone_metric_resource)
client.evals.delete_evaluation_metric(metric_resource_name=tone_metric_resource)
```

---

## 5. Simulated User Evaluation (2-Step Workflow, Personas & Environment Mocking)

Simulated evaluation bootstraps multi-turn test suites with zero production traffic:

1. **Stage 1 — Generate Scenarios:** Reads agent instructions and tool declarations to synthesize `eval_cases`, each pairing a **Starting Prompt** (turn-0 user message) with a hidden **Conversation Plan** (persona, hidden goal, and reaction rules).
2. **Stage 2 — Simulate Sessions:** The **User Simulator** LLM roleplays multi-turn exchanges against your agent, producing canonical behavior traces (`agent_data`).
   - **Simulator Settings:** `max_turn` (prevents infinite loops; **default `5`**), simulator `model_name`, and `model_configuration`.
   - **Environment Simulation:** Intercepts specific tool calls during simulation to inject mocked responses, HTTP 503 failures, or latency spikes without hitting live backends.

### Console Simulation Workflow

1. Prerequisite: register at least one immutable agent version snapshot in **Agent Registry**.
2. Go to `Agent Platform > Agents > Evaluation` (`https://console.cloud.google.com/agent-platform/agent-evaluation`) -> **New evaluation** -> **Simulate sessions**.
3. Enter a **Generation instruction** (e.g., `"Generate scenarios where the user tries to book a flight but then changes their mind"`).
4. Review, edit, or add rows in the generated scenarios table -> configure simulator settings -> run simulation.

### Python SDK Simulation Workflow

```python
from google.adk.agents import Agent
from vertexai import Client, types

client = Client(project="YOUR_PROJECT_ID", location="us-central1")

travel_agent = Agent(
    model="gemini-3-flash-preview",
    name="travel_agent",
    instruction="You are a travel expert; help users find flights and book flights with flight ID.",
    tools=[find_flights, book_flight],
)

# Step 1: Extract AgentInfo and synthesize multi-turn scenarios
travel_agent_info = types.evals.AgentInfo.load_from_agent(agent=travel_agent)
eval_dataset = client.evals.generate_conversation_scenarios(
    agent_info=travel_agent_info,
    config={
        "count": 5,
        "generation_instruction": "Generate scenarios where the user tries to book a flight.",
        "environment_context": "Today is Monday. User is in San Francisco. Flights to Paris, New York, Tokyo, Chicago, Sydney are available.",
    },
)

# Step 2: Execute multi-turn User Simulator to produce canonical traces
eval_dataset_with_traces = client.evals.run_inference(
    agent=travel_agent,
    src=eval_dataset,
    config={"user_simulator_config": {"max_turn": 5}},
)

# Step 3: Grade simulated multi-turn traces with multi_turn_* metrics ONLY
sim_results = client.evals.evaluate(
    dataset=eval_dataset_with_traces,
    metrics=[
        types.RubricMetric.MULTI_TURN_TASK_SUCCESS,
        types.RubricMetric.MULTI_TURN_TOOL_USE_QUALITY,
        types.RubricMetric.MULTI_TURN_TRAJECTORY_QUALITY,
    ],
)
sim_results.show()
```

### `agents-cli` Simulated Evaluation (`eval dataset synthesize`)

```bash
# Experimental — ADK Python ONLY (LangChain and Claude templates refuse it)
agents-cli eval dataset synthesize --count 10 \
    --instruction "Generate scenarios where a developer asks the agent to refactor code and fix failing pytest tests." \
    --environment-context "Python 3.12 repo with pytest suite inside /workspace." \
    -o artifacts/traces/synth_traces.json

# Output ALREADY contains simulated traces -> skip `eval generate`, grade directly with multi_turn_* metrics!
agents-cli eval grade --traces artifacts/traces/synth_traces.json \
    --metrics multi_turn_task_success,multi_turn_tool_use_quality,multi_turn_trajectory_quality
```

> **Region Trap:** `eval dataset synthesize` runs your agent locally (reading `.env` `GOOGLE_CLOUD_LOCATION`), **but scenario generation runs server-side at `GOOGLE_CLOUD_LOCATION`**. Keep `GOOGLE_CLOUD_LOCATION` set to one of the 15 eval-supported regions (or `global`), and pin a different model region in code via `Gemini(model=..., client_kwargs={"location": ...})` if needed.

---

## 6. `agents-cli` Offline Evaluation, Dataset Schema & CI Gating (`v1.15.0`)

### Project Layout & Essential Commands

- **Python layout:** `tests/eval/datasets/basic-dataset.json`, `tests/eval/eval_config.yaml`, `tests/eval/response_quality.py` (Go `adk_go` uses `eval/`).
- **Outputs:** Traces in `artifacts/traces/`; timestamped reports in `artifacts/grade_results/results_<YYYYMMDD_HHMMSS>.{json,html}`.

```bash
# List all built-in metrics with descriptions
agents-cli eval metric list

# Combined generate + grade (exits 1 if ANY threshold fails OR ANY case errors)
agents-cli eval run
agents-cli eval run --dataset tests/eval/datasets/custom.json \
    --metrics final_response_quality,safety --output ./out/ \
    --fail-under final_response_quality=0.8

# Evaluate an already-deployed HTTP agent (ADK templates only)
agents-cli eval run --url https://my-agent.run.app --app-name app

# Decoupled generate -> grade (reuse traces, adjust default 15 QPS limit, override region)
agents-cli eval generate --dataset tests/eval/datasets/custom.json -o custom_traces/
agents-cli eval grade --traces custom_traces/ --config tests/eval/eval_config.yaml \
    --qps 5 --region us-central1

# Live / voice WebSocket agent (/run_live; requires Live model + pinned model region + user-only turns)
agents-cli eval generate --mode adk_live

# Side-by-side before vs. after regression diff
agents-cli eval compare artifacts/grade_results/results_before.json \
    artifacts/grade_results/results_after.json

# Experimental cloud-side batch run (CI / large datasets)
agents-cli eval submit --dataset tests/eval/datasets/custom.json \
    --dest gs://YOUR_BUCKET \
    --resource-name projects/PROJECT_ID/locations/LOCATION/reasoningEngines/ENGINE_ID \
    --region us-central1
agents-cli eval results --run-id RUN_ID
```

### Canonical `EvaluationDataset` JSON Schema & Common Mistakes

- **Single-turn inference input (`prompt`):** Wrap `responses` and `reference` inside `ResponseCandidate` (`{"response": {"role": "model", "parts": [...]}}`), whereas `prompt` and `agent_data.turns[].events[].content` are bare `Content` objects.
- **Multi-turn / multi-agent (`agent_data`):** Contains `agents` map + chronological `turns` (`turn_index` 0-based) with `events` (`author`: `"user"`, agent ID, or `"tool"`).
- **Per-case rubrics (`rubric_groups`):** Supported on single-turn managed rubric metrics (`metric_spec_parameters.rubric_group_key` required when >1 group exists, else HTTP 400). For multi-turn custom rubrics, read `instance["rubric_groups"]` in a local `custom_function_file` judge.

| Common Dataset Mistake | Exact Fix |
|---|---|
| `role: "assistant"` | Use `role: "model"` (Gemini platform convention). |
| Missing `turn_index` | Set sequential 0-based `turn_index` on every turn. |
| Raw dict for tool return | Wrap in `parts: [{"function_response": {"name": ..., "response": ...}}]`. |
| Mixing `prompt` and `agent_data` in one `EvalCase` | Use either `prompt` (single-turn) or `agent_data` (multi-turn), never both. |
| Authoring agent replies for `--mode adk_live` | Author **user-only** turns; authored agent turns are ignored with a warning. |

### Verified `tests/eval/eval_config.yaml` Schema

```yaml
metrics_to_run:
  - multi_turn_task_success
  - response_under_500_chars
  - response_quality_rubric

custom_metrics:
  - name: response_under_500_chars
    # Runs locally in-process by default (no GCP project needed).
    # Add `execution: remote` to run in sandboxed server-side CodeExecutionMetric.
    custom_function: |
      def evaluate(instance: dict) -> dict:
          response = instance.get("response") or {}
          text = "".join(p.get("text", "") for p in (response.get("parts") or []) if p.get("text"))
          return {"score": 1.0 if len(text) <= 500 else 0.0, "explanation": f"{len(text)} chars"}

  - name: response_quality_rubric
    prompt_template: |
      Rate 1-5 for accuracy and helpfulness.
      Prompt: {prompt} | Response: {response} | Full trace: {agent_data}
      Return JSON: {"score": <1|2|3|4|5>, "explanation": "<reason>"}
    judge_model: gemini-3.8-flash
    judge_model_sampling_count: 3   # 1..32

thresholds:
  multi_turn_task_success: 0.8
  response_under_500_chars: 1.0
  response_quality_rubric: 4
```

---

## 7. Common ADK & Evaluation Failure Modes

| Symptom / Error | Cause | Fix |
|---|---|---|
| `"Session not found"` in `eval generate` or `adk optimize` | ADK `App(name=...)` does not match the containing directory name | Set `App(root_agent=root_agent, name="app")` inside `app/`. |
| First-turn `KeyError` on `{state_key}` in instruction | Session state key uninitialized on turn 0 | Initialize defaults inside `async def init_state(callback_context: CallbackContext) -> None` passed to `before_agent_callback`. |
| Thinking model skips expected tool calls | Thinking mode answers directly without calling tools | Set `tool_config` with `mode="ANY"` or switch to a non-thinking model. |
| Scores fluctuate across identical runs | Non-deterministic decoding or single-sample LLM judge | Set `temperature=0` on agent and `judge_model_sampling_count: 3` on custom judge; never delete flaky cases or lower thresholds. |
| Built-in judge ignores image/audio inputs | Default text extractor (`get_text_from_content()`) skips non-text parts | Implement a custom metric with a vision/audio-capable judge model. |
| `400 FAILED_PRECONDITION: Unsupported region` | `--region` or client `location` outside the 15 supported eval regions | Pass `--region global` or a supported US/EU region, or use local `custom_function` metrics. |
