#!/bin/bash
set -euo pipefail

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="$WORKSPACE_DIR/config/ecg_integration.env"
CONFIG_EXAMPLE="$WORKSPACE_DIR/config/ecg_integration.env.example"

if [ -f "$CONFIG_FILE" ]; then
    set -a
    source "$CONFIG_FILE"
    set +a
elif [ -f "$CONFIG_EXAMPLE" ]; then
    set -a
    source "$CONFIG_EXAMPLE"
    set +a
fi

ECG_PYTHON="${ECG_PYTHON:-$WORKSPACE_DIR/ecg/.venv/bin/python}"
if [ ! -x "$ECG_PYTHON" ]; then
    ECG_PYTHON="python3"
fi

ECG_TEST_DURATION="${ECG_TEST_DURATION:-15}"
ECG_TEST_SIGNAL_WAIT_TIMEOUT="${ECG_TEST_SIGNAL_WAIT_TIMEOUT:-60}"
ECG_TEST_OUTPUT="${ECG_TEST_OUTPUT:-$WORKSPACE_DIR/runtime/ecg_test_latest.json}"

echo "========================================="
echo " Standalone ECG measurement test"
echo "========================================="
echo "database_url=${ECG_FIREBASE_DATABASE_URL:-https://ecg-monitor-bf64d-default-rtdb.firebaseio.com}"
echo "device_path=${ECG_FIREBASE_DEVICE_PATH:-devices/yuguard_01}"
echo "duration=${ECG_TEST_DURATION}s"
echo "signal_wait_timeout=${ECG_TEST_SIGNAL_WAIT_TIMEOUT}s"
echo "output=$ECG_TEST_OUTPUT"
echo "python=$ECG_PYTHON"
echo "========================================="
echo "Phone app should show CLOUD ONLINE and BLUETOOTH READY."
echo "This script will write command=reset, clear stream, then write command=start."
echo "Countdown starts only after stable ECG quality, R peaks, and R-R intervals are confirmed."
echo "========================================="

"$ECG_PYTHON" "$WORKSPACE_DIR/ecg/src/integration/ecg_session.py" \
    --duration "$ECG_TEST_DURATION" \
    --signal-wait-timeout "$ECG_TEST_SIGNAL_WAIT_TIMEOUT" \
    --output "$ECG_TEST_OUTPUT"
