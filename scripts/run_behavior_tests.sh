#!/bin/bash

# ==========================================
# QTrobot AI Assistant - Test Runner
# ==========================================

echo "========================================"
echo " Starting Test Environment..."
echo "========================================"

# get current directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# 1. active ros virtual environment and run ros_behavior_dispatcher.py
echo "[1] Starting ros_behavior_dispatcher.py in background..."
python3 "$DIR/../ros/src/ros_behavior_dispatcher.py" &
DISPATCHER_PID=$!

# wait for ros_behavior_dispatcher.py to build ZeroMQ port 5556
echo "Polling localhost:5556 to ensure Dispatcher allows connections..."
TIMEOUT=15
COUNT=0
while ! bash -c 'echo > /dev/tcp/localhost/5556' 2>/dev/null; do
    sleep 1
    COUNT=$((COUNT+1))
    if [ $COUNT -ge $TIMEOUT ]; then
        echo "ERROR: Dispatcher failed to bind on port 5556 within $TIMEOUT seconds! Aborting."
        kill $DISPATCHER_PID 2>/dev/null
        exit 1
    fi
done
echo "Dispatcher (5556) is UP and listening! Launching menu..."

# 2. active ros virtual environment and run test_trigger.py
echo "========================================"
echo " Launching Interactive Test Menu"
echo "========================================"
# directly run test_trigger.py in foreground
python3 "$DIR/../ros/test/test_trigger.py"

# 3. when the interactive menu is closed (e.g., press 0 or Ctrl+C), automatically clean up background processes
echo ""
echo "========================================"
echo " Cleaning up background services..."
kill $DISPATCHER_PID 2>/dev/null

wait $DISPATCHER_PID 2>/dev/null

echo " Test environment completely shut down."
echo "========================================"
