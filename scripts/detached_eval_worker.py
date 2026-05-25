#!/usr/bin/env python3

import argparse
import fcntl
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

INITIAL_MYSQL_READY_TIMEOUT_SECONDS = 60
MYSQL_READY_TIMEOUT_SECONDS = 120
MYSQL_READY_POLL_SECONDS = 2
_PROJECTS_ROOT = Path(os.environ.get("PROJECTS_ROOT", str(Path(__file__).resolve().parent.parent.parent)))
def _find_master_root() -> Path:
    for name in ("Master_VLLM", "Master-Benchmarking-Orchestrator"):
        candidate = _PROJECTS_ROOT / name
        if candidate.is_dir():
            return candidate
    return _PROJECTS_ROOT / "Master_VLLM"
_MASTER_DIR = _find_master_root()
DEFAULT_MASTER_SYNC_SCRIPT = str(_MASTER_DIR / "master_vllm.py")
DEFAULT_MASTER_MANIFEST = str(_MASTER_DIR / "manifests" / "models_manifest.json")


def parse_args():
    parser = argparse.ArgumentParser(description="Detached CodeEditorBench Docker eval worker.")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--config-path", required=True)
    parser.add_argument("--judge-dir", required=True)
    parser.add_argument("--judge-template-dir", default="")
    parser.add_argument("--container-name", default=os.environ.get("CONTAINER_NAME", "codeeditorbench_judge"))
    parser.add_argument("--notify-script", default="")
    parser.add_argument("--master-sync-script", default=DEFAULT_MASTER_SYNC_SCRIPT)
    parser.add_argument("--master-manifest", default=DEFAULT_MASTER_MANIFEST)
    parser.add_argument("--summary-path", default="")
    parser.add_argument("--poll-interval", type=int, default=60)
    parser.add_argument("--max-wait-seconds", type=int, default=4 * 60 * 60)
    parser.add_argument("--stall-timeout-seconds", type=int, default=30 * 60)
    parser.add_argument(
        "--force-resolve-max-pending",
        type=int,
        default=150,
        help="At stall_timeout OR max_wait, if pending<=this, force-mark stuck rows TLE and "
             "finalize instead of raising. HUSTOJ has 50 judge slots so the floor is 50; "
             "default 150 absorbs queue stragglers (~1.5%% of a 10k dataset).",
    )
    return parser.parse_args()


def run(cmd, cwd=None, capture=False, check=True, env=None):
    kwargs = {"cwd": cwd, "check": check, "text": True}
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    if env is not None:
        kwargs["env"] = env
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, **kwargs)


def send_telegram(notify_script: str, message: str):
    if not notify_script or not os.path.exists(notify_script):
        return
    subprocess.run([sys.executable, notify_script, message], check=False)


def format_percent(value: object) -> Optional[str]:
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}%"
    return None


def benchmark_message(model_name: str, state: str, score: Optional[str] = None) -> str:
    parts = ["CodeEditorBench", model_name, state]
    if score:
        parts.append(score)
    return " | ".join(parts)


def sync_master(master_sync_script: str, master_manifest: str, summary_path: str) -> bool:
    if not master_sync_script or not os.path.exists(master_sync_script) or not summary_path:
        return False
    result = subprocess.run(
        [
            sys.executable,
            master_sync_script,
            "sync-codeeditorbench",
            "--manifest",
            master_manifest,
            "--summary-path",
            summary_path,
        ],
        check=False,
    )
    return result.returncode == 0


