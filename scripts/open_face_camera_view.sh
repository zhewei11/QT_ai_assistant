#!/bin/bash
set -u

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="$WORKSPACE_DIR/config/ecg_integration.env"
CONFIG_EXAMPLE="$WORKSPACE_DIR/config/ecg_integration.env.example"

USER_FACE_CAMERA_TOPIC="${FACE_CAMERA_TOPIC:-}"
USER_FACE_CAMERA_VIEWER="${FACE_CAMERA_VIEWER:-}"
USER_FACE_CAMERA_WEB_PORT="${FACE_CAMERA_WEB_PORT:-}"
USER_FACE_CAMERA_STREAM_HOST="${FACE_CAMERA_STREAM_HOST:-}"

if [ -f "$CONFIG_FILE" ]; then
    set -a
    source "$CONFIG_FILE"
    set +a
elif [ -f "$CONFIG_EXAMPLE" ]; then
    set -a
    source "$CONFIG_EXAMPLE"
    set +a
fi

FACE_CAMERA_TOPIC="${USER_FACE_CAMERA_TOPIC:-${FACE_CAMERA_TOPIC:-/camera/color/image_raw}}"
FACE_CAMERA_VIEWER="${USER_FACE_CAMERA_VIEWER:-${FACE_CAMERA_VIEWER:-auto}}"
FACE_CAMERA_WEB_PORT="${USER_FACE_CAMERA_WEB_PORT:-${FACE_CAMERA_WEB_PORT:-8090}}"
FACE_CAMERA_STREAM_HOST="${USER_FACE_CAMERA_STREAM_HOST:-${FACE_CAMERA_STREAM_HOST:-}}"
if [ -z "${FACE_CAMERA_STREAM_HOST:-}" ]; then
    FACE_CAMERA_STREAM_HOST="$(hostname -I 2>/dev/null | awk '{print $1}')"
    FACE_CAMERA_STREAM_HOST="${FACE_CAMERA_STREAM_HOST:-$(hostname)}"
fi

has_ros_package() {
    local package_name="$1"
    command -v rospack >/dev/null 2>&1 && rospack find "$package_name" >/dev/null 2>&1
}

print_header() {
    echo "========================================="
    echo " QTrobot face camera debug view"
    echo "========================================="
    echo "[Face camera] topic=$FACE_CAMERA_TOPIC"
    echo "[Face camera] viewer=$FACE_CAMERA_VIEWER"
    echo "[Face camera] DISPLAY=${DISPLAY:-'(unset)'}"
    echo "[Face camera] ROS_MASTER_URI=${ROS_MASTER_URI:-'(unset)'}"
    echo "========================================="
}

open_rqt_viewer() {
    if command -v rqt_image_view >/dev/null 2>&1; then
        echo "[Face camera] launching rqt_image_view..."
        exec rqt_image_view "$FACE_CAMERA_TOPIC"
    fi
    return 1
}

open_image_viewer() {
    if command -v rosrun >/dev/null 2>&1 && has_ros_package image_view; then
        echo "[Face camera] launching image_view..."
        exec rosrun image_view image_view image:="$FACE_CAMERA_TOPIC"
    fi
    return 1
}

open_web_viewer() {
    if command -v rosrun >/dev/null 2>&1 && has_ros_package web_video_server; then
        echo "[Face camera] launching web_video_server..."
        echo "[Face camera] laptop browser URL:"
        echo "  http://$FACE_CAMERA_STREAM_HOST:$FACE_CAMERA_WEB_PORT/stream?topic=$FACE_CAMERA_TOPIC"
        echo "[Face camera] stop with Ctrl+C when finished."
        exec rosrun web_video_server web_video_server _port:="$FACE_CAMERA_WEB_PORT"
    fi
    return 1
}

print_missing_tools() {
    echo "[Face camera] No usable ROS image viewer was found."
    echo "[Face camera] Install/use one of: rqt_image_view, image_view, or web_video_server."
    echo "[Face camera] Remote laptop options:"
    echo "  1. SSH with X forwarding, then run: FACE_CAMERA_VIEWER=rqt ./scripts/open_face_camera_view.sh"
    echo "  2. Use web mode, then open the printed URL in your laptop browser:"
    echo "     FACE_CAMERA_VIEWER=web ./scripts/open_face_camera_view.sh"
    exit 127
}

print_header

case "$FACE_CAMERA_VIEWER" in
    rqt)
        open_rqt_viewer || print_missing_tools
        ;;
    image_view)
        open_image_viewer || print_missing_tools
        ;;
    web)
        open_web_viewer || print_missing_tools
        ;;
    auto)
        if [ -n "${DISPLAY:-}" ]; then
            open_rqt_viewer || open_image_viewer || open_web_viewer || print_missing_tools
        else
            echo "[Face camera] DISPLAY is not set; using web mode for remote terminal viewing."
            open_web_viewer || print_missing_tools
        fi
        ;;
    *)
        echo "[Face camera] Unsupported FACE_CAMERA_VIEWER=$FACE_CAMERA_VIEWER"
        echo "[Face camera] Use one of: auto, rqt, image_view, web"
        exit 2
        ;;
esac
