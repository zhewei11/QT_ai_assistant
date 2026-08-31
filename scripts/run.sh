#!/bin/bash
# qt ai assistant

# Get the parent directory of this script as the workspace root
WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ECG_CONFIG_FILE="$WORKSPACE_DIR/config/ecg_integration.env"
ECG_CONFIG_EXAMPLE="$WORKSPACE_DIR/config/ecg_integration.env.example"
if [ -f "$ECG_CONFIG_FILE" ]; then
    set -a
    source "$ECG_CONFIG_FILE"
    set +a
elif [ -f "$ECG_CONFIG_EXAMPLE" ]; then
    set -a
    source "$ECG_CONFIG_EXAMPLE"
    set +a
fi

ECG_ENABLED="${ECG_ENABLED:-true}"
ECG_REQUIRED="${ECG_REQUIRED:-false}"
ECG_MEASURE_ON_START="${ECG_MEASURE_ON_START:-false}"
ECG_OPEN_DASHBOARD_ON_START="${ECG_OPEN_DASHBOARD_ON_START:-false}"
ECG_RESULT_FILE="${ECG_RESULT_FILE:-$WORKSPACE_DIR/runtime/ecg_latest.json}"
ECG_YBC_MODEL_ENABLED="${ECG_YBC_MODEL_ENABLED:-false}"
ECG_YBC_MAX_BEATS="${ECG_YBC_MAX_BEATS:-80}"
ECG_YBC_BATCH_SIZE="${ECG_YBC_BATCH_SIZE:-32}"
ECG_YBC_TIMEOUT_SECONDS="${ECG_YBC_TIMEOUT_SECONDS:-5}"
ECG_PROCESS_NICE="${ECG_PROCESS_NICE:-5}"
# Temporary master switch for project-level face recognition.
# Keep this false to avoid starting face_identity_memory even when an older
# robot environment file still contains FACE_MEMORY_ENABLED=true.
FACE_RECOGNITION_ENABLED="${FACE_RECOGNITION_ENABLED:-false}"
FACE_MEMORY_ENABLED="${FACE_MEMORY_ENABLED:-false}"
if [ "$FACE_RECOGNITION_ENABLED" != "true" ]; then
    FACE_MEMORY_ENABLED=false
