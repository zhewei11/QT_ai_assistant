#!/bin/bash
# qt ai assistant

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================="
echo " QT AI Assistant pipeline..."
echo "========================================="

# 0. boot Riva Core Server in background
echo "[0/4] Booting Riva Core Server in background..."
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

# 1. active ros virtual environment and run ros_behavior_dispatcher.py (Binds to 5556)
echo "[1/4] active ros virtual environment and run ros_behavior_dispatcher.py..."
cd "$WORKSPACE_DIR/ros"
# source /opt/ros/noetic/setup.bash
python3 src/ros_behavior_dispatcher.py &
DISPATCHER_PID=$!

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
echo "Dispatcher (5556) is UP and listening!"

# 2. active ros virtual environment and run riva_speech_recongnition.py
echo "[2/4] active ros virtual environment and run riva_speech_recongnition.py..."
cd "$WORKSPACE_DIR/ros"
python3 src/riva_speech_recongnition.py &
RIVA_PID=$!

# 3. active ai virtual environment and run ai_assistant_core.py (Binds to 5555, connects to 5556)
echo "[3/4] active ai virtual environment and run ai_assistant_core.py..."
cd "$WORKSPACE_DIR/ai"
source .venv/bin/activate
python3 src/ai_assistant_core.py &
AI_PID=$!
deactivate

echo "Polling localhost:5555 to ensure AI Brain allows connections..."
TIMEOUT=20
COUNT=0
while ! bash -c 'echo > /dev/tcp/localhost/5555' 2>/dev/null; do
    if ! kill -0 $AI_PID 2>/dev/null; then
        echo "ERROR: AI Brain crashed during startup! Aborting."
        kill $DISPATCHER_PID $RIVA_PID 2>/dev/null
        exit 1
    fi
    sleep 1
    COUNT=$((COUNT+1))
    if [ $COUNT -ge $TIMEOUT ]; then
        echo "ERROR: AI Brain failed to bind on port 5555 within $TIMEOUT seconds! Aborting."
        kill $DISPATCHER_PID $RIVA_PID $AI_PID 2>/dev/null
        exit 1
    fi
done
echo "AI Brain (5555) is UP and listening!"

echo "========================================="
echo "All nodes have been successfully started in the background!"
echo "You can press [CTRL+C] at any time to safely shut down all programs."
echo "========================================="

# cleanup function: when a termination signal is received, it will shut down all background processes
cleanup() {
    kill $RIVA_PID $DISPATCHER_PID $AI_PID 2>/dev/null
    wait $RIVA_PID $DISPATCHER_PID $AI_PID 2>/dev/null
    exit 0
}

# trap CTRL+C
trap cleanup SIGINT

# wait for background processes
wait
