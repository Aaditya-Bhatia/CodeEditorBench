#!/usr/bin/env python3

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MYSQL_READY_TIMEOUT_SECONDS = 60
MYSQL_READY_POLL_SECONDS = 2


def parse_args():
    parser = argparse.ArgumentParser(description="Detached CodeEditorBench Docker eval worker.")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--config-path", required=True)
    parser.add_argument("--judge-dir", required=True)
    parser.add_argument("--container-name", default=os.environ.get("CONTAINER_NAME", "codeeditorbench_judge"))
    parser.add_argument("--notify-script", default="")
    parser.add_argument("--summary-path", default="")
    parser.add_argument("--poll-interval", type=int, default=60)
    return parser.parse_args()


def run(cmd, cwd=None, capture=False, check=True):
    kwargs = {"cwd": cwd, "check": check, "text": True}
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, **kwargs)


def send_telegram(notify_script: str, message: str):
    if not notify_script or not os.path.exists(notify_script):
        return
    subprocess.run([sys.executable, notify_script, message], check=False)


def update_summary(summary_path: str, **updates):
    if not summary_path:
        return
    path = Path(summary_path)
    if path.exists():
        data = json.loads(path.read_text())
    else:
        data = {}
    data.update(updates)
    path.write_text(json.dumps(data, indent=2) + "\n")


def read_judge_config(container_name: str) -> dict[str, str]:
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
rm -f /var/lib/mysql/*.pid
pkill -9 mysqld || true
service mysql start || service mysql restart || true
"""
    run(["docker", "exec", container_name, "bash", "-lc", command], check=False)


def ensure_container(repo_root: Path, judge_dir: Path, container_name: str):
    inspect = run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
        cwd=str(repo_root),
        capture=True,
        check=False,
    )
    if inspect.returncode != 0:
        run(["bash", "evaluation/run_judge_container.sh", str(judge_dir)], cwd=str(repo_root))
    elif inspect.stdout.strip() != "true":
        run(["docker", "start", container_name], cwd=str(repo_root))
    if wait_for_mysql(container_name, timeout=10):
        return

    repair_mysql(container_name)
    if wait_for_mysql(container_name):
        return

    run(["docker", "rm", "-f", container_name], cwd=str(repo_root), check=False)
    run(["bash", "evaluation/run_judge_container.sh", str(judge_dir)], cwd=str(repo_root))
    repair_mysql(container_name)
    if wait_for_mysql(container_name):
        return

    raise RuntimeError(
        f"Judge container {container_name} is running but MySQL is not reachable after repair/recreate attempts"
    )


def docker_exec(container_name: str, command: str):
    run(["docker", "exec", container_name, "bash", "-lc", command])


def docker_py(container_name: str, code: str):
    result = run(["docker", "exec", "-i", container_name, "python3", "-c", code], capture=True)
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
        "print(json.dumps({'total': int(row[0] or 0), 'pending': int(row[1] or 0), 'accepted': int(row[2] or 0)}))\n"
        "cur.close(); conn.close()\n"
    )
    return json.loads(docker_py(container_name, code))


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    judge_dir = Path(args.judge_dir).resolve()

    try:
        update_summary(
            args.summary_path,
            status="eval_running",
            eval_started_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        ensure_container(repo_root, judge_dir, args.container_name)
        quoted_run_name = shlex.quote(args.run_name)
        docker_exec(args.container_name, f"cd /home/judge/scripts && python3 add_template.py --model-name {quoted_run_name}")
        docker_exec(args.container_name, f"cd /home/judge/scripts && python3 submit_solution.py --model-name {quoted_run_name}")
        docker_exec(
            args.container_name,
            "pgrep -af '/home/judge/scripts/run_judge.sh' >/dev/null || "
            "(cd /home/judge/scripts && nohup bash run_judge.sh > runlog.out 2>&1 &)",
        )

        model_id = fetch_model_id(args.container_name, args.run_name)
        if model_id is None:
            raise RuntimeError(f"Could not find submitted model_id for run {args.run_name}")

        update_summary(args.summary_path, model_id=model_id)
        while True:
            status = fetch_status(args.container_name, model_id)
            print(json.dumps({"run_name": args.run_name, "model_id": model_id, **status}), flush=True)
            update_summary(args.summary_path, eval_status=status)
            if status["total"] > 0 and status["pending"] == 0:
                break
            time.sleep(args.poll_interval)

        docker_exec(args.container_name, "cd /home/judge/scripts && python3 compute_metrics.py")
        metrics_path = "/home/judge/metrics/metircs_primary.csv"
        update_summary(
            args.summary_path,
            status="eval_complete",
            eval_completed_at_utc=datetime.now(timezone.utc).isoformat(),
            metrics_path=metrics_path,
        )
        send_telegram(
            args.notify_script,
            (
                f"CodeEditorBench eval done. run={args.run_name} model_id={model_id} "
                f"total={status['total']} accepted={status['accepted']} metrics={metrics_path}"
            ),
        )
    except Exception as exc:
        update_summary(
            args.summary_path,
            status="eval_failed",
            eval_failed_at_utc=datetime.now(timezone.utc).isoformat(),
            error=str(exc),
        )
        send_telegram(
            args.notify_script,
            f"CodeEditorBench eval failed. run={args.run_name} config={args.config_path} error={exc}",
        )
        raise


if __name__ == "__main__":
    main()
