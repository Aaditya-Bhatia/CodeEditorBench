#!/usr/bin/env python3
"""
Sequentially re-run 10 failed CodeEditorBench models on slot1.
Gates each new run on: total running eval containers < MAX_CONTAINERS.
Run in a screen/tmux session — it will run unsupervised until done.
"""

import subprocess
import sys
import time
from datetime import datetime

import os
from pathlib import Path
_PROJECTS_ROOT = Path(os.environ.get("PROJECTS_ROOT", str(Path(__file__).resolve().parent.parent.parent)))
def _find_master_root() -> Path:
    for name in ("Master_VLLM", "Master-Benchmarking-Orchestrator"):
        candidate = _PROJECTS_ROOT / name
        if candidate.is_dir():
            return candidate
    return _PROJECTS_ROOT / "Master_VLLM"
MASTER_VLLM = str(_find_master_root() / "master_vllm.py")
NOTIFY_SCRIPT = str(_PROJECTS_ROOT / "notify_telegram.py")
MAX_CONTAINERS = 5
POLL_INTERVAL = 60  # seconds between container-count checks

MODELS = [
    "llama-3.2-3b-baseline",
    "qwen2.5-3b-baseline",
    "qwen2.5-coder-3b-instruct-baseline",
    "starcoder2-3b-baseline",
    "qwen2.5-coder-3b-instruct-lora-3b-code-edit-clean-2026-04-03-21-23-10",
    "qwen2.5-coder-7b-lora-7b-code-edit-dirty-10k-2026-04-08-19-35-19",
    "qwen2.5-coder-7b-lora-7b-code-edit-dirty-2026-04-03-22-27-41",
    "qwen2.5-coder-7b-lora-7b-code-edit-unclean74k-2026-04-07-19-17-23",
    "qwen3-14b-base-lora-14b-qwen3-code-edit-clean-2026-04-08-02-49-46",
    "starcoder2-15b-lora-15b-starcoder2-code-edit-unclean74k-2026-04-09-01-47-56",
]


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def count_eval_containers() -> int:
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=False,
    )
    return sum(
        1 for name in result.stdout.splitlines()
        if "codeeditorbench_judge" in name or "ceb_judge" in name
    )


def notify(msg: str) -> None:
    subprocess.run([sys.executable, NOTIFY_SCRIPT, msg], check=False)


def wait_for_capacity() -> int:
    while True:
        n = count_eval_containers()
        if n < MAX_CONTAINERS:
            return n
        log(f"  {n} eval containers running (limit {MAX_CONTAINERS}), waiting {POLL_INTERVAL}s ...")
        time.sleep(POLL_INTERVAL)


def run_model(model_id: str) -> bool:
    result = subprocess.run(
        [
            sys.executable, MASTER_VLLM, "run",
            "--slots", "slot1",
            "--no-rebuild",
            "--models", model_id,
        ],
        check=False,
    )
    return result.returncode == 0


def main() -> None:
    log(f"Starting re-run of {len(MODELS)} models on slot1 (max {MAX_CONTAINERS} concurrent eval containers)")
    notify(f"[CodeEditorBench] Re-run starting: {len(MODELS)} failed models queued on slot1")

    failures = []
    for i, model_id in enumerate(MODELS, 1):
        log(f"--- [{i}/{len(MODELS)}] {model_id} ---")
        n = wait_for_capacity()
        log(f"[{i}/{len(MODELS)}] {n} containers running — launching {model_id}")
        ok = run_model(model_id)
        if ok:
            log(f"[{i}/{len(MODELS)}] Generation+eval-launch OK: {model_id}")
        else:
            log(f"[{i}/{len(MODELS)}] FAILED (master_vllm non-zero exit): {model_id}")
            failures.append(model_id)

    log("All models submitted. Waiting for remaining eval containers to finish ...")
    while True:
        n = count_eval_containers()
        if n == 0:
            break
        log(f"  {n} eval containers still running, checking again in {POLL_INTERVAL}s ...")
        time.sleep(POLL_INTERVAL)

    if failures:
        msg = (
            f"[CodeEditorBench] Re-run complete — {len(failures)}/{len(MODELS)} generation failures: "
            + ", ".join(failures)
        )
    else:
        msg = f"[CodeEditorBench] Re-run complete — all {len(MODELS)} models generated and eval launched successfully."
    log(msg)
    notify(msg)


if __name__ == "__main__":
    main()
