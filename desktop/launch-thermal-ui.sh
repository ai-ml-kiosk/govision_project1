#!/bin/sh

PROJECT_DIR="/home/jetson/workspace/GoVision_proj1"
LOG_FILE="$PROJECT_DIR/results/thermal_ui.log"

mkdir -p "$PROJECT_DIR/results"

{
    echo "---- $(date '+%Y-%m-%d %H:%M:%S') GoVision Thermal Viewer launch ----"
    echo "DISPLAY=${DISPLAY:-}"
    echo "XAUTHORITY=${XAUTHORITY:-}"
    cd "$PROJECT_DIR" || exit 1
    export FLIR_FLIP_CODE="${FLIR_FLIP_CODE:--1}"
    /usr/bin/python3 "$PROJECT_DIR/ui/thermal_ui.py"
    status=$?
    echo "Exit status: $status"
    exit "$status"
} >> "$LOG_FILE" 2>&1
