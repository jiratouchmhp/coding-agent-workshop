# Agent Optimization & Feedback-to-Eval-to-Canary Flywheel

Production reference for closing the **Quality Flywheel** on Gemini Enterprise Agent Platform: ADK's built-in prompt/skill optimizers (`adk optimize`, `GEPARootAgentPromptOptimizer`, `GEPARootAgentOptimizer`, `SimplePromptOptimizer`), custom `Sampler`/`AgentOptimizer` extensions, `agents-cli eval optimize`, zero-redeploy few-shot refinement with **Example Store**, and the end-to-end **Feedback -> Eval -> Optimize -> Canary Rollout** workflow.

---

## 1. Choosing the Right Optimization Strategy

| Failure Root Cause | Recommended Fix | Redeploy Needed? |
|---|---|---|
| **Tool bug / schema / docstring error** | Fix tool code, signature, or docstrings directly *(GEPA does NOT optimize tools or sub-agents)* | Yes |
| **Missing domain-specific examples or function-calling patterns** | Upload curated input-output pairs to **Example Store** (Preview) for dynamic cosine-similarity retrieval | **No** (live immediately) |
| **System prompt / instruction gaps** (after manual fixes plateau) | Run **`adk optimize`** (`GEPARootAgentPromptOptimizer`), **`SimplePromptOptimizer`**, or **`agents-cli eval optimize`** | Yes (apply optimized instruction) |
| **Root agent + `SkillToolset` skill instruction gaps** | Run programmatic **`GEPARootAgentOptimizer`** (optimizes both root prompt and `SkillToolset` skills) | Yes |

---

## 2. Built-In ADK Optimizers Comparison (`google-adk>=2.0.0`)

| Optimizer Class (`google.adk.optimization.*`) | Status | Scope Optimized | Algorithm & Default Model Config | Key Config Parameters |
|---|---|---|---|---|
| **`GEPARootAgentPromptOptimizer`** (`gepa_root_agent_prompt_optimizer`) | Experimental *(emits warning; default for `adk optimize`)* | **Root agent instructions ONLY** *(does NOT optimize sub-agents, tools, or skills)* | GEPA Pareto-frontier evolutionary reflection; default **10K token thinking budget** | `optimizer_model`, `model_configuration`, `max_metric_calls` (`100`), `reflection_minibatch_size` (`3`), `run_dir` (warm starts) |
| **`GEPARootAgentOptimizer`** (`gepa_root_agent_optimizer`) | Experimental *(emits warning)* | **Root agent instructions AND `SkillToolset` skill instructions** *(NOT sub-agents or tools)* | GEPA Pareto-frontier reflection; default **`ThinkingLevel` `HIGH`** | `optimizer_model`, `model_configuration`, `max_metric_calls` (`100`), `reflection_minibatch_size` (`3`), `run_dir` (warm starts) |
| **`SimplePromptOptimizer`** (`simple_prompt_optimizer`) | Built-in | **Root agent instructions ONLY** *(single-prompt sequential refinement; does NOT mutate initial agent)* | 4-stage async loop: **Execute -> Evaluate -> Critique -> Rewrite**; default `gemini-2.5-flash` + **10K token thinking budget** | `num_iterations` (`10`), `batch_size` (`5`), `optimizer_model` (`"gemini-2.5-flash"`), `model_configuration` (`GenerateContentConfig`) |

---

## 3. ADK `adk optimize` CLI Workflow (`adk.dev/optimize/`)

`adk optimize` wires `LocalEvalSampler` and `GEPARootAgentPromptOptimizer` out of the box.

### Step 1 — Create ADK Eval Set (`train_eval_set.evalset.json` inside agent directory)

