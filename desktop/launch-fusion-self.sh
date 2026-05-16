#!/bin/sh

PROJECT_DIR="/home/jetson/workspace/GoVision_proj1"
LOG_FILE="$PROJECT_DIR/results/fusion_self.log"

mkdir -p "$PROJECT_DIR/results"

{
    echo "---- $(date '+%Y-%m-%d %H:%M:%S') GoVision Fusion Viewer launch ----"
    echo "DISPLAY=${DISPLAY:-}"
    echo "XAUTHORITY=${XAUTHORITY:-}"
    cd "$PROJECT_DIR" || exit 1
    export CAMERA_SENSOR_MODE="${CAMERA_SENSOR_MODE:-4}"
    export CAMERA_CAPTURE_WIDTH="${CAMERA_CAPTURE_WIDTH:-1280}"
    export CAMERA_CAPTURE_HEIGHT="${CAMERA_CAPTURE_HEIGHT:-720}"
    export CAMERA_DISPLAY_WIDTH="${CAMERA_DISPLAY_WIDTH:-640}"
    export CAMERA_DISPLAY_HEIGHT="${CAMERA_DISPLAY_HEIGHT:-360}"
    export CAMERA_FRAMERATE="${CAMERA_FRAMERATE:-30}"
    export FUSION_VISIBLE_CROP_WIDTH_RATIO="${FUSION_VISIBLE_CROP_WIDTH_RATIO:-0.64}"
    export FUSION_VISIBLE_CROP_HEIGHT_RATIO="${FUSION_VISIBLE_CROP_HEIGHT_RATIO:-1.0}"
    export FUSION_THERMAL_OFFSET_X="${FUSION_THERMAL_OFFSET_X:-19}"
    export FUSION_THERMAL_OFFSET_Y="${FUSION_THERMAL_OFFSET_Y:--4}"
    export FUSION_THERMAL_FLIP_CODE="${FUSION_THERMAL_FLIP_CODE:-none}"
    /usr/bin/python3 "$PROJECT_DIR/core/fusion_self.py"
    status=$?
    echo "Exit status: $status"
    exit "$status"
} >> "$LOG_FILE" 2>&1
