# CodeEditorBench Migration

Sets up this repo's environment on a new server.

## Prerequisites

- Linux server with conda installed and in PATH
- Docker installed (for the judge)
- The benchmark dataset files (4 JSONL files — not in git)

## Quick Start

```bash
git clone <your-fork-url> CodeEditorBench
cd CodeEditorBench

# Install conda env + pull judge image + check data files
bash migrate.sh

# Activate and run
conda activate codeeditorbench
python scripts/run_benchmark.py /path/to/vllm_config.yaml
```

## What `migrate.sh` Does

1. Creates/updates the `codeeditorbench` conda env from `coder.yml`
2. Pulls the Docker judge image (`xliudg/code_editor_bench:latest`)
3. Checks that all 4 benchmark datasets exist in `data/`
4. Creates the `benchmark_runs/` output directory

## Benchmark Data Files

These must be copied manually (not in git):

```
data/code_debug_primary.jsonl
data/code_translate_primary.jsonl
data/code_polishment_primary.jsonl
data/code_switch_primary.jsonl
```

## Full Usage

See `OPERATIONS.md` for benchmark running, judge management, and evaluation details.
