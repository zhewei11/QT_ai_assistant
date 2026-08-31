#!/bin/bash

set -u

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

ECG_DASHBOARD_URL="${ECG_DASHBOARD_URL:-https://ecg-monitor-bf64d.web.app}"
QT_FACE_HOST="${QT_FACE_HOST:-}"
QT_FACE_USER="${QT_FACE_USER:-qtrobot}"
QT_FACE_DISPLAY="${QT_FACE_DISPLAY:-:0}"
ECG_KIOSK_CLOSE_EXISTING="${ECG_KIOSK_CLOSE_EXISTING:-false}"

if [ -z "$QT_FACE_HOST" ]; then
    echo "[ECG kiosk] QT_FACE_HOST 未設定，略過遠端臉部瀏覽器啟動。"
    echo "[ECG kiosk] 若要在 QTrobot 臉部顯示 ECG，請設定 QT_FACE_HOST=<face raspberry pi ip>。"
    exit 0
fi

REMOTE_TARGET="${QT_FACE_USER}@${QT_FACE_HOST}"
REMOTE_URL=$(printf '%q' "$ECG_DASHBOARD_URL")
REMOTE_DISPLAY=$(printf '%q' "$QT_FACE_DISPLAY")

echo "[ECG kiosk] target=${REMOTE_TARGET}"
echo "[ECG kiosk] display=${QT_FACE_DISPLAY}"
echo "[ECG kiosk] url=${ECG_DASHBOARD_URL}"
echo "[ECG kiosk] launching chromium kiosk on QTrobot face..."
if ssh -o BatchMode=yes -o ConnectTimeout=8 "$REMOTE_TARGET" \
    "export DISPLAY=${REMOTE_DISPLAY}; \
     BROWSER=\$(command -v chromium-browser || command -v chromium); \
     if [ -z \"\$BROWSER\" ]; then echo 'chromium-browser/chromium not found' >&2; exit 127; fi; \
     echo \"browser=\$BROWSER\"; \
     if [ '${ECG_KIOSK_CLOSE_EXISTING}' = 'true' ]; then pkill -f '[c]hromium' >/dev/null 2>&1 || true; fi; \
     nohup \"\$BROWSER\" --disable-gpu --no-sandbox --kiosk --incognito ${REMOTE_URL} \
     >/tmp/qt_ecg_kiosk.log 2>&1 </dev/null & \
     echo \"chromium_pid=\$!\"; \
     exit 0"; then
    echo "[ECG kiosk] 已送出 ECG 螢幕啟動命令。遠端 log: /tmp/qt_ecg_kiosk.log"
else
    echo "[ECG kiosk] 啟動失敗，請檢查 SSH、DISPLAY、chromium-browser。"
    exit 1
fi
