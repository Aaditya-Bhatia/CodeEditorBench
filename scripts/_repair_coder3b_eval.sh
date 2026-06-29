#!/usr/bin/env bash
# One-shot repair: for each Qwen2.5-Coder-3B base LoRA CEB run whose eval
# died because /home/judge/etc was missing, postprocess raw -> clean,
# stage clean -> judge solution_folder, and relaunch the detached
# eval worker. Idempotent re: container names (worker stops/removes on exit).
set -euo pipefail

CEB=/shared_workspace_mfs/aadi/Projects/CodeEditorBench
PY=/shared_workspace_mfs/aadi/miniconda3/envs/SFT_env/bin/python
TEMPLATE=$CEB/evaluation/judge
DATASETS=(debug translate polishment switch)

declare -A RUNS=(
  [qwen2.5-coder-3b-lora-clean]=qwen2.5-coder-3b-lora-clean-20260515T165024236513Z
  [qwen2.5-coder-3b-lora-dirty]=qwen2.5-coder-3b-lora-dirty-20260515T165024311087Z
  [qwen2.5-coder-3b-lora-dirty-ss]=qwen2.5-coder-3b-lora-dirty-ss-20260515T170923238880Z
  [qwen2.5-coder-3b-lora-unclean-ss]=qwen2.5-coder-3b-lora-unclean-ss-20260515T172642718261Z
  [qwen2.5-coder-3b-lora-unclean74k]=qwen2.5-coder-3b-lora-unclean74k-20260515T170623225012Z
)

cd "$CEB"
for model in "${!RUNS[@]}"; do
  run=${RUNS[$model]}
  rd=$CEB/benchmark_runs/$run
  echo "=== $model :: $run ==="

  raw_basename=$($PY -c "n=r'''$run'''.split('/')[-1].replace('-','_').replace('.','_'); print(f'{n}_0_end.jsonl')")
  staged=$run.jsonl

  $PY result_postprocess.py --input-root "$rd/raw" --output-root "$rd/clean" --files "$raw_basename"

  for ds in "${DATASETS[@]}"; do
    src=$rd/clean/code_$ds/$raw_basename
    dst_dir=$rd/judge/solution_folder/code_$ds
    mkdir -p "$dst_dir"
    if [[ ! -f $src ]]; then echo "MISSING $src"; exit 1; fi
    cp "$src" "$dst_dir/$staged"
  done

  $PY -c "
import json,fcntl,os,time
from pathlib import Path
p=Path('$rd/summary.json')
with p.open('a+') as h:
    fcntl.flock(h,fcntl.LOCK_EX); h.seek(0); d=json.loads(h.read() or '{}')
    d.update(status='eval_running', staged_name='$staged', error=None,
             eval_failed_at_utc=None, eval_started_at_utc=time.strftime('%Y-%m-%dT%H:%M:%S+00:00',time.gmtime()))
    t=p.with_suffix('.tmp')
    t.write_text(json.dumps(d,indent=2)+'\n')
    os.replace(t,p)
    fcntl.flock(h,fcntl.LOCK_UN)
"

  cont=$(jq -r .container_name "$rd/summary.json")
  nohup $PY scripts/detached_eval_worker.py \
    --run-name "$run" --model-name "$model" \
    --config-path "$rd/summary.json" \
    --judge-dir "$rd/judge" \
    --judge-template-dir "$TEMPLATE" \
    --container-name "$cont" \
    --summary-path "$rd/summary.json" \
    --master-sync-script "" \
    --poll-interval 30 \
    >> "$rd/logs/detached_eval.log" 2>&1 &
  echo "  launched worker pid $! container $cont"
  sleep 5
done

echo "All 5 workers launched."
