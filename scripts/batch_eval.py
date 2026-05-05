#!/usr/bin/env python3
"""Batch evaluation launcher for CodeEditorBench.

Scans benchmark_runs/ for runs where generation is complete but evaluation
hasn't finished, then launches up to --max-concurrent (default 24) Docker
eval workers in parallel with staggered starts to avoid I/O storms.

Retries failed runs up to --max-retries times.  After each worker finishes
(success or fail), its Docker container is stopped and removed to free the
slot for the next queued run.

Usage:
    python scripts/batch_eval.py                       # full batch, 24 concurrent
    python scripts/batch_eval.py --dry-run             # preview only
    python scripts/batch_eval.py --max-concurrent 12
    python scripts/batch_eval.py --show-matrix         # print result matrix before & after
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = REPO_ROOT / "benchmark_runs"
EVAL_WORKER = REPO_ROOT / "scripts" / "detached_eval_worker.py"
SHOW_MATRIX = REPO_ROOT / "show_result_matrix.py"

EVAL_ELIGIBLE_STATUSES = {"generation_complete", "eval_failed"}
DEFAULT_MAX_WAIT = 4 * 60 * 60
DEFAULT_STALL_TIMEOUT = 30 * 60

_print_lock = threading.Lock()
_launch_lock = threading.Lock()
_launch_count = 0


def tprint(msg):
    with _print_lock:
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", flush=True)


def parse_args():
    parser = argparse.ArgumentParser(description="Batch-launch CodeEditorBench eval workers.")
    parser.add_argument("--max-concurrent", type=int, default=24,
                        help="Maximum eval Docker containers running at once (default: 24)")
    parser.add_argument("--max-wait-seconds", type=int, default=DEFAULT_MAX_WAIT,
                        help="Per-run max wall-clock wait for eval (default: 4h)")
    parser.add_argument("--stall-timeout-seconds", type=int, default=DEFAULT_STALL_TIMEOUT,
                        help="Per-run stall timeout (default: 30m)")
    parser.add_argument("--max-retries", type=int, default=2,
                        help="Retry failed runs up to N times (default: 2)")
    parser.add_argument("--stagger-seconds", type=int, default=15,
                        help="Delay between launching successive workers (default: 15s)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be launched without starting anything")
    parser.add_argument("--show-matrix", action="store_true",
                        help="Run show_result_matrix.py before and after evaluation")
    parser.add_argument("--filter", type=str, default=None,
                        help="Only eval runs whose name contains this substring")
    return parser.parse_args()


def load_summary(run_dir):
    path = run_dir / "summary.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def default_container_name(run_name):
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", run_name).strip("-_.").lower() or "run"
    digest = hashlib.sha1(run_name.encode("utf-8")).hexdigest()[:10]
    return f"codeeditorbench_judge_{safe[:40]}_{digest}"


def find_eval_candidates(name_filter=None):
    candidates = []
    for entry in sorted(BENCHMARK_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        if name_filter and name_filter not in entry.name:
            continue
        summary = load_summary(entry)
        if summary is None:
            continue
        status = summary.get("status", "")
        if status not in EVAL_ELIGIBLE_STATUSES:
            continue
        candidates.append((entry, summary))
    return candidates


def count_our_containers():
    try:
        r = subprocess.run(
            ["docker", "ps", "--filter", "name=codeeditorbench_judge", "-q"],
            capture_output=True, text=True, check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            return len(r.stdout.strip().splitlines())
    except Exception:
        pass
    return 0


def cleanup_container(container_name):
    subprocess.run(["docker", "stop", container_name],
                   capture_output=True, check=False, timeout=120)
    subprocess.run(["docker", "rm", "-f", container_name],
                   capture_output=True, check=False, timeout=60)


def cleanup_all_stopped():
    """Remove all stopped codeeditorbench_judge containers to avoid name conflicts."""
    try:
        r = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=codeeditorbench_judge",
             "--filter", "status=exited", "--format", "{{.Names}}"],
            capture_output=True, text=True, check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            names = r.stdout.strip().splitlines()
            for name in names:
                subprocess.run(["docker", "rm", "-f", name],
                               capture_output=True, check=False, timeout=60)
            return len(names)
    except Exception:
        pass
    return 0


def resolve_container_name(summary):
    """Get or generate a valid container name for the run."""
    name = summary.get("container_name")
    if name and name != "codeeditorbench_judge":
        return name
    return default_container_name(summary["run_name"])


def run_eval_worker(run_dir, summary, max_wait, stall_timeout, stagger_seconds):
    """Run detached_eval_worker.py synchronously for one run.

    Stagger start to avoid I/O storm, then after completion the container
    is stopped and removed.

    Returns (run_name, success, message).
    """
    global _launch_count

    run_name = summary["run_name"]
    container_name = resolve_container_name(summary)
    summary_path = run_dir / "summary.json"
    judge_dir = summary.get("judge_dir", str(run_dir / "judge"))
    judge_template_dir = summary.get("judge_template_dir",
                                      str(REPO_ROOT / "evaluation" / "judge"))
    model_name = summary.get("model_name", run_name)
    config_path = summary.get("config_path", "")

    with _launch_lock:
        seq = _launch_count
        _launch_count += 1

    stagger_delay = seq * stagger_seconds
    if stagger_delay > 0:
        tprint(f"QUEUE {run_name} (will start in {stagger_delay}s)")
        time.sleep(stagger_delay)

    cleanup_container(container_name)

    log_dir = run_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "detached_eval.log"

    cmd = [
        sys.executable,
        str(EVAL_WORKER),
        "--run-name", run_name,
        "--model-name", model_name,
        "--config-path", config_path,
        "--container-name", container_name,
        "--judge-dir", judge_dir,
        "--judge-template-dir", judge_template_dir,
        "--summary-path", str(summary_path),
        "--max-wait-seconds", str(max_wait),
        "--stall-timeout-seconds", str(stall_timeout),
    ]

    tprint(f"START {run_name}  (container={container_name})")
    start = time.monotonic()
    try:
        with log_path.open("w") as lf:
            proc = subprocess.run(
                cmd, cwd=str(REPO_ROOT),
                stdout=lf, stderr=subprocess.STDOUT,
                timeout=max_wait + 600,
            )
        elapsed = time.monotonic() - start
        if proc.returncode == 0:
            return (run_name, True, f"completed in {elapsed/60:.1f}m")
        return (run_name, False, f"exit code {proc.returncode} after {elapsed/60:.1f}m "
                                  f"(log: {log_path})")
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return (run_name, False, f"hard timeout after {elapsed/60:.1f}m")
    except Exception as exc:
        return (run_name, False, str(exc))
    finally:
        try:
            cleanup_container(container_name)
        except Exception:
            pass


def run_wave(candidates, max_concurrent, max_wait, stall_timeout, stagger_seconds):
    """Run one wave of evals. Returns (succeeded, failed_list)."""
    global _launch_count
    _launch_count = 0

    succeeded = 0
    failed_list = []

    with ThreadPoolExecutor(max_workers=max_concurrent) as pool:
        futures = {}
        for run_dir, summary in candidates:
            f = pool.submit(run_eval_worker, run_dir, summary,
                            max_wait, stall_timeout, stagger_seconds)
            futures[f] = (run_dir, summary)

        for f in as_completed(futures):
            run_name, success, message = f.result()
            run_dir, summary = futures[f]
            if success:
                succeeded += 1
                tprint(f"OK   {run_name}: {message}")
            else:
                failed_list.append((run_dir, summary, message))
                tprint(f"FAIL {run_name}: {message}")
            total_done = succeeded + len(failed_list)
            tprint(f"Progress: {total_done}/{len(candidates)} "
                   f"({succeeded} ok, {len(failed_list)} failed)")

    return succeeded, failed_list


def main():
    args = parse_args()

    if args.show_matrix:
        print("=" * 80)
        print("Current result matrix (BEFORE eval):")
        print("=" * 80)
        subprocess.run([sys.executable, str(SHOW_MATRIX)], cwd=str(REPO_ROOT))
        print()

    candidates = find_eval_candidates(args.filter)
    if not candidates:
        print("No runs need evaluation. All done!")
        return

    print(f"Found {len(candidates)} runs needing evaluation:")
    for run_dir, summary in candidates:
        status = summary.get("status", "?")
        cname = resolve_container_name(summary)
        print(f"  {run_dir.name:65s} [{status}]  -> {cname}")
    print()

    removed = cleanup_all_stopped()
    if removed:
        tprint(f"Pre-cleaned {removed} stopped codeeditorbench containers")

    existing = count_our_containers()
    effective = max(1, args.max_concurrent - existing)
    if existing > 0:
        tprint(f"{existing} CodeEditorBench containers already running; "
               f"concurrency capped at {effective}")
    print()

    if args.dry_run:
        print("DRY RUN — nothing launched.")
        return

    grand_ok = 0
    permanently_failed = []

    tprint(f"=== WAVE 1/{1 + args.max_retries}: "
           f"{len(candidates)} runs, {effective} concurrent, "
           f"{args.stagger_seconds}s stagger ===")
    ok, failed = run_wave(candidates, effective, args.max_wait_seconds,
                          args.stall_timeout_seconds, args.stagger_seconds)
    grand_ok += ok

    for retry in range(1, args.max_retries + 1):
        if not failed:
            break

        tprint(f"Cleaning up before retry wave {retry + 1}...")
        cleanup_all_stopped()
        time.sleep(30)

        retry_candidates = []
        for run_dir, summary, _msg in failed:
            fresh = load_summary(run_dir)
            if fresh and fresh.get("status") == "eval_complete":
                grand_ok += 1
                tprint(f"SKIP {run_dir.name}: already eval_complete on recheck")
                continue
            retry_candidates.append((run_dir, fresh or summary))

        if not retry_candidates:
            break

        effective = max(1, args.max_concurrent - count_our_containers())
        tprint(f"=== WAVE {retry + 1}/{1 + args.max_retries}: "
               f"{len(retry_candidates)} retries, {effective} concurrent ===")
        ok, failed = run_wave(retry_candidates, effective,
                              args.max_wait_seconds, args.stall_timeout_seconds,
                              args.stagger_seconds)
        grand_ok += ok

    for _rd, _s, msg in failed:
        permanently_failed.append((_s.get("run_name", "?"), msg))

    remaining = find_eval_candidates(args.filter)
    if remaining and not permanently_failed:
        tprint(f"Post-check found {len(remaining)} still not done — final wave")
        cleanup_all_stopped()
        effective = max(1, args.max_concurrent - count_our_containers())
        ok, failed = run_wave(remaining, effective,
                              args.max_wait_seconds, args.stall_timeout_seconds,
                              args.stagger_seconds)
        grand_ok += ok
        for _rd, _s, msg in failed:
            permanently_failed.append((_s.get("run_name", "?"), msg))

    grand_fail = len(permanently_failed)

    print()
    print("=" * 80)
    total = grand_ok + grand_fail
    print(f"BATCH EVAL DONE: {grand_ok} succeeded, {grand_fail} failed "
          f"(out of {total} attempted)")
    print("=" * 80)

    if permanently_failed:
        print("\nPermanently failed runs:")
        for name, msg in permanently_failed:
            print(f"  {name}: {msg}")

    if args.show_matrix or grand_ok > 0:
        print()
        print("=" * 80)
        print("Final result matrix:")
        print("=" * 80)
        subprocess.run([sys.executable, str(SHOW_MATRIX)], cwd=str(REPO_ROOT))


if __name__ == "__main__":
    main()
