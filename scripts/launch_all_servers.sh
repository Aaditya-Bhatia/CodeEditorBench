#!/usr/bin/env bash
# Launch distributed_eval.py on lux-3-cyber-01 .. lux-3-cyber-10 via ssh.
#
# Each server runs the eval in the background (nohup) and logs to
#   benchmark_runs/_distributed_eval_<hostname>.log
#
# Usage:
#   ./scripts/launch_all_servers.sh                 # launch on 01..10
#   ./scripts/launch_all_servers.sh 01 03 07        # launch on specific servers
#   ./scripts/launch_all_servers.sh --tail          # tail logs across all servers
#   ./scripts/launch_all_servers.sh --status        # show assignment status
#   ./scripts/launch_all_servers.sh --stop          # kill running workers on all servers

set -u

REPO_DIR="/shared_workspace_mfs/aadi/Projects/CodeEditorBench"
SERVER_PREFIX="lux-3-cyber"
DEFAULT_IDS=(01 02 03 04 05 06 07 08 09 10)
MAX_CONCURRENT="${MAX_CONCURRENT:-4}"

case "${1:-}" in
    --status)
        cd "$REPO_DIR"
        python scripts/distributed_eval.py --status
        exit 0
        ;;
    --tail)
        cd "$REPO_DIR"
        exec tail -F benchmark_runs/_distributed_eval_${SERVER_PREFIX}-*.log
        ;;
    --stop)
        for id in "${DEFAULT_IDS[@]}"; do
            host="${SERVER_PREFIX}-${id}"
            echo "[$host] stopping workers..."
            ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$host" \
                "cd ${REPO_DIR} && \
                 source /shared_workspace_mfs/aadi/common.bashrc >/dev/null 2>&1 || true; \
                 pkill -f 'distributed_eval.py' || true; \
                 pkill -f '/shared_workspace_mfs/aadi/Projects/CodeEditorBench/scripts/detached_eval_worker.py' || true; \
                 docker ps --filter name=ceb_judge_${id} -q | xargs -r docker rm -f; \
                 python scripts/distributed_eval.py --release-server ${host}" &
        done
        wait
        exit 0
        ;;
esac

if [[ $# -gt 0 ]]; then
    IDS=("$@")
else
    IDS=("${DEFAULT_IDS[@]}")
fi

echo "Launching on: ${IDS[*]/#/${SERVER_PREFIX}-}"
echo

for id in "${IDS[@]}"; do
    host="${SERVER_PREFIX}-${id}"
    log="${REPO_DIR}/benchmark_runs/_distributed_eval_${host}.log"
    remote_cmd="cd ${REPO_DIR} && \
        source /shared_workspace_mfs/aadi/common.bashrc >/dev/null 2>&1 || true; \
        nohup python scripts/distributed_eval.py --max-concurrent ${MAX_CONCURRENT} \
            > ${log} 2>&1 < /dev/null & \
        echo \"[${host}] launched pid=\$!\""
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -n "$host" "$remote_cmd" &
done

wait
echo
echo "All launched. Useful follow-ups:"
echo "  $0 --status       # assignment table"
echo "  $0 --tail         # stream all server logs"
echo "  $0 --stop         # kill everything"
