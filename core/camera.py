"""Camera helpers for IMX219-83 CSI sensors on NVIDIA Jetson."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np


Frame = np.ndarray


@dataclass(frozen=True)
class CameraConfig:
    """Configuration for an IMX219-83 GStreamer capture pipeline."""

    capture_width: int = 1280
    capture_height: int = 720
    display_width: int = 1280
    display_height: int = 720
    framerate: int = 30
    flip_method: int = 2
    sensor_mode: Optional[int] = None


class CameraError(RuntimeError):
    """Raised when a camera cannot be opened or read."""


class IMX219Camera:
    """OpenCV wrapper around a Jetson GStreamer pipeline for one IMX219-83."""

    def __init__(self, sensor_id: int = 0, config: Optional[CameraConfig] = None) -> None:
        self.sensor_id = sensor_id
        self.config = config or CameraConfig()
        self.pipeline = self._build_pipeline()
        self._capture: Optional[cv2.VideoCapture] = None

    def _build_pipeline(self) -> str:
        cfg = self.config
        sensor_mode = ""
        if cfg.sensor_mode is not None:
            sensor_mode = f" sensor-mode={cfg.sensor_mode}"

        return (
            f"nvarguscamerasrc sensor-id={self.sensor_id}{sensor_mode} ! "
            f"video/x-raw(memory:NVMM), "
            f"width=(int){cfg.capture_width}, "
            f"height=(int){cfg.capture_height}, "
            f"framerate=(fraction){cfg.framerate}/1 ! "
            f"nvvidconv flip-method={cfg.flip_method} ! "
            f"video/x-raw, "
            f"width=(int){cfg.display_width}, "
            f"height=(int){cfg.display_height}, "
            "format=(string)BGRx ! "
            "videoconvert ! "
            "video/x-raw, format=(string)BGR ! "
            "appsink drop=true max-buffers=1 sync=false"
        )

    def open(self) -> None:
        """Open the camera pipeline if it is not already open."""

        if self.is_opened:
            return

        capture = cv2.VideoCapture(self.pipeline, cv2.CAP_GSTREAMER)
        if not capture.isOpened():
            capture.release()
            raise CameraError(
                f"Unable to open IMX219 camera sensor-id={self.sensor_id}. "
                "Check that the CSI sensor is connected and not already in use."
            )

        self._capture = capture

    @property
    def is_opened(self) -> bool:
        return bool(self._capture and self._capture.isOpened())

    def get_frame(self) -> Frame:
        """Return one BGR frame from the camera.

        The camera is opened lazily so callers can construct this class on a
        Jetson without immediately touching the hardware.
        """

        self.open()
        assert self._capture is not None

        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise CameraError(f"Unable to read frame from IMX219 sensor-id={self.sensor_id}.")

        return frame

    def release(self) -> None:
        """Release the OpenCV camera resource."""

        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def __enter__(self) -> "IMX219Camera":
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()


class DualIMX219Camera:
    """Dual-sensor capture helper for paired IMX219-83 CSI cameras."""

    def __init__(
        self,
        left_sensor_id: int = 0,
        right_sensor_id: int = 1,
        config: Optional[CameraConfig] = None,
    ) -> None:
        self.left = IMX219Camera(sensor_id=left_sensor_id, config=config)
        self.right = IMX219Camera(sensor_id=right_sensor_id, config=config)

    def open(self) -> None:
        """Open both sensors, releasing the first if the second fails."""

        try:
            self.left.open()
            self.right.open()
        except Exception:
            self.release()
            raise

    @property
    def is_opened(self) -> bool:
        return self.left.is_opened and self.right.is_opened

    def get_frame(self) -> Tuple[Frame, Frame]:
        """Return synchronized best-effort BGR frames as ``(left, right)``."""

        self.open()
        left_frame = self.left.get_frame()
        right_frame = self.right.get_frame()
        return left_frame, right_frame

    def release(self) -> None:
        self.left.release()
        self.right.release()

    def __enter__(self) -> "DualIMX219Camera":
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()