```json
{
  "eval_set_id": "train_eval_set",
  "name": "train_eval_set",
  "eval_cases": [
    {
      "eval_id": "is_good",
      "conversation": [
        {
          "invocation_id": "inv1",
          "user_content": { "parts": [{ "text": "Is 4 a bad number?" }], "role": "user" },
          "final_response": { "parts": [{ "text": "4 is not prime so it is a good number." }], "role": "model" }
        }
      ],
      "session_input": { "app_name": "hello_world", "user_id": "user" }
    }
  ]
}
```

### Step 2 — Create Sampler Config (`sampler_config.json` -> `LocalEvalSamplerConfig`)

```json
{
  "eval_config": {
    "criteria": {
      "response_match_score": 0.75
    }
  },
  "app_name": "hello_world",
  "train_eval_set": "train_eval_set",
  "validation_eval_set": "val_eval_set"
}
```

- **All `LocalEvalSamplerConfig` fields:** `eval_config`, `app_name` (must match containing agent directory name), `train_eval_set`, optional `train_eval_case_ids`, optional `validation_eval_set` (reuses `train_eval_set` if omitted — **always provide a separate holdout set in production to detect overfitting**), and optional `validation_eval_case_ids`.

### Step 3 — Run `adk optimize`

```bash
adk optimize [OPTIONS] AGENT_MODULE_FILE_PATH

# Example (AGENT_MODULE_FILE_PATH MUST be a directory whose __init__.py exposes `agent.root_agent`)
adk optimize path/to/hello_world \
    --sampler_config_file_path path/to/hello_world/sampler_config.json \
    --print_detailed_results \
    --log_level INFO
```

- **All verified CLI flags:**
  - `--sampler_config_file_path PATH` (required)
  - `--optimizer_config_file_path PATH` (optional; defaults to `GEPARootAgentPromptOptimizerConfig`)
  - `--print_detailed_results` (optional; prints detailed optimizer metrics)
  - `--log_level` (`DEBUG|INFO|WARNING|ERROR|CRITICAL`, default `INFO`)

---

## 4. Programmatic ADK Optimization & Custom Extensions

### A. Programmatic `GEPARootAgentPromptOptimizer` (Matches `adk optimize`)

```python
import asyncio
import logging
import os

import agent  # Exposes agent.root_agent inside current directory
from google.adk.cli.utils import envs, logs
from google.adk.evaluation.eval_config import EvalConfig
from google.adk.evaluation.local_eval_sets_manager import LocalEvalSetsManager
from google.adk.optimization.gepa_root_agent_prompt_optimizer import (
    GEPARootAgentPromptOptimizer,
    GEPARootAgentPromptOptimizerConfig,
)
from google.adk.optimization.local_eval_sampler import (
    LocalEvalSampler,
    LocalEvalSamplerConfig,
)

envs.load_dotenv_for_agent(".", ".")
logs.setup_adk_logger(logging.INFO)

sampler_config = LocalEvalSamplerConfig(
    eval_config=EvalConfig(criteria={"response_match_score": 0.75}),
    app_name="hello_world",  # Must match containing directory name
    train_eval_set="train_eval_set",
)
eval_sets_manager = LocalEvalSetsManager(agents_dir=os.path.dirname(os.getcwd()))
sampler = LocalEvalSampler(sampler_config, eval_sets_manager)

optimizer = GEPARootAgentPromptOptimizer(
    config=GEPARootAgentPromptOptimizerConfig(
        max_metric_calls=100,
        reflection_minibatch_size=3,
        run_dir="./gepa_runs/exp1",  # Enables warm starts / checkpointing
    )
)
result = asyncio.run(optimizer.optimize(agent.root_agent, sampler))

best_idx = result.gepa_result["best_idx"]
print("Validation score:", result.optimized_agents[best_idx].overall_score)
print("Optimized prompt:", result.optimized_agents[best_idx].optimized_agent.instruction)
```

*(Swap `GEPARootAgentPromptOptimizer` / `GEPARootAgentPromptOptimizerConfig` with `GEPARootAgentOptimizer` / `GEPARootAgentOptimizerConfig` from `google.adk.optimization.gepa_root_agent_optimizer` to co-optimize root instructions + `SkillToolset` skill instructions.)*