def update_summary(summary_path: str, **updates):
    if not summary_path:
        return
    path = Path(summary_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        raw = handle.read().strip()
        data = json.loads(raw) if raw else {}
        data.update(updates)
        tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        with tmp_path.open("w", encoding="utf-8") as tmp_handle:
            json.dump(data, tmp_handle, indent=2)
            tmp_handle.write("\n")
            tmp_handle.flush()
            os.fsync(tmp_handle.fileno())
        os.replace(tmp_path, path)
        dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_judge_config(container_name: str) -> Dict[str, str]:
    code = (
        "import json\n"
        "keys=('OJ_HOST_NAME','OJ_PORT_NUMBER','OJ_USER_NAME','OJ_PASSWORD','OJ_DB_NAME')\n"
        "vals={}\n"
        "for line in open('/home/judge/etc/judge.conf'):\n"
        "    line=line.strip()\n"
        "    if '=' in line and not line.startswith('#'):\n"
        "        k,v=line.split('=',1)\n"
        "        vals[k.strip()]=v.strip()\n"
        "print(json.dumps({key: vals.get(key, '') for key in keys}))\n"
    )
    return json.loads(docker_py(container_name, code))


def mysql_ready(container_name: str) -> bool:
    try:
        config = read_judge_config(container_name)
    except Exception:
        return False
    host = shlex.quote(config.get("OJ_HOST_NAME") or "127.0.0.1")
    port = shlex.quote(config.get("OJ_PORT_NUMBER") or "3306")
    user = shlex.quote(config.get("OJ_USER_NAME") or "root")
    password = shlex.quote(config.get("OJ_PASSWORD") or "")
    command = (
        f"MYSQL_PWD={password} mysqladmin --protocol=tcp ping "
        f"-h {host} -P {port} -u {user} --silent"
    )
    result = run(
        ["docker", "exec", container_name, "bash", "-lc", command],
        capture=True,
        check=False,
    )
    return result.returncode == 0


def wait_for_mysql(container_name: str, timeout: int = MYSQL_READY_TIMEOUT_SECONDS) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if mysql_ready(container_name):
            return True
        time.sleep(MYSQL_READY_POLL_SECONDS)
    return False


def repair_mysql(container_name: str):
    command = """
set -euo pipefail
mkdir -p /run/mysqld /var/run/mysqld
chown mysql:mysql /run/mysqld /var/run/mysqld || true
rm -f /run/mysqld/mysqld.sock.lock /run/mysqld/mysqlx.sock.lock
rm -f /var/run/mysqld/mysqld.sock.lock /var/run/mysqld/mysqlx.sock.lock
rm -f /run/mysqld/*.pid /var/run/mysqld/*.pid /run/mysql/*.pid /var/run/mysql/*.pid
rm -f /var/lib/mysql/*.pid
pkill -9 mysqld || true
service mysql restart || service mysql start || true
"""
    run(["docker", "exec", container_name, "bash", "-lc", command], check=False)


def ensure_container(repo_root: Path, judge_dir: Path, judge_template_dir: Optional[Path], container_name: str):
    container_env = {**os.environ, "CONTAINER_NAME": container_name}
    if judge_template_dir:
        container_env["SHARED_JUDGE_TEMPLATE"] = str(judge_template_dir)
    inspect = run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
        cwd=str(repo_root),
        capture=True,
        check=False,
    )
    if inspect.returncode != 0:
        run(["bash", "evaluation/run_judge_container.sh", str(judge_dir)], cwd=str(repo_root), env=container_env)
    elif inspect.stdout.strip() != "true":
        run(["docker", "start", container_name], cwd=str(repo_root))
    if wait_for_mysql(container_name, timeout=INITIAL_MYSQL_READY_TIMEOUT_SECONDS):
        return

    repair_mysql(container_name)
    if wait_for_mysql(container_name):
        return

    run(["docker", "rm", "-f", container_name], cwd=str(repo_root), check=False)
    run(["bash", "evaluation/run_judge_container.sh", str(judge_dir)], cwd=str(repo_root), env=container_env)
    if wait_for_mysql(container_name, timeout=INITIAL_MYSQL_READY_TIMEOUT_SECONDS):
        return
    repair_mysql(container_name)
    if wait_for_mysql(container_name):
        return

    raise RuntimeError(
        f"Judge container {container_name} is running but MySQL is not reachable after repair/recreate attempts"
    )


def docker_exec(container_name: str, command: str):
    run(["docker", "exec", container_name, "bash", "-lc", command])


