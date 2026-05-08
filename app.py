"""Flask MJPEG streams for GoVision camera and thermal feeds."""

from __future__ import annotations

import atexit
import time
from threading import Lock
from typing import Generator

import cv2
import numpy as np
from flask import Flask, Response, stream_with_context

from core.camera import CameraError, IMX219Camera as Camera
from core.thermal import FLIRLepton25 as Thermal, ThermalError


app = Flask(__name__)

camera = Camera(sensor_id=0)
thermal = Thermal()

camera_lock = Lock()
thermal_lock = Lock()

MJPEG_MIMETYPE = "multipart/x-mixed-replace; boundary=frame"
JPEG_QUALITY = 85


def _encode_jpeg(frame: np.ndarray) -> bytes:
    if frame.ndim == 2:
        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

    ok, encoded = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
    )
    if not ok:
        raise RuntimeError("Unable to encode frame as JPEG.")

    return encoded.tobytes()


def _mjpeg_chunk(frame: np.ndarray) -> bytes:
    return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + _encode_jpeg(frame) + b"\r\n"


def _error_frame(message: str, width: int = 640, height: int = 360) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.putText(
        frame,
        message[:72],
        (24, height // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return frame


def _video_stream() -> Generator[bytes, None, None]:
    while True:
        try:
            with camera_lock:
                frame = camera.get_frame()
            yield _mjpeg_chunk(frame)
        except (CameraError, RuntimeError) as exc:
            with camera_lock:
                camera.release()
            yield _mjpeg_chunk(_error_frame(str(exc)))
            time.sleep(1.0)


def _thermal_stream() -> Generator[bytes, None, None]:
    while True:
        try:
            with thermal_lock:
                frame = thermal.get_frame(colorize=True)
            yield _mjpeg_chunk(frame)
        except (ThermalError, RuntimeError) as exc:
            with thermal_lock:
                thermal.release()
            yield _mjpeg_chunk(_error_frame(str(exc)))
            time.sleep(1.0)


@app.get("/video_feed")
def video_feed() -> Response:
    return Response(stream_with_context(_video_stream()), content_type=MJPEG_MIMETYPE)


@app.get("/thermal_feed")
def thermal_feed() -> Response:
    return Response(stream_with_context(_thermal_stream()), content_type=MJPEG_MIMETYPE)


@atexit.register
def _release_hardware() -> None:
    camera.release()
    thermal.release()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
