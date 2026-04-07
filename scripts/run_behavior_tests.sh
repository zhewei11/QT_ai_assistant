#!/bin/bash

# ==========================================
# QTrobot AI Assistant - Test Runner
# ==========================================

echo "========================================"
echo " Starting Test Environment..."
echo "========================================"

# 取得目前腳本目錄
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# 1. 在背景啟動 ROS Behavior Dispatcher
echo "[1] Starting ros_behavior_dispatcher.py in background..."
python3 "$DIR/src/ros_behavior_dispatcher.py" &
DISPATCHER_PID=$!

# 確保 5556 port 在監聽 (Dispatcher 啟動成功)
echo "Polling localhost:5556 to ensure Dispatcher allows connections..."
TIMEOUT=15
COUNT=0
while ! bash -c 'echo > /dev/tcp/localhost/5556' 2>/dev/null; do
    sleep 1
    COUNT=$((COUNT+1))
    if [ $COUNT -ge $TIMEOUT ]; then
        echo "❌ ERROR: Dispatcher failed to bind on port 5556 within $TIMEOUT seconds! Aborting."
        kill $DISPATCHER_PID 2>/dev/null
        exit 1
    fi
done
echo "✅ Dispatcher (5556) is UP and listening! Launching menu..."

# 2. 在前景啟動互動式選單 (test_trigger.py)
echo "========================================"
echo " Launching Interactive Test Menu"
echo "========================================"
# 直接在前台執行，這會把終端機交還給使用者操作
python3 "$DIR/test/test_trigger.py"

# 3. 當互動選單被關閉（例如按下 0 或 Ctrl+C）時，自動清理背景程式
echo ""
echo "========================================"
echo " Cleaning up background services..."
kill $DISPATCHER_PID 2>/dev/null

wait $DISPATCHER_PID 2>/dev/null

echo " Test environment completely shut down."
echo "========================================"
