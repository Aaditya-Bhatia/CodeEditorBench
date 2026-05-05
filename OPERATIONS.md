# CodeEditorBench Operations

This is the single operational document for running CodeEditorBench in this repository.

Use it for:
- environment setup
- config-driven benchmark generation
- detached Docker judge evaluation
- Telegram notifications
- manual judge troubleshooting

All smaller operational docs should point here instead of duplicating steps.

## Pipeline

CodeEditorBench has two phases:

1. Host-side generation
   Model outputs are generated against the four benchmark datasets and written as JSONL.

2. Docker-side evaluation
   Those outputs are postprocessed, staged into the judge, submitted to MySQL, executed by the HUSTOJ-based runner, and aggregated into metrics.

The new default entrypoint is:

```bash
python scripts/run_benchmark.py /path/to/vllm_config.yaml
```

That command:
- reads a vLLM YAML config
- connects to the existing OpenAI-compatible vLLM server from the config port
- runs all four CodeEditorBench datasets in parallel by default
- postprocesses outputs into judge-ready JSONL
- stages those files into a per-run judge workspace
- starts a detached evaluation worker
- sends a Telegram notification when generation finishes
- sends another Telegram notification when evaluation finishes or fails

## Isolation And Delayed Eval

Generation and evaluation are now decoupled.

Important behavior:
- vLLM is only needed for the generation phase.
- After generation completes, evaluation runs entirely from files saved under `benchmark_runs/<run_name>/`.
- Detached eval can continue after the launcher or scheduler process exits.
- Multiple runs no longer share the same default judge container or writable judge state.

Each run now gets:
- a unique default Docker container name
- a per-run writable judge workspace under `benchmark_runs/<run_name>/judge/`
- a per-run metrics output under `benchmark_runs/<run_name>/judge/metrics/`

The heavy static judge assets are mounted read-only from the template judge tree, while run-specific state stays isolated.

## Environment

Recommended:

```bash
bash install.sh codeeditorbench
conda activate codeeditorbench
```

Or:

```bash
conda env create -f coder.yml
conda activate coder
```

Benchmark datasets should exist under:

```text
data/code_debug_primary.jsonl
data/code_translate_primary.jsonl
data/code_polishment_primary.jsonl
data/code_switch_primary.jsonl
```

## Run The Benchmark

Example:

```bash
python scripts/run_benchmark.py \
  /shared_workspace_mfs/aadi/Projects/EditBench_fork/configs/qwen3-14b-base-lora-dirty.yaml
```

Important config fields used by the runner:
- `model_name`
- `served_model_name`
- `port`
- `temperature`
- `top_p`
- `max_tokens`
- `batch_size`
- `max_workers`

Useful overrides:

```bash
python scripts/run_benchmark.py \
  /path/to/config.yaml \
  --prompt-model deepseek \
  --run-name qwen3-14b-base-lora-dirty-manual \
  --dataset-parallelism 2 \
  --batch-size 16 \
  --max-concurrent 16
```

Notes:
- `--prompt-model` controls which benchmark prompt wrapper is used.
- The runner defaults to a unique run name based on the config model name plus a UTC timestamp.
- Output artifacts are written under `benchmark_runs/<run_name>/`.
- Generation now defaults to `--dataset-parallelism 4`, so all datasets are inferred at once.
- `max_workers` from the YAML, or `--max-concurrent`, is applied to each active dataset worker.
- With the default four-way fanout, total in-flight request pressure against the vLLM server can be roughly `4 * max_workers`.
- If a shared vLLM server needs lower pressure, reduce `--dataset-parallelism` instead of changing eval behavior.

## Artifacts

Each run writes:

```text
benchmark_runs/<run_name>/
  raw/
  clean/
  judge/
  logs/detached_eval.log
  summary.json
```

`summary.json` is the main machine-readable status file. It records:
- config path
- API base
- prompt model
- staged judge filename
- detached eval worker PID
- model ID once submitted
- isolated judge directory
- isolated container name
- eval completion or failure state

## Telegram Notifications

The runner uses:

```text
/shared_workspace_mfs/aadi/Projects/notify_telegram.py
```

Generation completion notification is sent immediately after the detached eval worker is launched.

Eval completion or failure notification is sent by the detached worker.

If the notify script is missing, the benchmark still runs and notifications are skipped.

## Docker Judge

The helper launcher is:

```bash
bash evaluation/run_judge_container.sh
```

Default container name when launched manually:

```text
codeeditorbench_judge
```

For automated runs, the detached worker assigns a unique per-run container name unless `--container-name` is set explicitly.

The detached worker starts the container automatically if it is missing, or starts it if it already exists but is stopped.

## Detached Eval Worker

The background worker is:

```text
scripts/detached_eval_worker.py
```

It performs:
- `add_template.py --model-name <run_name>`
- `submit_solution.py --model-name <run_name>`
- judge runtime reset and watchdog startup via `run_judge.sh`
- polling until that model has no pending submissions left
- targeted `compute_metrics.py --model-id <model_id>`

It also automatically:
- checks real MySQL readiness instead of only checking whether the container is up
- repairs stale MySQL socket lock files and stale PID files
- recreates the judge container if MySQL still cannot be recovered
- clears stale `judge.pid`, `client*.pid`, and `run*/judge_client.pid` state before restarting the judge runtime
- restarts the judge runtime if submissions are pending but there are no active judge workers
- fails with a bounded timeout instead of hanging forever

The worker log is:

```text
benchmark_runs/<run_name>/logs/detached_eval.log
```

## Judge Scripts Changed For Targeted Runs

To avoid reprocessing the entire historical `solution_folder`, these judge scripts now accept targeted model filters:
- `evaluation/judge/scripts/add_template.py --model-name <run_name>`
- `evaluation/judge/scripts/submit_solution.py --model-name <run_name>`

This is required for safe automation because the repository already contains many example outputs.

## Manual Judge Checks

Normal operation should not require manual PID cleanup anymore. The detached worker now resets stale judge runtime state automatically.

Inspect container state:

```bash
docker ps -a --format 'table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}'
```

Enter container:

```bash
docker exec -it <container_name> /bin/bash
```

Start the judge watchdog manually inside the container:

```bash
cd /home/judge/scripts
nohup bash run_judge.sh > runlog.out 2>&1 &
```

Recompute metrics manually:

```bash
docker exec <container_name> bash -lc "cd /home/judge/scripts && python3 compute_metrics.py --model-id <model_id>"
```

Primary metrics output for automated runs:

```text
benchmark_runs/<run_name>/judge/metrics/metrics_primary.csv
```

## Judge Result Semantics

The judge is not an LLM-based grader.

It is an online-judge style executor based on HUSTOJ that:
- compiles code
- runs hidden tests
- stores outcomes in MySQL

Important pending states:
- `result < 4`
- `result = 14`

Successful states counted by the detached worker:
- `4`
- `41`
- `42`
- `43`

## Docs

The repo keeps only:
- `README.md`
- `OPERATIONS.md`
