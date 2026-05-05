#!/usr/bin/env python3
"""Distributed CodeEditorBench eval across multiple servers.

Run the SAME command on every server (lux-3-cyber-01 .. lux-3-cyber-10):
    python scripts/distributed_eval.py

Servers coordinate via a shared JSONL assignment file
(`benchmark_runs/eval_assignments.jsonl`) protected by a separate lock file.
Each server claims up to --max-concurrent runs at a time, evaluates
them via `scripts/detached_eval_worker.py`, and updates the assignments.

One-time setup (run on any server):
    python scripts/distributed_eval.py --save-image
    python scripts/distributed_eval.py --generate-assignments

Preview what this server would do:
    python scripts/distributed_eval.py --dry-run
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import socket
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
ASSIGNMENTS = BENCHMARK_DIR / "eval_assignments.jsonl"
ASSIGNMENTS_LOCK = BENCHMARK_DIR / ".eval_assignments.lock"

DOCKER_IMAGE = "xliudg/code_editor_bench:latest"
SHARED_IMAGE_DIR = Path("/shared_workspace_mfs/aadi/docker_images")
SHARED_IMAGE_TAR = SHARED_IMAGE_DIR / "code_editor_bench.tar.gz"

EVAL_ELIGIBLE_STATUSES = {"generation_complete", "eval_failed"}
DEFAULT_MAX_WAIT = 4 * 60 * 60
DEFAULT_STALL_TIMEOUT = 30 * 60
DEFAULT_RECLAIM_AFTER = DEFAULT_MAX_WAIT + 30 * 60

_print_lock = threading.Lock()
_active_lock = threading.Lock()
_active_workers = {}
_shutdown_event = threading.Event()


def tprint(msg):
    with _print_lock:
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", flush=True)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def get_hostname():
    h = socket.gethostname()
    return h.split(".")[0]


def host_short(hostname):
    m = re.search(r"(\d+)$", hostname)
    return m.group(1) if m else hostname[-3:]


# ---------- Docker image management ----------

def image_exists_locally():
    result = subprocess.run(
        ["docker", "image", "inspect", DOCKER_IMAGE],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def save_image():
    SHARED_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SHARED_IMAGE_TAR.with_suffix(".tar.gz.tmp")
    tprint(f"Saving {DOCKER_IMAGE} -> {SHARED_IMAGE_TAR}")
    if not image_exists_locally():
        tprint(f"Image not present locally; pulling first")
        subprocess.run(["docker", "pull", DOCKER_IMAGE], check=True)
    with tmp.open("wb") as handle:
        save = subprocess.Popen(["docker", "save", DOCKER_IMAGE], stdout=subprocess.PIPE)
        gz = subprocess.Popen(["gzip", "-1"], stdin=save.stdout, stdout=handle)
        save.stdout.close()
        rc = gz.wait()
        save.wait()
    if rc != 0:
        raise RuntimeError("docker save | gzip failed")
    tmp.rename(SHARED_IMAGE_TAR)
    tprint(f"Saved ({SHARED_IMAGE_TAR.stat().st_size / 1e9:.1f} GB)")


def ensure_image_loaded():
    if image_exists_locally():
        return
    if not SHARED_IMAGE_TAR.exists():
        tprint(f"WARNING: image missing locally AND {SHARED_IMAGE_TAR} not found")
        tprint(f"Falling back to docker pull {DOCKER_IMAGE}")
        subprocess.run(["docker", "pull", DOCKER_IMAGE], check=True)
        return
    tprint(f"Loading docker image from {SHARED_IMAGE_TAR} (one-time per server)...")
    proc = subprocess.Popen(["gunzip", "-c", str(SHARED_IMAGE_TAR)], stdout=subprocess.PIPE)
    subprocess.run(["docker", "load"], stdin=proc.stdout, check=True)
    proc.wait()
    tprint("Image loaded.")


# ---------- Assignment file (locked JSONL) ----------

def _read_assignments():
    if not ASSIGNMENTS.exists():
        return []
    with ASSIGNMENTS.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _write_assignments(rows):
    tmp_path = ASSIGNMENTS.with_name(f".{ASSIGNMENTS.name}.{os.getpid()}.{time.time_ns()}.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, ASSIGNMENTS)
    dir_fd = os.open(str(ASSIGNMENTS.parent), os.O_DIRECTORY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def with_lock(fn):
    """Execute fn(rows) under an exclusive lock on a separate lockfile."""
    ASSIGNMENTS.parent.mkdir(parents=True, exist_ok=True)
    ASSIGNMENTS.touch(exist_ok=True)
    ASSIGNMENTS_LOCK.touch(exist_ok=True)
    with ASSIGNMENTS_LOCK.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            rows = _read_assignments()
            new_rows, result = fn(rows)
            if new_rows is not None:
                _write_assignments(new_rows)
            return result
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# ---------- Assignment generation ----------

def load_summary(run_dir):
    path = run_dir / "summary.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def find_eligible_runs():
    eligible = []
    for entry in sorted(BENCHMARK_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        summary = load_summary(entry)
        if summary is None:
            continue
        if summary.get("status") in EVAL_ELIGIBLE_STATUSES:
            eligible.append((entry, summary))
    return eligible


def generate_assignments(force=False):
    eligible = find_eligible_runs()

    def _fn(rows):
        existing = {row["run_name"] for row in rows}
        added = 0
        new_rows = list(rows)
        for run_dir, summary in eligible:
            run_name = summary["run_name"]
            if run_name in existing and not force:
                continue
            if force:
                new_rows = [row for row in new_rows if row["run_name"] != run_name]
            new_rows.append({
                "run_name": run_name,
                "run_dir": str(run_dir),
                "server": None,
                "status": "pending",
                "claimed_at": None,
                "completed_at": None,
                "attempts": 0,
                "error": None,
            })
            added += 1
        return new_rows, added

    added = with_lock(_fn)
    tprint(f"Assignments: added/refreshed {added}, total eligible runs {len(eligible)}")


# ---------- Claiming & updating ----------

def _summary_recovery_state(summary):
    status = summary.get("status")
    if status == "eval_complete":
        return {
            "status": "done",
            "completed_at": summary.get("eval_completed_at_utc") or now_iso(),
            "error": None,
        }
    if status == "eval_failed":
        return {
            "status": "failed",
            "completed_at": summary.get("eval_failed_at_utc") or now_iso(),
            "error": summary.get("error"),
        }
    return None


def reconcile_assignments(stale_after_seconds=DEFAULT_RECLAIM_AFTER, target_server=None):
    def _fn(rows):
        changed = False
        stats = {"done": 0, "failed": 0, "requeued": 0}
        now = datetime.now(timezone.utc)
        for row in rows:
            if target_server and row.get("server") != target_server:
                continue
            summary = load_summary(Path(row["run_dir"])) or {}
            recovered = _summary_recovery_state(summary)
            if recovered and row["status"] in {"claimed", "running"}:
                row.update(recovered)
                if recovered["status"] == "failed":
                    row["attempts"] = row.get("attempts", 0) + 1
                    stats["failed"] += 1
                else:
                    stats["done"] += 1
                changed = True
                continue
            if row["status"] not in {"claimed", "running"}:
                continue
            claimed_at = parse_iso(row.get("claimed_at"))
            if claimed_at is None:
                continue
            age_seconds = (now - claimed_at).total_seconds()
            if age_seconds < stale_after_seconds:
                continue
            row["status"] = "pending"
            row["server"] = None
            row["claimed_at"] = None
            row["completed_at"] = None
            row["error"] = f"stale_assignment_reclaimed_after_{int(age_seconds)}s"
            stats["requeued"] += 1
            changed = True
        return (rows if changed else None), stats

    return with_lock(_fn)


def release_server_assignments(server, reason="released_by_operator"):
    def _fn(rows):
        changed = False
        stats = {"done": 0, "failed": 0, "requeued": 0}
        for row in rows:
            if row.get("server") != server or row["status"] not in {"claimed", "running"}:
                continue
            summary = load_summary(Path(row["run_dir"])) or {}
            recovered = _summary_recovery_state(summary)
            if recovered:
                row.update(recovered)
                if recovered["status"] == "failed":
                    row["attempts"] = row.get("attempts", 0) + 1
                    stats["failed"] += 1
                else:
                    stats["done"] += 1
            else:
                row["status"] = "pending"
                row["server"] = None
                row["claimed_at"] = None
                row["completed_at"] = None
                row["error"] = reason
                stats["requeued"] += 1
            changed = True
        return (rows if changed else None), stats

    return with_lock(_fn)


def claim_work(hostname, n, include_failed_retry=True, max_attempts=3):
    def _fn(rows):
        claimed = []
        changed = False
        for preferred_status in ("pending", "failed"):
            for row in rows:
                if len(claimed) >= n:
                    break
                if preferred_status == "pending":
                    if row["status"] != "pending":
                        continue
                else:
                    if not include_failed_retry:
                        break
                    if row["status"] != "failed" or row.get("attempts", 0) >= max_attempts:
                        continue
                row["server"] = hostname
                row["status"] = "claimed"
                row["claimed_at"] = now_iso()
                snapshot = dict(row)
                snapshot["claimed_from_status"] = preferred_status
                claimed.append(snapshot)
                changed = True
        return (rows if changed else None), claimed

    return with_lock(_fn)


def update_assignment(run_name, **fields):
    def _fn(rows):
        for row in rows:
            if row["run_name"] == run_name:
                row.update(fields)
                return rows, True
        return None, False

    return with_lock(_fn)


# ---------- Container naming & cleanup ----------

def container_name_for(run_name, hostname):
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", run_name).strip("-_.").lower() or "run"
    digest = hashlib.sha1(run_name.encode("utf-8")).hexdigest()[:8]
    return f"ceb_judge_{host_short(hostname)}_{safe[:30]}_{digest}"


def cleanup_container(name):
    subprocess.run(["docker", "stop", name], capture_output=True, check=False, timeout=120)
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False, timeout=60)


# ---------- Worker ----------

def _register_worker(run_name, proc, container_name):
    with _active_lock:
        _active_workers[run_name] = {"proc": proc, "container_name": container_name}


def _unregister_worker(run_name):
    with _active_lock:
        _active_workers.pop(run_name, None)


def _terminate_process_tree(proc):
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=15)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except Exception:
        proc.kill()


def _handle_shutdown(signum, _frame):
    if _shutdown_event.is_set():
        return
    _shutdown_event.set()
    tprint(f"Shutdown requested via signal {signum}; terminating active eval workers")
    with _active_lock:
        active = list(_active_workers.values())
    for entry in active:
        _terminate_process_tree(entry["proc"])
        cleanup_container(entry["container_name"])


def eval_one_run(row, hostname, max_wait, stall_timeout, stagger_delay):
    run_name = row["run_name"]
    run_dir = Path(row["run_dir"])

    if stagger_delay > 0 and _shutdown_event.wait(stagger_delay):
        update_assignment(
            run_name,
            status="pending",
            server=None,
            claimed_at=None,
            completed_at=None,
            error="interrupted_by_shutdown",
        )
        return False
    if _shutdown_event.is_set():
        update_assignment(
            run_name,
            status="pending",
            server=None,
            claimed_at=None,
            completed_at=None,
            error="interrupted_by_shutdown",
        )
        return False

    update_assignment(run_name, status="running")
    summary = load_summary(run_dir) or {}
    container_name = container_name_for(run_name, hostname)
    summary_path = run_dir / "summary.json"
    judge_dir = summary.get("judge_dir", str(run_dir / "judge"))
    judge_template_dir = summary.get("judge_template_dir", str(REPO_ROOT / "evaluation" / "judge"))
    model_name = summary.get("model_name", run_name)
    config_path = summary.get("config_path", "")

    cleanup_container(container_name)

    log_dir = run_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"distributed_eval_{host_short(hostname)}.log"

    cmd = [
        sys.executable, str(EVAL_WORKER),
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
    rc = -1
    err = None
    try:
        with log_path.open("w", encoding="utf-8") as log_fh:
            proc = subprocess.Popen(
                cmd,
                cwd=str(REPO_ROOT),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            _register_worker(run_name, proc, container_name)
            try:
                rc = proc.wait(timeout=max_wait + 600)
            except subprocess.TimeoutExpired:
                err = "hard timeout"
                _terminate_process_tree(proc)
                try:
                    rc = proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    rc = -1
    except Exception as exc:
        err = str(exc)
    finally:
        _unregister_worker(run_name)
        cleanup_container(container_name)

    elapsed = time.monotonic() - start
    if _shutdown_event.is_set():
        update_assignment(
            run_name,
            status="pending",
            server=None,
            claimed_at=None,
            completed_at=None,
            error="interrupted_by_shutdown",
        )
        tprint(f"STOP {run_name}  ({elapsed / 60:.1f}m)")
        return False

    success = (rc == 0 and err is None)
    if success:
        update_assignment(run_name, status="done", completed_at=now_iso(), error=None)
        tprint(f"OK   {run_name}  ({elapsed / 60:.1f}m)")
        return True

    message = err or f"exit {rc}"

    def _bump(rows):
        for assignment in rows:
            if assignment["run_name"] == run_name:
                assignment["status"] = "failed"
                assignment["completed_at"] = now_iso()
                assignment["error"] = message
                assignment["attempts"] = assignment.get("attempts", 0) + 1
                return rows, None
        return None, None

    with_lock(_bump)
    tprint(f"FAIL {run_name}: {message}  ({elapsed / 60:.1f}m, log: {log_path})")
    return False


# ---------- Status display ----------

def print_status_summary():
    rows = with_lock(lambda rows: (None, rows))
    if not rows:
        print("(no assignments)")
        return
    by_server = {}
    by_status = {}
    for row in rows:
        server = row.get("server") or "—"
        status = row["status"]
        by_server.setdefault(server, {}).setdefault(status, 0)
        by_server[server][status] += 1
        by_status[status] = by_status.get(status, 0) + 1
    print(f"Total assignments: {len(rows)}")
    print(f"By status: {by_status}")
    print("By server:")
    for server in sorted(by_server):
        print(f"  {server:25s} {by_server[server]}")


# ---------- Main ----------

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-concurrent", type=int, default=4)
    parser.add_argument("--max-wait-seconds", type=int, default=DEFAULT_MAX_WAIT)
    parser.add_argument("--stall-timeout-seconds", type=int, default=DEFAULT_STALL_TIMEOUT)
    parser.add_argument("--reclaim-after-seconds", type=int, default=DEFAULT_RECLAIM_AFTER)
    parser.add_argument("--stagger-seconds", type=int, default=15)
    parser.add_argument("--max-attempts", type=int, default=3,
                        help="Retry a failed run up to N total attempts")
    parser.add_argument("--save-image", action="store_true",
                        help="Save the docker image to the shared disk, then exit")
    parser.add_argument("--generate-assignments", action="store_true",
                        help="Generate / refresh the assignment file, then exit")
    parser.add_argument("--regenerate", action="store_true",
                        help="With --generate-assignments, replace existing rows for eligible runs")
    parser.add_argument("--status", action="store_true",
                        help="Print assignment status summary and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what this server would claim, don't run")
    parser.add_argument("--hostname", type=str, default=None,
                        help="Override auto-detected hostname")
    parser.add_argument("--release-server", type=str, default="",
                        help="Release claimed/running rows for a specific server, then exit")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.save_image:
        save_image()
        return
    if args.status:
        print_status_summary()
        return
    if args.generate_assignments:
        generate_assignments(force=args.regenerate)
        print_status_summary()
        return
    if args.release_server:
        stats = release_server_assignments(args.release_server)
        tprint(f"Released assignments for {args.release_server}: {stats}")
        print_status_summary()
        return

    hostname = args.hostname or get_hostname()
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)
    tprint(f"hostname={hostname}  short={host_short(hostname)}")

    if not ASSIGNMENTS.exists() or ASSIGNMENTS.stat().st_size == 0:
        tprint("Assignment file missing — generating")
        generate_assignments(force=False)

    ensure_image_loaded()
    reconciled = reconcile_assignments(stale_after_seconds=args.reclaim_after_seconds)
    if any(reconciled.values()):
        tprint(f"Reconciled assignments: {reconciled}")

    if args.dry_run:
        claimed = claim_work(hostname, args.max_concurrent, max_attempts=args.max_attempts)
        print(f"[DRY RUN] would claim {len(claimed)} runs:")
        for row in claimed:
            print(f"  {row['run_name']}")

        def _release(rows):
            claimed_map = {row["run_name"]: row.get("claimed_from_status", "pending") for row in claimed}
            for row in rows:
                if row["run_name"] not in claimed_map:
                    continue
                row["status"] = claimed_map[row["run_name"]]
                row["server"] = None
                row["claimed_at"] = None
            return rows, None

        with_lock(_release)
        return

    total_done = 0
    total_fail = 0
    while not _shutdown_event.is_set():
        reconciled = reconcile_assignments(stale_after_seconds=args.reclaim_after_seconds)
        if any(reconciled.values()):
            tprint(f"Reconciled assignments: {reconciled}")
        claimed = claim_work(hostname, args.max_concurrent, max_attempts=args.max_attempts)
        if not claimed:
            tprint("No more pending work — exiting")
            break

        tprint(f"Claimed {len(claimed)} runs:")
        for row in claimed:
            tprint(f"  queued: {row['run_name']}")

        with ThreadPoolExecutor(max_workers=len(claimed)) as pool:
            futures = []
            for index, row in enumerate(claimed):
                delay = index * args.stagger_seconds
                futures.append(pool.submit(
                    eval_one_run,
                    row,
                    hostname,
                    args.max_wait_seconds,
                    args.stall_timeout_seconds,
                    delay,
                ))
            for future in as_completed(futures):
                try:
                    success = future.result()
                except Exception as exc:
                    tprint(f"[{hostname}] worker exception: {exc}")
                    success = False
                if success:
                    total_done += 1
                else:
                    total_fail += 1
                tprint(f"[{hostname}] progress: {total_done} done, {total_fail} failed")

    print()
    tprint(f"DONE on {hostname}: {total_done} succeeded, {total_fail} failed")
    print_status_summary()


if __name__ == "__main__":
    main()
