#!/bin/sh

PROJECT_DIR="/home/jetson/workspace/GoVision_proj1"
LOG_FILE="$PROJECT_DIR/results/camera_self.log"

mkdir -p "$PROJECT_DIR/results"

{
    echo "---- $(date '+%Y-%m-%d %H:%M:%S') GoVision Camera Viewer launch ----"
    echo "DISPLAY=${DISPLAY:-}"
    echo "XAUTHORITY=${XAUTHORITY:-}"
    cd "$PROJECT_DIR" || exit 1
    export CAMERA_SENSOR_MODE="${CAMERA_SENSOR_MODE:-4}"
    export CAMERA_CAPTURE_WIDTH="${CAMERA_CAPTURE_WIDTH:-1280}"
    export CAMERA_CAPTURE_HEIGHT="${CAMERA_CAPTURE_HEIGHT:-720}"
    export CAMERA_DISPLAY_WIDTH="${CAMERA_DISPLAY_WIDTH:-352}"
    export CAMERA_DISPLAY_HEIGHT="${CAMERA_DISPLAY_HEIGHT:-320}"
    export CAMERA_FRAMERATE="${CAMERA_FRAMERATE:-30}"
    /usr/bin/python3 "$PROJECT_DIR/core/camera_self.py"
    status=$?
    echo "Exit status: $status"
    exit "$status"
} >> "$LOG_FILE" 2>&1
