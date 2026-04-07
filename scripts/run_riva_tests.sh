#!/bin/bash

# ==========================================
# QTrobot AI Assistant - Riva Speech Test Runner
# ==========================================

echo "========================================"
echo " Starting Riva Speech Test Environment..."
echo "========================================"

# 取得目前腳本目錄 (在 scripts/ 底下)
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# 指向上一層的專案根目錄
PROJECT_ROOT="$(dirname "$DIR")"

# 0. 啟動 Riva 核心大腦伺服器 (在背景執行)
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
        echo "❌ ERROR: Riva Server failed to start on Port 50051 within $TIMEOUT seconds! Aborting."
        exit 1
    fi
done
echo "✅ Riva Server is UP and listening! Proceeding with ROS nodes..."

# 1. 在背景啟動 Riva ROS 語音辨識節點
echo "[1] Starting riva_speech_recongnition.py in background..."
python3 "$PROJECT_ROOT/ros/src/riva_speech_recongnition.py" &
RIVA_PID=$!

# 透過不斷檢查 ROS 節點清單來確認 Riva Python 程式是否已經順利連上 ROS 網路
echo "Polling ROS network to check if Riva ASR Node is initialized..."
TIMEOUT=15
COUNT=0
while ! rosnode list 2>/dev/null | grep -q "riva_speech_recongnition_node"; do
    # 同時檢查背景程式是不是已經當掉崩潰了
    if ! kill -0 $RIVA_PID 2>/dev/null; then
        echo "❌ ERROR: Riva Python script crashed during startup! Aborting."
        exit 1
    fi
    sleep 1
    COUNT=$((COUNT+1))
    if [ $COUNT -ge $TIMEOUT ]; then
        echo "❌ ERROR: Riva ASR Node failed to register in ROS within $TIMEOUT seconds! Aborting."
        kill $RIVA_PID 2>/dev/null
        exit 1
    fi
done
echo "✅ Riva ASR Node is running and registered in ROS! Launching receiver..."

# 2. 在前景啟動測試接收器 (Receiver)
echo "========================================"
echo " [2] Launching Riva Test Receiver"
echo "========================================"
echo " Please speak into the QTrobot Microphone!"
echo " The recognized texts will appear below:"
echo "========================================"

# 把畫面交還給使用者看接收結果
python3 "$PROJECT_ROOT/ros/test/test_riva_receiver.py"

# 4. 當接收端被關閉（例如按下 Ctrl+C）時，自動清理背景的 Riva 程式
echo ""
echo "========================================"
echo " Cleaning up background Riva ASR node..."
kill $RIVA_PID 2>/dev/null

wait $RIVA_PID 2>/dev/null

echo " Riva Test environment completely shut down."
echo "========================================"
