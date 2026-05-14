# Eval Instructions (detached CPU eval) — CodeEditorBench

This repo contains **generation outputs** from the same-size dirty-LoRA
experiment, committed by the k8s GPU pod. The judge / eval phase runs on
a separate CPU machine using these committed artifacts — generation is
not re-run.

## Critical: experiment isolation

The same model_name slugs (e.g. `qwen2.5-coder-7b-lora-dirty`) are
**shared** with the prior different-size experiment. The two are
distinguished ONLY by `summary.json:"config_path"`:

- **Same-size** (this experiment, what we want to eval):
  `config_path` starts with `/workspace/Master-Benchmarking-Orchestrator/`
- **Different-size** (older experiment):
  `config_path` starts with `/shared_workspace_mfs/.../Master_VLLM/`

Before running judges, verify every run dir:

```bash
for f in benchmark_runs/*/summary.json; do
  cfg=$(python3 -c "import json; print(json.load(open('$f')).get('config_path',''))")
  [[ "$cfg" != /workspace/Master-Benchmarking-Orchestrator/* ]] && echo "WRONG-EXPERIMENT: $f -> $cfg"
done
```

Expect: empty output. If anything prints, you have a stale checkout or
mixed history — STOP and ask before evaluating.

## Which dirs are ready

Only dirs where `summary.json:"status" == "generation_complete"`. Anything
else (`running_generation`, `generation_failed`, `generation_pending`,
`eval_running`, `eval_failed`) is either partial or already mid-judge —
skip it. Cross-check by row count: a complete run has `clean_rows=7960`
(4 datasets × ~1990 rows).

## 3B-tier models

Regenerated cleanly on 2026-05-14 and now included. Eligible 3B slugs:
`qwen2.5-3b-lora-dirty`, `qwen2.5-coder-3b-instruct-lora-dirty`,
`qwen3-4b-base-lora-dirty`, `starcoder2-3b-lora-dirty`. (The earlier
contaminated dirs were removed in commit `6ba6143` before the rerun.)

`llama-3.2-3b-lora-dirty` has no generation dir on the GPU pod and is
not included; it may land later.

## Eval entrypoint: CodeEditorBench

Generation artifacts under `benchmark_runs/<model>-<UTC-ts>/`:

- `raw/<dataset>/<run-stem>_0_end.jsonl` — full vLLM outputs (audit)
- `clean/<dataset>/<run-stem>_0_end.jsonl` — postprocessed JSONL the judge
  consumes
- `judge/solution_folder/<dataset>/<staged_name>.jsonl` — pre-staged input
  files for the Docker judge (see `summary.json:"staged_name"`)
- `judge/` — per-run isolated judge workspace (scripts, etc dir, etc.)
- `summary.json` — run metadata, includes `config_path`, `staged_name`,
  `container_name`, `judge_solution_root`, `clean_root`, `raw_root`,
  `datasets`

### Prerequisites on the eval machine

- Docker daemon running
- The CEB repo at `/workspace/CodeEditorBench` (paths in `summary.json`
  assume this; if you check out elsewhere, the detached worker needs the
  paths updated or you `cd` into a worktree at this path)
- MySQL via the per-run Docker container; the worker handles it

### Run eval on one model

```bash
cd /workspace/CodeEditorBench
# The eval-only entrypoint is the detached worker, NOT run_benchmark.py
# (that script does generation too — bypass it).
python scripts/detached_eval_worker.py \
    --run-name <model>-<UTC-ts> \
    --run-dir benchmark_runs/<model>-<UTC-ts> \
    --summary-path benchmark_runs/<model>-<UTC-ts>/summary.json
```

This:
1. Builds a per-run Docker container from the staged JSONL.
2. Submits solutions to the HUSTOJ judge inside the container.
3. Polls until the judge finishes (or hits eval-stall timeout).
4. Aggregates metrics into `judge/metrics/`.
5. Updates `summary.json` to `status=eval_complete` with
   `eval_completed_at_utc` set.

See `OPERATIONS.md` § "Isolation And Delayed Eval" for the deeper protocol.

### Run dirs ready (as of this commit)

```
codellama-13b-hf-lora-dirty-20260513T040842367272Z
codellama-7b-hf-lora-dirty-20260512T031245241413Z
deepseek-coder-6.7b-base-lora-dirty-20260512T062122762789Z
qwen2.5-coder-14b-instruct-lora-dirty-20260513T090049388059Z
qwen2.5-coder-14b-lora-dirty-20260513T082723360426Z
qwen2.5-coder-7b-instruct-lora-dirty-20260512T184421411771Z
qwen2.5-coder-7b-lora-dirty-20260511T104646422197Z
qwen3-8b-base-lora-dirty-20260512T054433853068Z
starcoder2-15b-lora-dirty-20260513T105605515507Z
starcoder2-7b-lora-dirty-20260512T162336480292Z
qwen2.5-3b-lora-dirty-20260514T020245332605Z
qwen2.5-coder-3b-instruct-lora-dirty-20260514T020219218392Z
qwen3-4b-base-lora-dirty-20260514T022129874000Z
starcoder2-3b-lora-dirty-20260514T031602013184Z
```