### B. Programmatic `SimplePromptOptimizer` (Sequential 4-Stage Loop)

```python
from google.adk.optimization.simple_prompt_optimizer import (
    SimplePromptOptimizer,
    SimplePromptOptimizerConfig,
)

optimizer = SimplePromptOptimizer(
    config=SimplePromptOptimizerConfig(
        num_iterations=5,
        batch_size=10,
        optimizer_model="gemini-2.5-flash",
    )
)
# Non-mutating: initial agent object is unchanged; highest-scoring variant is returned
optimized_result = await optimizer.optimize(agent.root_agent, sampler)
```

### C. Custom `Sampler` & `AgentOptimizer` Extensibility (`google.adk.optimization.*`)

- **Key Data Types (`data_types.py`):**
  - `SamplingResult(scores: dict[uid, float])` and subclass `UnstructuredSamplingResult(scores=..., data=...)` (holds per-example JSON-serializable trajectories, sub-metrics, and rationales — required by GEPA optimizers).
  - `AgentWithScores(optimized_agent: Agent, overall_score: float)` and `OptimizerResult(optimized_agents: list[AgentWithScores])` (multiple entries represent a Pareto frontier).
- **Custom `Sampler` (`sampler.py`):** Subclass `Sampler` and implement:
  - `get_train_example_ids(self)`
  - `get_validation_example_ids(self)`
  - `sample_and_score(self, candidate, example_set, batch, capture_full_eval_data)` where `example_set` is `"train"` or `"validation"`.
- **Custom `AgentOptimizer` (`agent_optimizer.py`):** Subclass `AgentOptimizer` and implement `optimize(self, initial_agent, sampler) -> OptimizerResult`.

---

## 5. `agents-cli eval optimize` & Vertex Optimizer Service

### `agents-cli eval optimize` (Experimental, ADK Python ONLY)

```bash
agents-cli eval optimize \
    --dataset tests/eval/datasets/basic-dataset.json \
    --target-metric final_response_quality
```

- Options can be stored in `tests/eval/optimization_config.json`; add `"print_detailed_results": true` for full per-iteration traces.
- **Operational Cost Guardrails:**
  1. GEPA makes many LLM calls and runs for **minutes to hours** — **never** run it in an automated loop or without explicit user approval.
  2. Suitable for **prompt-only failures**; exhaust targeted manual edits to instructions/tools first.
  3. Hold back an unseen evaluation slice to prevent overfitting, run at most a **single** final `eval optimize` pass, copy the optimized instruction from stdout into `agent.py`, and verify with `agents-cli eval compare <before>.json <after>.json`.

### High-Level Vertex AI Client Optimizer Snippet

The `evaluate-agents` overview documents:

```python
optimize_result = client.optimizer.optimize(
    targets=["system_prompt"],
    benchmark=eval_result,
    tests=eval_dataset,
)
```

> **Verification Caution:** `client.optimizer.optimize` only appears in the high-level overview snippet and is not yet detailed in the `vertexai._genai.evals.Evals` reference — verify installed `google-cloud-aiplatform` support in your environment before choosing it over `adk optimize`.

---

## 6. Zero-Redeploy Few-Shot Refinement: Example Store (Preview)

**Example Store** (Pre-GA Offerings Terms) dynamically retrieves relevant few-shot input-output examples at inference time via **cosine similarity search** (with optional **function-name filtering**), improving reasoning and tool calling without fine-tuning weights or redeploying your agent.

