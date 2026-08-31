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

QT_FACE_HOST="${QT_FACE_HOST:-}"
QT_FACE_USER="${QT_FACE_USER:-qtrobot}"

if [ -z "$QT_FACE_HOST" ]; then
    echo "[ECG kiosk] QT_FACE_HOST 未設定，略過遠端臉部瀏覽器關閉。"
    exit 0
fi

REMOTE_TARGET="${QT_FACE_USER}@${QT_FACE_HOST}"

echo "[ECG kiosk] target=${REMOTE_TARGET}"
echo "[ECG kiosk] closing chromium kiosk on QTrobot face..."
if ssh -o BatchMode=yes -o ConnectTimeout=8 "$REMOTE_TARGET" \
    "pkill -f '[c]hromium.*ecg-monitor' >/dev/null 2>&1 || \
     pkill -f '[c]hromium.*--kiosk' >/dev/null 2>&1 || true; \
     rm -f /tmp/qt_ecg_kiosk.log; \
     echo closed"; then
    echo "[ECG kiosk] ECG 螢幕已關閉。"
else
    echo "[ECG kiosk] 關閉失敗，請檢查 SSH。"
    exit 1
fi