def docker_py(container_name: str, code: str, retries: int = 5, delay: int = 15):
    for attempt in range(retries):
        result = run(
            ["docker", "exec", "-i", container_name, "python3", "-c", code],
            capture=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        if attempt < retries - 1:
            print(f"  docker_py attempt {attempt + 1}/{retries} failed (rc={result.returncode}), "
                  f"retrying in {delay}s...", flush=True)
            if result.stderr:
                print(f"  stderr: {result.stderr.strip()[:200]}", flush=True)
            repair_mysql(container_name)
            time.sleep(delay)
    result.check_returncode()
    return result.stdout.strip()


def fetch_model_id(container_name: str, run_name: str):
    code = (
        "import json, pymysql, re\n"
        "cfg='/home/judge/etc/judge.conf'\n"
        "vals={}\n"
        "for line in open(cfg):\n"
        "    if '=' in line and not line.strip().startswith('#'):\n"
        "        k,v=line.split('=',1); vals[k.strip()]=v.strip()\n"
        "conn=pymysql.connect(host=vals['OJ_HOST_NAME'], port=int(vals['OJ_PORT_NUMBER']), "
        "user=vals['OJ_USER_NAME'], password=vals['OJ_PASSWORD'], database=vals['OJ_DB_NAME'])\n"
        "cur=conn.cursor()\n"
        f"cur.execute(\"SELECT model_id FROM models WHERE model_name=%s ORDER BY model_id DESC LIMIT 1\", ({run_name!r},))\n"
        "row=cur.fetchone()\n"
        "print(row[0] if row else '')\n"
        "cur.close(); conn.close()\n"
    )
    output = docker_py(container_name, code)
    return int(output) if output else None


def fetch_status(container_name: str, model_id: int):
    code = (
        "import json, pymysql\n"
        "vals={}\n"
        "for line in open('/home/judge/etc/judge.conf'):\n"
        "    if '=' in line and not line.strip().startswith('#'):\n"
        "        k,v=line.split('=',1); vals[k.strip()]=v.strip()\n"
        "conn=pymysql.connect(host=vals['OJ_HOST_NAME'], port=int(vals['OJ_PORT_NUMBER']), "
        "user=vals['OJ_USER_NAME'], password=vals['OJ_PASSWORD'], database=vals['OJ_DB_NAME'])\n"
        "cur=conn.cursor()\n"
        f"cur.execute(\"SELECT COUNT(*), SUM(CASE WHEN result < 4 OR result = 14 THEN 1 ELSE 0 END), "
        f"SUM(CASE WHEN result IN (4,41,42,43) THEN 1 ELSE 0 END) FROM solution WHERE model_id=%s\", ({model_id},))\n"
        "row=cur.fetchone() or (0,0,0)\n"
        "total=int(row[0] or 0); pending=int(row[1] or 0); accepted=int(row[2] or 0)\n"
        "print(json.dumps({'total': total, 'pending': pending, 'accepted': accepted, 'resolved': total - pending}))\n"
        "cur.close(); conn.close()\n"
    )
    return json.loads(docker_py(container_name, code))


def fetch_judge_activity(container_name: str):
    code = (
        "import json, subprocess\n"
        "ps = subprocess.run(['ps', '-eo', 'cmd'], text=True, capture_output=True, check=True)\n"
        "cmds = [line.strip() for line in ps.stdout.splitlines() if line.strip()]\n"
        "watchdog = any(cmd == 'bash run_judge.sh' for cmd in cmds)\n"
        "judged = any(cmd == 'judged /home/judge' for cmd in cmds)\n"
        "judge_clients = sum(\n"
        "    cmd.startswith('/usr/bin/judge_client ')\n"
        "    or cmd.startswith('judge_client ')\n"
        "    or '/home/judge/src/core/judge_client/judge_client ' in cmd\n"
        "    for cmd in cmds\n"
        ")\n"
        "print(json.dumps({'watchdog': watchdog, 'judged': judged, 'judge_clients': judge_clients}))\n"
    )
    return json.loads(docker_py(container_name, code))


def normalize_pending_queue(container_name: str, model_id: int):
    code = (
        "import pymysql\n"
        "vals={}\n"
        "for line in open('/home/judge/etc/judge.conf'):\n"
        "    if '=' in line and not line.strip().startswith('#'):\n"
        "        k,v=line.split('=',1); vals[k.strip()]=v.strip()\n"
        "conn=pymysql.connect(host=vals['OJ_HOST_NAME'], port=int(vals['OJ_PORT_NUMBER']), "
        "user=vals['OJ_USER_NAME'], password=vals['OJ_PASSWORD'], database=vals['OJ_DB_NAME'])\n"
        "cur=conn.cursor()\n"
        f"cur.execute(\"UPDATE solution SET result=0 WHERE model_id=%s AND result IN (1,2,3,14)\", ({model_id},))\n"
        "conn.commit()\n"
        "print(cur.rowcount)\n"
        "cur.close(); conn.close()\n"
    )
    output = docker_py(container_name, code)
    return int(output) if output else 0


def force_resolve_pending(container_name: str, model_id: int, result_code: int = 7):
    # HUSTOJ has exactly 50 judge worker slots (run0..run49). When the queue
    # narrows to ~50 prompts, generations with non-terminating user code can
    # fill every slot; renormalize cycles just redispatch the same rows.
    # Force-mark surviving pending rows with a non-accepted terminal code
    # (default 7 = Time Limit Exceeded) so compute_metrics can finalize.
    code = (
        "import pymysql\n"
        "vals={}\n"
        "for line in open('/home/judge/etc/judge.conf'):\n"
        "    if '=' in line and not line.strip().startswith('#'):\n"
        "        k,v=line.split('=',1); vals[k.strip()]=v.strip()\n"
        "conn=pymysql.connect(host=vals['OJ_HOST_NAME'], port=int(vals['OJ_PORT_NUMBER']), "
        "user=vals['OJ_USER_NAME'], password=vals['OJ_PASSWORD'], database=vals['OJ_DB_NAME'])\n"
        "cur=conn.cursor()\n"
        f"cur.execute(\"UPDATE solution SET result=%s WHERE model_id=%s AND (result < 4 OR result = 14)\", ({result_code}, {model_id}))\n"
        "conn.commit()\n"
        "print(cur.rowcount)\n"
        "cur.close(); conn.close()\n"
    )
    output = docker_py(container_name, code)
    return int(output) if output else 0


def reset_judge_runtime_state(container_name: str):
    command = r"""
set -euo pipefail
pkill -f '^bash run_judge.sh$' || true
pkill -f '^judged /home/judge$' || true
pkill -f judge_client || true
rm -f /home/judge/etc/judge.pid
rm -f /home/judge/client*.pid
rm -f /home/judge/run*/judge_client.pid
mkdir -p /home/judge/log /home/judge/monitor /home/judge/metrics
for i in $(seq 0 49); do
  mkdir -p "/home/judge/run${i}/log"
done
"""
    run(["docker", "exec", container_name, "bash", "-lc", command], check=False)


def start_watchdog(container_name: str):
    docker_exec(
        container_name,
        "cd /home/judge/scripts && nohup bash run_judge.sh > /home/judge/scripts/runlog.out 2>&1 < /dev/null &",
    )


def ensure_judge_runtime(container_name: str, timeout: int = 30):
    reset_judge_runtime_state(container_name)
    start_watchdog(container_name)
    deadline = time.time() + timeout
    while time.time() < deadline:
        activity = fetch_judge_activity(container_name)
        if activity["watchdog"] and activity["judged"]:
            return activity
        time.sleep(2)
    raise RuntimeError(f"Judge runtime failed to start cleanly in container {container_name}")


def stop_container(container_name: str):
    run(["docker", "rm", "-f", container_name], capture=True, check=False)


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    judge_dir = Path(args.judge_dir).resolve()
    judge_template_dir = Path(args.judge_template_dir).resolve() if args.judge_template_dir else None

    try:
        update_summary(
            args.summary_path,
            status="eval_running",
            eval_started_at_utc=datetime.now(timezone.utc).isoformat(),
            eval_failed_at_utc=None,
            eval_completed_at_utc=None,
            error=None,
            metrics_path=None,
        )
        ensure_container(repo_root, judge_dir, judge_template_dir, args.container_name)
        quoted_run_name = shlex.quote(args.run_name)
        docker_exec(args.container_name, f"cd /home/judge/scripts && python3 add_template.py --model-name {quoted_run_name}")
        docker_exec(args.container_name, f"cd /home/judge/scripts && python3 submit_solution.py --model-name {quoted_run_name}")
        ensure_judge_runtime(args.container_name)

        model_id = fetch_model_id(args.container_name, args.run_name)
        if model_id is None:
            raise RuntimeError(f"Could not find submitted model_id for run {args.run_name}")

        normalized_pending_rows = normalize_pending_queue(args.container_name, model_id)
        update_summary(args.summary_path, model_id=model_id, normalized_pending_rows=normalized_pending_rows)
        started_at = time.monotonic()
        last_progress_at = started_at
        last_runtime_restart_at = 0.0
        last_status = None
        while True:
            status = fetch_status(args.container_name, model_id)
            activity = fetch_judge_activity(args.container_name)
            print(json.dumps({"run_name": args.run_name, "model_id": model_id, **status}), flush=True)
            update_summary(args.summary_path, eval_status=status, judge_activity=activity)
            if last_status is None or status["pending"] < last_status["pending"] or status["resolved"] > last_status["resolved"]:
                last_progress_at = time.monotonic()
            elapsed = time.monotonic() - started_at
            stalled_for = time.monotonic() - last_progress_at
            if status["total"] > 0 and status["pending"] == 0:
                break
            # Restart judge if no clients running, or if stalled for >5 min (normalize queue first to unstick solutions)
            needs_restart = status["pending"] > 0 and (
                activity["judge_clients"] == 0
                or stalled_for > 5 * 60
            )
            if needs_restart and time.monotonic() - last_runtime_restart_at > 60:
                if stalled_for > 5 * 60:
                    renorm = normalize_pending_queue(args.container_name, model_id)
                    print(f"  stall detected ({int(stalled_for)}s), renormalized {renorm} rows", flush=True)
                ensure_judge_runtime(args.container_name)
                last_runtime_restart_at = time.monotonic()
            if elapsed > args.max_wait_seconds:
                if 0 < status["pending"] <= args.force_resolve_max_pending:
                    forced = force_resolve_pending(args.container_name, model_id)
                    print(
                        f"  max_wait reached at pending={status['pending']} "
                        f"(<={args.force_resolve_max_pending}); force-marked {forced} rows as TLE to finalize",
                        flush=True,
                    )
                    status = fetch_status(args.container_name, model_id)
                    update_summary(
                        args.summary_path,
                        eval_status=status,
                        force_resolved_rows=forced,
                    )
                    if status["pending"] == 0:
                        break
                raise TimeoutError(
                    f"Timed out waiting for eval completion after {int(elapsed)}s for run={args.run_name} model_id={model_id}"
                )
            if stalled_for > args.stall_timeout_seconds:
                if 0 < status["pending"] <= args.force_resolve_max_pending:
                    forced = force_resolve_pending(args.container_name, model_id)
                    print(
                        f"  stall persisted at pending={status['pending']} (<={args.force_resolve_max_pending}); "
                        f"force-marked {forced} rows as TLE to finalize",
                        flush=True,
                    )
                    status = fetch_status(args.container_name, model_id)
                    update_summary(
                        args.summary_path,
                        eval_status=status,
                        force_resolved_rows=forced,
                    )
                    if status["pending"] == 0:
                        break
                raise TimeoutError(
                    f"Eval stalled for {int(stalled_for)}s with pending={status['pending']} for run={args.run_name} model_id={model_id}"
                )
            last_status = status
            time.sleep(args.poll_interval)

        metrics_path = str((judge_dir / "metrics" / "metrics_primary.csv").resolve())
        docker_exec(
            args.container_name,
            (
                "cd /home/judge/scripts && python3 compute_metrics.py "
                f"--model-id {model_id} "
                "--primary-output-path /home/judge/metrics/metrics_primary.csv "
                "--plus-output-path /home/judge/metrics/metrics_plus.csv"
            ),
        )
        update_summary(
            args.summary_path,
            status="eval_complete",
            eval_completed_at_utc=datetime.now(timezone.utc).isoformat(),
            metrics_path=metrics_path,
            eval_failed_at_utc=None,
            error=None,
        )
        if not sync_master(args.master_sync_script, args.master_manifest, args.summary_path):
            score = None
            if status["total"]:
                score = format_percent(100.0 * status["accepted"] / status["total"])
            send_telegram(
                args.notify_script,
                benchmark_message(args.model_name, "done", score),
            )
    except Exception as exc:
        update_summary(
            args.summary_path,
            status="eval_failed",
            eval_failed_at_utc=datetime.now(timezone.utc).isoformat(),
            error=str(exc),
        )
        if not sync_master(args.master_sync_script, args.master_manifest, args.summary_path):
            send_telegram(
                args.notify_script,
                benchmark_message(args.model_name, "failed"),
            )
        raise
    finally:
        stop_container(args.container_name)


if __name__ == "__main__":
    main()