fi
FACE_MEMORY_FILE="${FACE_MEMORY_FILE:-$WORKSPACE_DIR/runtime/face_memory.json}"
FACE_MEMORY_MAX_PEOPLE="${FACE_MEMORY_MAX_PEOPLE:-4}"
FACE_CURRENT_TTL_SECONDS="${FACE_CURRENT_TTL_SECONDS:-30}"
FACE_MEMORY_TOPIC="${FACE_MEMORY_TOPIC:-/qt_nuitrack_app/faces}"
FACE_MEMORY_DEBUG_LOG_INTERVAL="${FACE_MEMORY_DEBUG_LOG_INTERVAL:-2.0}"
FACE_CAMERA_TOPIC="${FACE_CAMERA_TOPIC:-/camera/color/image_raw}"
FACE_CAMERA_VIEWER="${FACE_CAMERA_VIEWER:-auto}"
FACE_CAMERA_WEB_PORT="${FACE_CAMERA_WEB_PORT:-8090}"
FACE_CAMERA_STREAM_HOST="${FACE_CAMERA_STREAM_HOST:-}"
AI_TERMINAL_DEBUG="${AI_TERMINAL_DEBUG:-normal}"
AI_LOG_LEVEL="${AI_LOG_LEVEL:-WARNING}"
AI_LIBRARY_LOG_LEVEL="${AI_LIBRARY_LOG_LEVEL:-WARNING}"
if [[ "$FACE_MEMORY_FILE" != /* ]]; then
    FACE_MEMORY_FILE="$WORKSPACE_DIR/$FACE_MEMORY_FILE"
fi
export ECG_RESULT_FILE
export ECG_YBC_MODEL_ENABLED ECG_YBC_MAX_BEATS ECG_YBC_BATCH_SIZE ECG_YBC_TIMEOUT_SECONDS ECG_PROCESS_NICE
export FACE_RECOGNITION_ENABLED FACE_MEMORY_ENABLED FACE_MEMORY_FILE FACE_MEMORY_MAX_PEOPLE FACE_CURRENT_TTL_SECONDS FACE_MEMORY_TOPIC FACE_MEMORY_DEBUG_LOG_INTERVAL
export FACE_CAMERA_TOPIC FACE_CAMERA_VIEWER FACE_CAMERA_WEB_PORT FACE_CAMERA_STREAM_HOST
export AI_TERMINAL_DEBUG AI_LOG_LEVEL AI_LIBRARY_LOG_LEVEL

load_ros_params() {
    local namespace="$1"
    local file_path="$2"

    if command -v rosparam >/dev/null 2>&1; then
        echo "    -> rosparam load $file_path $namespace"
        if ! rosparam load "$file_path" "$namespace"; then
            echo "WARNING: Failed to load ROS params from $file_path into $namespace"
        fi
    else
        echo "WARNING: rosparam command not found; using Python default ROS parameters."
    fi
}

RIVA_PID=""
DISPATCHER_PID=""
FACE_MEMORY_PID=""
AI_PID=""
CLEANING_UP=false

stop_robot_outputs() {
    echo "[Shutdown] Stopping QTrobot speech/gesture if services are available..."
    if ! command -v rosservice >/dev/null 2>&1; then
        return
    fi

    local services
    services="$(rosservice list 2>/dev/null || true)"
    for service in \
        "/qt_robot/speech/stop" \
        "/qt_robot/behavior/stop" \
        "/qt_robot/gesture/stop" \
        "/qt_robot/emotion/stop"
    do
        if printf "%s\n" "$services" | grep -qx "$service"; then
            rosservice call "$service" "{}" >/dev/null 2>&1 || true
        fi
    done
}

kill_pid_tree() {
    local pid="$1"
    if [ -z "${pid:-}" ]; then
        return
    fi
    pkill -TERM -P "$pid" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true
}

force_kill_pid_tree() {
    local pid="$1"
    if [ -z "${pid:-}" ]; then
        return
    fi
    pkill -KILL -P "$pid" 2>/dev/null || true
    kill -KILL "$pid" 2>/dev/null || true
}

kill_project_processes() {
    pkill -TERM -f "src/ros_behavior_dispatcher.py" 2>/dev/null || true
    pkill -TERM -f "src/riva_speech_recongnition.py" 2>/dev/null || true
    pkill -TERM -f "src/ai_assistant_core.py" 2>/dev/null || true
    pkill -TERM -f "src/face_identity_memory.py" 2>/dev/null || true
    pkill -TERM -f "src/usb_audio_publisher.py" 2>/dev/null || true
    pkill -TERM -f "ecg/src/integration/ecg_session.py" 2>/dev/null || true
}

force_kill_project_processes() {
    pkill -KILL -f "src/ros_behavior_dispatcher.py" 2>/dev/null || true
    pkill -KILL -f "src/riva_speech_recongnition.py" 2>/dev/null || true
    pkill -KILL -f "src/ai_assistant_core.py" 2>/dev/null || true
    pkill -KILL -f "src/face_identity_memory.py" 2>/dev/null || true
    pkill -KILL -f "src/usb_audio_publisher.py" 2>/dev/null || true
    pkill -KILL -f "ecg/src/integration/ecg_session.py" 2>/dev/null || true
}

kill_port_listeners() {
    if ! command -v ss >/dev/null 2>&1; then
        return
    fi
    local pids
    pids="$(ss -ltnp 2>/dev/null | sed -n 's/.*:\(5555\|5556\).*pid=\([0-9]*\).*/\2/p' | sort -u)"
    for pid in $pids; do
        kill -KILL "$pid" 2>/dev/null || true
    done
}

# cleanup function: when a termination signal is received, it shuts down background processes
cleanup() {
    if [ "$CLEANING_UP" = "true" ]; then
        exit 130
    fi
    CLEANING_UP=true
    trap - SIGINT SIGTERM EXIT

    echo ""
    echo "[Shutdown] Ctrl+C received; stopping QT AI Assistant..."
    stop_robot_outputs

    if [ -x "$WORKSPACE_DIR/scripts/close_ecg_kiosk.sh" ]; then
        bash "$WORKSPACE_DIR/scripts/close_ecg_kiosk.sh" >/dev/null 2>&1 || true
    fi

    kill_pid_tree "$AI_PID"
    kill_pid_tree "$RIVA_PID"
    kill_pid_tree "$DISPATCHER_PID"
    kill_pid_tree "$FACE_MEMORY_PID"
    kill_project_processes
    sleep 1
    force_kill_pid_tree "$AI_PID"
    force_kill_pid_tree "$RIVA_PID"
    force_kill_pid_tree "$DISPATCHER_PID"
    force_kill_pid_tree "$FACE_MEMORY_PID"
    force_kill_project_processes
    kill_port_listeners

    wait "$RIVA_PID" "$DISPATCHER_PID" "$FACE_MEMORY_PID" "$AI_PID" 2>/dev/null || true
    echo "[Shutdown] All QT AI Assistant processes stopped."
    exit 130
}

# Trap early so Ctrl+C also works during startup.
trap cleanup SIGINT SIGTERM

echo "========================================="
echo " QT AI Assistant pipeline..."
echo "========================================="
echo "[Debug Config]"
echo "  ECG_ENABLED=$ECG_ENABLED"
echo "  ECG_MEASURE_ON_START=$ECG_MEASURE_ON_START"
echo "  ECG_OPEN_DASHBOARD_ON_START=$ECG_OPEN_DASHBOARD_ON_START"
echo "  ECG_DASHBOARD_URL=${ECG_DASHBOARD_URL:-https://ecg-monitor-bf64d.web.app}"
echo "  ECG_RESULT_FILE=$ECG_RESULT_FILE"
echo "  ECG_YBC_MODEL_ENABLED=$ECG_YBC_MODEL_ENABLED"
echo "  ECG_YBC_MAX_BEATS=$ECG_YBC_MAX_BEATS"
echo "  ECG_YBC_BATCH_SIZE=$ECG_YBC_BATCH_SIZE"
echo "  ECG_YBC_TIMEOUT_SECONDS=$ECG_YBC_TIMEOUT_SECONDS"
echo "  ECG_PROCESS_NICE=$ECG_PROCESS_NICE"
echo "  FACE_RECOGNITION_ENABLED=$FACE_RECOGNITION_ENABLED"
echo "  FACE_MEMORY_ENABLED=$FACE_MEMORY_ENABLED"
echo "  FACE_MEMORY_TOPIC=$FACE_MEMORY_TOPIC"
echo "  FACE_MEMORY_FILE=$FACE_MEMORY_FILE"
echo "  FACE_MEMORY_MAX_PEOPLE=$FACE_MEMORY_MAX_PEOPLE"
echo "  FACE_MEMORY_DEBUG_LOG_INTERVAL=$FACE_MEMORY_DEBUG_LOG_INTERVAL"
echo "  FACE_CAMERA_TOPIC=$FACE_CAMERA_TOPIC"
echo "  FACE_CAMERA_VIEWER=$FACE_CAMERA_VIEWER"
echo "  FACE_CAMERA_WEB_PORT=$FACE_CAMERA_WEB_PORT"
echo "  FACE_CAMERA_STREAM_HOST=${FACE_CAMERA_STREAM_HOST:-auto}"
echo "  AI_TERMINAL_DEBUG=$AI_TERMINAL_DEBUG"
echo "  AI_LOG_LEVEL=$AI_LOG_LEVEL"
echo "  AI_LIBRARY_LOG_LEVEL=$AI_LIBRARY_LOG_LEVEL"
echo "========================================="

# 0. Prepare ECG integration without blocking startup.
if [ "$ECG_ENABLED" = "true" ]; then
    echo "[0/6] ECG integration enabled; startup measurement is disabled by default."
    if [ "$ECG_OPEN_DASHBOARD_ON_START" = "true" ]; then
        echo "[0/6] Opening ECG dashboard at startup..."
        bash "$WORKSPACE_DIR/scripts/open_ecg_kiosk.sh" || \
            echo "WARNING: Unable to start the ECG kiosk on the face Raspberry Pi."
    else
        echo "[0/6] ECG dashboard will open only when showECG/measureECG is triggered."
    fi

    if [ "$ECG_MEASURE_ON_START" = "true" ]; then
        echo "[0/6] ECG_MEASURE_ON_START=true, running initial ECG measurement..."
        ECG_PYTHON="${ECG_PYTHON:-$WORKSPACE_DIR/ecg/.venv/bin/python}"
        if [ ! -x "$ECG_PYTHON" ]; then
            ECG_PYTHON="python3"
        fi

        if ! "$ECG_PYTHON" "$WORKSPACE_DIR/ecg/src/integration/ecg_session.py" \
            --output "$ECG_RESULT_FILE"; then
            echo "WARNING: Initial ECG measurement did not produce a valid result."
            if [ "$ECG_REQUIRED" = "true" ]; then
                echo "ERROR: ECG_REQUIRED=true, aborting startup."
                exit 1
            fi
        fi
    else
        echo "[0/6] ECG measurement is waiting for a voice command."
    fi
else
    echo "[0/6] ECG integration disabled."
fi

# 0. boot Riva Core Server in background
echo "[1/6] Booting Riva Core Server in background..."
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

echo "Loading ROS parameter files..."
load_ros_params "/ros_behavior_dispatcher" "$WORKSPACE_DIR/ros/config/dispatcher.yaml"
load_ros_params "/riva_speech_recongnition_node" "$WORKSPACE_DIR/ros/config/riva_speech_recognition.yaml"
if [ "$FACE_MEMORY_ENABLED" = "true" ]; then
    load_ros_params "/face_identity_memory" "$WORKSPACE_DIR/ros/config/face_memory.yaml"
fi

# 1. active ros virtual environment and run ros_behavior_dispatcher.py (Binds to 5556)
echo "[2/6] active ros virtual environment and run ros_behavior_dispatcher.py..."
cd "$WORKSPACE_DIR/ros"
# source /opt/ros/noetic/setup.bash
source .venv/bin/activate
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

if [ "$FACE_MEMORY_ENABLED" = "true" ]; then
    echo "[3/6] active ros virtual environment and run face_identity_memory.py..."
    echo "    -> subscribing to $FACE_MEMORY_TOPIC"
    echo "    -> writing slots to $FACE_MEMORY_FILE"
    echo "    -> max face slots: $FACE_MEMORY_MAX_PEOPLE"
    echo "    -> debug log interval: ${FACE_MEMORY_DEBUG_LOG_INTERVAL}s"
    cd "$WORKSPACE_DIR/ros"
    source .venv/bin/activate
    python3 src/face_identity_memory.py &
    FACE_MEMORY_PID=$!
else
    echo "[3/6] Face memory disabled."
    FACE_MEMORY_PID=""
fi

# 2. active ros virtual environment and run riva_speech_recongnition.py
echo "[4/6] active ros virtual environment and run riva_speech_recongnition.py..."
cd "$WORKSPACE_DIR/ros"
source .venv/bin/activate
python3 src/riva_speech_recongnition.py &
RIVA_PID=$!

# 3. active ai virtual environment and run ai_assistant_core.py (Binds to 5555, connects to 5556)
echo "[5/6] active ai virtual environment and run ai_assistant_core.py..."
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
        kill $DISPATCHER_PID $FACE_MEMORY_PID $RIVA_PID 2>/dev/null
        exit 1
    fi
    sleep 1
    COUNT=$((COUNT+1))
    if [ $COUNT -ge $TIMEOUT ]; then
        echo "ERROR: AI Brain failed to bind on port 5555 within $TIMEOUT seconds! Aborting."
        kill $DISPATCHER_PID $FACE_MEMORY_PID $RIVA_PID $AI_PID 2>/dev/null
        exit 1
    fi
done
echo "AI Brain (5555) is UP and listening!"

echo "========================================="
echo "All nodes have been successfully started in the background!"
echo "You can press [CTRL+C] at any time to safely shut down all programs."
echo "Face camera debug: ./scripts/open_face_camera_view.sh"
echo "Remote terminal web mode: FACE_CAMERA_VIEWER=web ./scripts/open_face_camera_view.sh"
echo "========================================="

# wait for background processes
wait
