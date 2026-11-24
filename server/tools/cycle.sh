#!/usr/bin/env bash
# One test cycle: restart server, relaunch the game, tap "Vao game", report requests and Lua errors.
set -u
export PATH=$HOME/Android/Sdk/platform-tools:$PATH
SRV=/home/hii/Documents/SAHHT/server
SHOT=${1:-cycle}

PID=$(ss -ltnpH 'sport = :8080' | grep -oP 'pid=\K[0-9]+' | head -1)
[ -n "$PID" ] && kill "$PID" && sleep 1
cd "$SRV" && setsid nohup python3 -m sahht_server.app --port 8080 > build/server.out 2>&1 < /dev/null &
sleep 1.5

: > "$SRV/data/requests.jsonl"
adb shell am force-stop vn.sahht.sl
adb logcat -c
adb shell monkey -p vn.sahht.sl -c android.intent.category.LAUNCHER 1 > /dev/null 2>&1
sleep 18                       # login scene + auto server list
adb shell input tap 1260 934   # "Vao game"
sleep 35

echo "--- requests"
python3 -c "
import json
for l in open('$SRV/data/requests.jsonl'):
    d = json.loads(l)
    flags = [f for f in ('quiet', 'closed') if d.get(f)]
    print(d['service'], d['method'], d['params'].get('config_name', ''), *flags)"
echo "--- lua errors"
adb logcat -d | grep "LUA-print" | sed 's/.*LUA-print\] //' | grep -E "LUA ERROR|failed:|attempt to" | sort -u | head -15
echo "--- server stderr"
tail -5 "$SRV/build/server.out"
adb exec-out screencap -p > "$SRV/build/$SHOT.png"
echo "screenshot: $SRV/build/$SHOT.png"
