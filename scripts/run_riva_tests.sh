#!/bin/bash

# ==========================================
# QTrobot AI Assistant - Riva Speech Test Runner
# ==========================================

echo "========================================"
echo " Starting Riva Speech Test Environment..."
echo "========================================"

# get current directory (in scripts/)
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# point to the project root directory
PROJECT_ROOT="$(dirname "$DIR")"

# 0. boot Riva Core Server in background
echo "[0] Booting Riva Core Server in background..."
echo "    -> cd ~/robot/riva_quickstart_arm64_v2.14.0 && bash ./riva_start.sh ./config.sh -s"
(cd ~/robot/riva_quickstart_arm64_v2.14.0 && bash ./riva_start.sh ./config.sh -s) &

echo "Polling localhost:50051 to check if Riva Server's neural network to load into the GPU..."
TIMEOUT=60
COUNT=0
while ! bash -c 'echo > /dev/tcp/localhost/50051' >/dev/null 2>&1; do
    sleep 1
    COUNT=$((COUNT+1))
    if [ $COUNT -ge $TIMEOUT ]; then
        echo "ERROR: Riva Server failed to start on Port 50051 within $TIMEOUT seconds! Aborting."
        exit 1
    fi
done
echo "Riva Server is UP and listening! Proceeding with ROS nodes..."

# 1. boot Riva ROS ASR node in background
echo "[1] Starting riva_speech_recongnition.py in background..."
python3 "$PROJECT_ROOT/ros/src/riva_speech_recongnition.py" &
RIVA_PID=$!

# check if Riva Python script has successfully connected to ROS network
echo "Polling ROS network to check if Riva ASR Node is initialized..."
TIMEOUT=15
COUNT=0
while ! rosnode list 2>/dev/null | grep -q "riva_speech_recongnition_node"; do
    # check if Riva Python script has crashed
    if ! kill -0 $RIVA_PID 2>/dev/null; then
        echo "ERROR: Riva Python script crashed during startup! Aborting."
        exit 1
    fi
    sleep 1
    COUNT=$((COUNT+1))
    if [ $COUNT -ge $TIMEOUT ]; then
        echo "ERROR: Riva ASR Node failed to register in ROS within $TIMEOUT seconds! Aborting."
        kill $RIVA_PID 2>/dev/null
        exit 1
    fi
done
echo "Riva ASR Node is running and registered in ROS! Launching receiver..."

# 2. boot Riva Test Receiver in foreground
echo "========================================"
echo " [2] Launching Riva Test Receiver"
echo "========================================"
echo " Please speak into the QTrobot Microphone!"
echo " The recognized texts will appear below:"
echo "========================================"


python3 "$PROJECT_ROOT/ros/test/test_riva_receiver.py"


echo ""
echo "========================================"
echo " Cleaning up background Riva ASR node..."
kill $RIVA_PID 2>/dev/null

wait $RIVA_PID 2>/dev/null

echo " Riva Test environment completely shut down."
echo "========================================"