- **ADK Integration:** Linking an ADK agent to an `ExampleStore` instance automatically injects retrieved few-shot examples into LLM requests as soon as examples are uploaded. Non-ADK apps query the store and inject retrieved examples into prompts manually.
- **Hard Quota Limit:** Maximum **50 `ExampleStore` instances per region and project**.
- **Authoring Best Practices:**
  - Keep examples tightly relevant to real production queries (fewer, high-relevance examples cut token usage while improving accuracy).
  - Use low-complexity examples that cleanly show expected function names and argument transformations ("show, don't tell").
  - Match the exact prompt formatting consistent with model training data and clearly separate examples from live conversation history.

---

## 7. End-to-End Feedback-to-Eval-to-Canary Production Flywheel

Combine **Feedback Service** (`agentplatform.Client`), **Offline Eval & Loss Clustering** (`vertexai.Client` / `agents-cli`), **Optimization** (`adk optimize` / Example Store), and **`v1beta1` Revisions & Canary Traffic Splitting** (`agentplatform.Client`) into a safe production loop:

```text
1. Harvest negative production feedback + transcripts
   └── agentplatform.Client: feedback_entries.list(...) -> feedback_contexts.get(name=f"{entry.name}/feedbackContext")
2. Curate regression cases + holdout slice (EvaluationDataset JSON)
   └── Supplement with `eval dataset synthesize` or `generate_conversation_scenarios` for edge-case coverage
3. Baseline eval + Failure Clustering
   └── `agents-cli eval run` / `client.evals.evaluate(dataset=...)` + `generate_loss_clusters` (`global`)
4. Targeted fix or single optimization pass
   └── Fix tools/docstrings -> Upload Example Store few-shots (zero redeploy) -> OR `adk optimize` / `eval optimize`
5. Verify against holdout + diff baseline vs candidate
   └── `agents-cli eval compare baseline.json candidate.json` (confirm target up, zero regressions on other metrics)
6. Canary rollout via Agent Runtime v1beta1 Revisions (e.g., 90% stable / 10% candidate)
   └── Monitor `online_evaluator/scores` & Quality Alerts sliced by `runtime_revision_id`
7. Promote 100% (or instant rollback via `trafficSplitManual` 100% -> stable revision)
```

### Verified SDK Bridges (Feedback Harvest -> Canary Traffic Split)

```python
import os
import agentplatform

os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "TRUE"

# 1. Harvest production feedback entries and their exact transcript snapshots
ap_client = agentplatform.Client(
    project="PROJECT_ID",
    location="LOCATION",
    http_options={"api_version": "v1beta1"},
)
engine_name = "projects/PROJECT_ID/locations/LOCATION/reasoningEngines/RESOURCE_ID"

entries = ap_client.feedback_entries.list(
    name=engine_name,
    config={"filter": 'session_id="SESSION_ID"', "order_by": "create_time desc"},
)
for entry in entries:
    # Note: feedback_contexts.get requires the `/feedbackContext` suffix on entry.name
    ctx = ap_client.feedback_entries.feedback_contexts.get(
        name=f"{entry.name}/feedbackContext"
    )
    print(entry.name, entry.feedback_type, len(ctx.context_events))

# 2. After eval + compare pass, shift 10% canary traffic to the new revision
ap_client.runtimes.update(
    name=engine_name,
    config={
        "traffic_config": {
            "trafficSplitManual": {
                "targets": [
                    {
                        "runtimeRevisionName": f"{engine_name}/runtimeRevisions/STABLE_REV_ID",
                        "percent": 90,
                    },
                    {
                        "runtimeRevisionName": f"{engine_name}/runtimeRevisions/CANARY_REV_ID",
                        "percent": 10,
                    },
                ]
            }
        }
    },
)
```

---

## 8. Companion AI Coding Assistant Skills

Google publishes two standalone skills referenced in the official Agent Evaluation docs for editor-assisted workflows:

```bash
# CLI-driven evaluation & optimization loop for agents-cli projects
npx skills add https://github.com/google/agents-cli --skill google-agents-cli-eval

# SDK-driven evaluation flywheel using client.evals.evaluate()
npx skills add https://github.com/google/skills --skill agent-platform-eval-flywheel
```
