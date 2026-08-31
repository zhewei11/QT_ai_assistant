#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$DIR/.." && pwd)"

if [ -f /opt/ros/noetic/setup.bash ]; then
    source /opt/ros/noetic/setup.bash
fi

if [ -f "$HOME/catkin_ws/devel/setup.bash" ]; then
    source "$HOME/catkin_ws/devel/setup.bash"
fi

if [ -f /home/qtrobot/robot/autostart/qt_robot.inc ]; then
    source /home/qtrobot/robot/autostart/qt_robot.inc
    if declare -F prepare_ros_environment >/dev/null; then
        prepare_ros_environment
    fi
fi

python3 "$ROOT_DIR/ros/test/test_gesture_catalog.py" "$@"
