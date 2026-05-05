log_dir="/home/judge/log"
if [ ! -d "$log_dir" ]; then
    mkdir -p "$log_dir"
    echo "Created log directory: $log_dir"
fi
rm -f /home/judge/etc/judge.pid
rm -f /home/judge/client*.pid
rm -f /home/judge/run*/judge_client.pid
pkill -f '^judged /home/judge$' >/dev/null 2>&1 || true
pkill -f judge_client >/dev/null 2>&1 || true
for i in $(seq 0 49); do
    mkdir -p "/home/judge/run${i}/log"
done
judged /home/judge
while true; do
    current_time=$(date +%s)
    four_minutes_ago=$((current_time - 360))
    ps -eo pid,lstart,cmd --no-headers | while read -r pid weekday month day time year cmd; do
        case "$cmd" in
            "java -Xmx512M -cp .:lib/gson-2.9.1.jar Main" | "/usr/bin/python3 Main.py")
                start_timestamp=$(date -d "$month $day $time $year" +%s)
                if [ "$start_timestamp" -lt "$four_minutes_ago" ]; then
                    kill -9 "$pid"
                    echo "Killed process $pid ($cmd) started at $month $day $time $year"
                fi
                ;;
        esac
    done
    sleep 60
done
