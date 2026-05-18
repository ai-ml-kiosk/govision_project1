"""Standalone 480x320 live fusion viewer for CSI and FLIR Lepton cameras."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import cv2
import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.camera import CameraConfig, CameraError, IMX219Camera  # noqa: E402
from core.thermal import (  # noqa: E402
    FLIRLepton25,
    LeptonConfig,
    ThermalError,
    config_with_detected_spidev,
    parse_spi_candidates,
    tlinear_to_celsius,
)


DEFAULT_WINDOW_WIDTH = 480
DEFAULT_WINDOW_HEIGHT = 320
DEFAULT_WINDOW_NAME = "GoVision Fusion UI"
DEFAULT_PANEL_WIDTH = 128
DEFAULT_VIEW_WIDTH = DEFAULT_WINDOW_WIDTH - DEFAULT_PANEL_WIDTH
DEFAULT_VIEW_HEIGHT = DEFAULT_WINDOW_HEIGHT
DEFAULT_SENSOR_MODE = 4
DEFAULT_CAMERA_DISPLAY_WIDTH = 640
DEFAULT_CAMERA_DISPLAY_HEIGHT = 360
DEFAULT_VISIBLE_CROP_WIDTH_RATIO = 0.64
DEFAULT_VISIBLE_CROP_HEIGHT_RATIO = 1.0
DEFAULT_VISIBLE_OFFSET_X = 0
DEFAULT_VISIBLE_OFFSET_Y = 0
DEFAULT_THERMAL_OFFSET_X = 19
DEFAULT_THERMAL_OFFSET_Y = -4
DEFAULT_THERMAL_FLIP_CODE = "none"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "results"
DEFAULT_SETTINGS_PATH = Path("~/.config/govision/fusion_ui.json")
LEGACY_SETTINGS_PATH = Path("~/.config/govision/fusion_self.json")
ZOOM_LEVELS = (1.0, 1.5, 2.0, 3.0, 4.0)
THERMAL_OFFSET_NUDGE_PIXELS = 2


Rect = Tuple[int, int, int, int]


@dataclass
class ViewerState:
    csi_on: bool = True
    thermal_on: bool = True
    toggle_csi_requested: bool = False
    toggle_thermal_requested: bool = False
    reset_thermal_requested: bool = False
    csi_rotation_delta_requested: int = 0
    csi_rotation_degrees: int = 0
    csi_zoom_delta_requested: int = 0
    csi_zoom_level: float = 1.0
    thermal_rotation_delta_requested: int = 0
    thermal_rotation_degrees: int = 0
    thermal_zoom_delta_requested: int = 0
    thermal_zoom_level: float = 1.0
    thermal_offset_delta_x_requested: int = 0
    thermal_offset_delta_y_requested: int = 0
    thermal_offset_x: int = DEFAULT_THERMAL_OFFSET_X
    thermal_offset_y: int = DEFAULT_THERMAL_OFFSET_Y
    capture_requested: bool = False
    quit_requested: bool = False
    last_camera_frame: Optional[np.ndarray] = None
    last_thermal_raw: Optional[np.ndarray] = None
    last_fused_view: Optional[np.ndarray] = None
    message: str = "Starting"
    message_until: float = 0.0

    def set_message(self, message: str, ttl_s: float = 3.0) -> None:
        self.message = message
        self.message_until = time.monotonic() + ttl_s


def env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_optional_float(name: str) -> Optional[float]:
    value = os.getenv(name)
    return None if value is None else float(value)


def env_int_optional(name: str) -> Optional[int]:
    value = os.getenv(name)
    return None if value is None else int(value)


def env_first(*names: str, default: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value
    return default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open a 480x320 live CSI plus FLIR fusion viewing window"
    )
    parser.add_argument("--window-name", default=os.getenv("FUSION_WINDOW_NAME", DEFAULT_WINDOW_NAME))
    parser.add_argument(
        "--window-width",
        type=int,
        default=env_int("FUSION_WINDOW_WIDTH", DEFAULT_WINDOW_WIDTH),
    )
    parser.add_argument(
        "--window-height",
        type=int,
        default=env_int("FUSION_WINDOW_HEIGHT", DEFAULT_WINDOW_HEIGHT),
    )
    parser.add_argument(
        "--panel-width",
        type=int,
        default=env_int("FUSION_PANEL_WIDTH", DEFAULT_PANEL_WIDTH),
    )
    parser.add_argument(
        "--results-dir",
        default=os.getenv("FUSION_RESULTS_DIR", str(DEFAULT_RESULTS_DIR)),
        help="Directory for Capture button JPEG output",
    )
    parser.add_argument(
        "--settings-file",
        default=os.getenv(
            "FUSION_UI_SETTINGS_FILE",
            os.getenv("FUSION_SELF_SETTINGS_FILE", str(DEFAULT_SETTINGS_PATH)),
        ),
        help="JSON file used to remember viewer settings",
    )
    parser.add_argument(
        "--no-save-settings",
        action="store_true",
        help="Do not load or save persisted viewer settings",
    )
    parser.add_argument(
        "--rotation-degrees",
        type=int,
        default=None,
        help="Fallback clockwise display rotation for both cameras; overrides saved setting",
    )
    parser.add_argument(
        "--zoom-level",
        type=float,
        default=None,
        help="Fallback display zoom for both cameras; overrides saved setting",
    )
    parser.add_argument(
        "--csi-rotation-degrees",
        type=int,
        default=None,
        help="Initial clockwise CSI display rotation in degrees; overrides saved setting",
    )
    parser.add_argument(
        "--csi-zoom-level",
        type=float,
        default=None,
        help="Initial CSI display zoom; overrides saved setting",
    )
    parser.add_argument(
        "--thermal-rotation-degrees",
        type=int,
        default=None,
        help="Initial clockwise thermal display rotation in degrees; overrides saved setting",
    )
    parser.add_argument(
        "--thermal-zoom-level",
        type=float,
        default=None,
        help="Initial thermal display zoom; overrides saved setting",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=env_float("FUSION_ALPHA", 0.35),
        help="Thermal overlay alpha when both cameras are on",
    )
    parser.add_argument(
        "--visible-crop-width-ratio",
        type=float,
        default=env_float("FUSION_VISIBLE_CROP_WIDTH_RATIO", DEFAULT_VISIBLE_CROP_WIDTH_RATIO),
        help="Visible-frame width ratio used before thermal overlay alignment",
    )
    parser.add_argument(
        "--visible-crop-height-ratio",
        type=float,
        default=env_float("FUSION_VISIBLE_CROP_HEIGHT_RATIO", DEFAULT_VISIBLE_CROP_HEIGHT_RATIO),
        help="Visible-frame height ratio used before thermal overlay alignment",
    )
    parser.add_argument(
        "--visible-offset-x",
        type=int,
        default=env_int("FUSION_VISIBLE_OFFSET_X", DEFAULT_VISIBLE_OFFSET_X),
        help="Visible crop center x offset in source-frame pixels",
    )
    parser.add_argument(
        "--visible-offset-y",
        type=int,
        default=env_int("FUSION_VISIBLE_OFFSET_Y", DEFAULT_VISIBLE_OFFSET_Y),
        help="Visible crop center y offset in source-frame pixels",
    )
    parser.add_argument(
        "--thermal-offset-x",
        type=int,
        default=None,
        help="Thermal overlay x shift in final view pixels; positive moves right",
    )
    parser.add_argument(
        "--thermal-offset-y",
        type=int,
        default=None,
        help="Thermal overlay y shift in final view pixels; positive moves down",
    )
    parser.add_argument("--jpeg-quality", type=int, default=env_int("FUSION_JPEG_QUALITY", 95))
    parser.add_argument("--no-overlay", action="store_true", help="Hide view-area status overlay")

    parser.add_argument("--sensor-id", type=int, default=env_int("CAMERA_SENSOR_ID", 0))
    parser.add_argument("--capture-width", type=int, default=env_int("CAMERA_CAPTURE_WIDTH", 1280))
    parser.add_argument("--capture-height", type=int, default=env_int("CAMERA_CAPTURE_HEIGHT", 720))
    parser.add_argument(
        "--display-width",
        type=int,
        default=env_int("CAMERA_DISPLAY_WIDTH", DEFAULT_CAMERA_DISPLAY_WIDTH),
    )
    parser.add_argument(
        "--display-height",
        type=int,
        default=env_int("CAMERA_DISPLAY_HEIGHT", DEFAULT_CAMERA_DISPLAY_HEIGHT),
    )
    parser.add_argument("--framerate", type=int, default=env_int("CAMERA_FRAMERATE", 30))
    parser.add_argument("--flip-method", type=int, default=env_int("CAMERA_FLIP_METHOD", 2))
    parser.add_argument(
        "--sensor-mode",
        type=int,
        default=env_int("CAMERA_SENSOR_MODE", DEFAULT_SENSOR_MODE),
    )
    parser.add_argument("--camera-error-sleep-s", type=float, default=env_float("CAMERA_ERROR_SLEEP_S", 0.25))

    parser.add_argument(
        "--thermal-flip-code",
        default=env_first(
            "FUSION_THERMAL_FLIP_CODE",
            "fusion_thermal_flip_code",
            "FLIR_FLIP_CODE",
            "flir_flip_code",
            default=DEFAULT_THERMAL_FLIP_CODE,
        ),
        help="OpenCV flip code for thermal overlay orientation",
    )
    parser.add_argument("--thermal-min-c", type=float, default=env_optional_float("FLIR_MIN_C"))
    parser.add_argument("--thermal-max-c", type=float, default=env_optional_float("FLIR_MAX_C"))
    parser.add_argument("--thermal-low-percentile", type=float, default=env_float("FLIR_LOW_PCT", 2.0))
    parser.add_argument("--thermal-high-percentile", type=float, default=env_float("FLIR_HIGH_PCT", 98.0))
    parser.add_argument(
        "--thermal-sensitivity",
        type=float,
        default=env_float("FLIR_SENSITIVITY", 1.4),
        help="Narrow auto color range; higher values make smaller changes more visible",
    )
    parser.add_argument("--tlinear-scale", type=float, default=env_float("FLIR_TLINEAR_SCALE", 100.0))
    parser.add_argument("--bus", type=int, default=None, help="Force FLIR SPI bus")
    parser.add_argument("--device", type=int, default=None, help="Force FLIR SPI device")
    parser.add_argument("--speed-hz", type=int, default=env_int("FLIR_SPI_SPEED_HZ", 18_000_000))
    parser.add_argument("--probe-speed-hz", type=int, default=env_int("FLIR_PROBE_SPEED_HZ", 2_000_000))
    parser.add_argument(
        "--candidates",
        default=os.getenv("FLIR_SPI_CANDIDATES", "0.0,0.1,1.0,1.1"),
        help="Comma-separated FLIR bus.device list for auto-detect",
    )
    parser.add_argument("--no-auto-detect", action="store_true")
    parser.add_argument("--max-frame-attempts", type=int, default=env_int("FLIR_MAX_FRAME_ATTEMPTS", 2))
    parser.add_argument("--max-sync-packets", type=int, default=env_int("FLIR_MAX_SYNC_PACKETS", 6_000))
    parser.add_argument("--resync-delay-s", type=float, default=env_float("FLIR_RESYNC_DELAY_S", 0.0))
    parser.add_argument("--thermal-error-sleep-s", type=float, default=env_float("FLIR_ERROR_SLEEP_S", 0.1))
    parser.add_argument(
        "--reset-board-pin",
        type=int,
        default=env_int_optional("FLIR_RESET_BOARD_PIN"),
        help="Optional Jetson J41 physical pin wired to FLIR reset/enable",
    )
    parser.add_argument(
        "--reset-active-high",
        action="store_true",
        default=env_bool("FLIR_RESET_ACTIVE_HIGH", False),
        help="Use active-high reset pulse instead of the default active-low pulse",
    )
    parser.add_argument("--reset-pulse-s", type=float, default=env_float("FLIR_RESET_PULSE_S", 0.2))
    parser.add_argument("--reset-settle-s", type=float, default=env_float("FLIR_RESET_SETTLE_S", 0.75))
    return parser


def build_camera_config(args: argparse.Namespace) -> CameraConfig:
    return CameraConfig(
        capture_width=args.capture_width,
        capture_height=args.capture_height,
        display_width=args.display_width,
        display_height=args.display_height,
        framerate=args.framerate,
        flip_method=args.flip_method,
        sensor_mode=args.sensor_mode,
    )


def build_thermal_config(args: argparse.Namespace) -> LeptonConfig:
    config = fallback_thermal_config(args)
    forced_spi = args.bus is not None or args.device is not None
    env_forced_spi = "FLIR_SPI_BUS" in os.environ or "FLIR_SPI_DEVICE" in os.environ

    if args.no_auto_detect or forced_spi or env_forced_spi:
        return config

    return config_with_detected_spidev(
        config,
        candidates=parse_spi_candidates(args.candidates),
        probe_speed_hz=args.probe_speed_hz,
    )


def fallback_thermal_config(args: argparse.Namespace) -> LeptonConfig:
    return LeptonConfig(
        spi_bus=args.bus if args.bus is not None else env_int("FLIR_SPI_BUS", LeptonConfig.spi_bus),
        spi_device=args.device
        if args.device is not None
        else env_int("FLIR_SPI_DEVICE", LeptonConfig.spi_device),
        spi_speed_hz=args.speed_hz,
        max_frame_attempts=args.max_frame_attempts,
        max_sync_packets=args.max_sync_packets,
        resync_delay_s=args.resync_delay_s,
        reset_board_pin=args.reset_board_pin,
        reset_active_low=not args.reset_active_high,
        reset_pulse_s=args.reset_pulse_s,
        reset_settle_s=args.reset_settle_s,
    )


def settings_path(args: argparse.Namespace) -> Path:
    return Path(args.settings_file).expanduser()


def legacy_settings_path(args: argparse.Namespace) -> Optional[Path]:
    if Path(args.settings_file) != DEFAULT_SETTINGS_PATH:
        return None
    path = LEGACY_SETTINGS_PATH.expanduser()
    return path if path.exists() else None


def load_viewer_settings(args: argparse.Namespace) -> Dict[str, float]:
    if args.no_save_settings:
        return {}

    path = legacy_settings_path(args) or settings_path(args)
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Unable to load fusion viewer settings from {path}: {exc}", file=sys.stderr)
        return {}

    if not isinstance(data, dict):
        return {}

    settings: Dict[str, float] = {}
    rotation = data.get("rotation_degrees")
    if isinstance(rotation, int):
        settings["rotation_degrees"] = normalize_degrees(rotation)
    zoom = data.get("zoom_level")
    if isinstance(zoom, (int, float)):
        settings["zoom_level"] = normalize_zoom(float(zoom))
    csi_rotation = data.get("csi_rotation_degrees")
    if isinstance(csi_rotation, int):
        settings["csi_rotation_degrees"] = normalize_degrees(csi_rotation)
    csi_zoom = data.get("csi_zoom_level")
    if isinstance(csi_zoom, (int, float)):
        settings["csi_zoom_level"] = normalize_zoom(float(csi_zoom))
    thermal_rotation = data.get("thermal_rotation_degrees")
    if isinstance(thermal_rotation, int):
        settings["thermal_rotation_degrees"] = normalize_degrees(thermal_rotation)
    thermal_zoom = data.get("thermal_zoom_level")
    if isinstance(thermal_zoom, (int, float)):
        settings["thermal_zoom_level"] = normalize_zoom(float(thermal_zoom))
    thermal_offset_x = data.get("thermal_offset_x")
    if isinstance(thermal_offset_x, int):
        settings["thermal_offset_x"] = thermal_offset_x
    thermal_offset_y = data.get("thermal_offset_y")
    if isinstance(thermal_offset_y, int):
        settings["thermal_offset_y"] = thermal_offset_y
    return settings


def save_viewer_settings(args: argparse.Namespace, state: ViewerState) -> None:
    if args.no_save_settings:
        return

    path = settings_path(args)
    payload = {
        "csi_rotation_degrees": normalize_degrees(state.csi_rotation_degrees),
        "csi_zoom_level": normalize_zoom(state.csi_zoom_level),
        "thermal_rotation_degrees": normalize_degrees(state.thermal_rotation_degrees),
        "thermal_zoom_level": normalize_zoom(state.thermal_zoom_level),
        "thermal_offset_x": int(state.thermal_offset_x),
        "thermal_offset_y": int(state.thermal_offset_y),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except OSError as exc:
        print(f"Unable to save fusion viewer settings to {path}: {exc}", file=sys.stderr)


def normalize_degrees(value: int) -> int:
    return int(value) % 360


def rotation_label(degrees: int) -> str:
    normalized = normalize_degrees(degrees)
    return "360" if normalized == 0 else str(normalized)


def normalize_zoom(value: float) -> float:
    try:
        zoom = float(value)
    except (TypeError, ValueError):
        return ZOOM_LEVELS[0]
    if not np.isfinite(zoom):
        return ZOOM_LEVELS[0]
    return min(ZOOM_LEVELS, key=lambda level: abs(level - zoom))


def zoom_label(value: float) -> str:
    return f"{normalize_zoom(value):.1f}x"


def step_zoom(value: float, delta: int) -> float:
    current = normalize_zoom(value)
    index = min(range(len(ZOOM_LEVELS)), key=lambda i: abs(ZOOM_LEVELS[i] - current))
    next_index = min(max(index + delta, 0), len(ZOOM_LEVELS) - 1)
    return ZOOM_LEVELS[next_index]


def view_size(args: argparse.Namespace) -> Tuple[int, int]:
    return args.window_width - args.panel_width, args.window_height


def fit_to_view(
    frame: np.ndarray,
    width: int,
    height: int,
    interpolation: int = cv2.INTER_AREA,
) -> Tuple[np.ndarray, float, int, int]:
    source_h, source_w = frame.shape[:2]
    scale = min(width / source_w, height / source_h)
    resized_w = max(1, int(round(source_w * scale)))
    resized_h = max(1, int(round(source_h * scale)))
    resized = cv2.resize(frame, (resized_w, resized_h), interpolation=interpolation)

    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    x_offset = (width - resized_w) // 2
    y_offset = (height - resized_h) // 2
    canvas[y_offset : y_offset + resized_h, x_offset : x_offset + resized_w] = resized
    return canvas, scale, x_offset, y_offset


def crop_frame(
    frame: np.ndarray,
    width_ratio: float,
    height_ratio: float,
    offset_x: int,
    offset_y: int,
) -> np.ndarray:
    height, width = frame.shape[:2]
    width_ratio = max(0.1, min(1.0, width_ratio))
    height_ratio = max(0.1, min(1.0, height_ratio))
    crop_w = max(1, min(width, int(round(width * width_ratio))))
    crop_h = max(1, min(height, int(round(height * height_ratio))))

    center_x = width // 2 + offset_x
    center_y = height // 2 + offset_y
    x0 = max(0, min(width - crop_w, center_x - crop_w // 2))
    y0 = max(0, min(height - crop_h, center_y - crop_h // 2))
    return frame[y0 : y0 + crop_h, x0 : x0 + crop_w]


def crop_center_for_zoom(frame: np.ndarray, zoom_level: float) -> np.ndarray:
    zoom = normalize_zoom(zoom_level)
    if zoom <= 1.0:
        return frame

    height, width = frame.shape[:2]
    crop_w = max(1, int(round(width / zoom)))
    crop_h = max(1, int(round(height / zoom)))
    x0 = max(0, (width - crop_w) // 2)
    y0 = max(0, (height - crop_h) // 2)
    return frame[y0 : y0 + crop_h, x0 : x0 + crop_w]


def rotate_image_bound(
    frame: np.ndarray,
    degrees: int,
    interpolation: int = cv2.INTER_AREA,
    border_value: Union[int, Tuple[int, int, int]] = 0,
) -> np.ndarray:
    normalized = normalize_degrees(degrees)
    if normalized == 0:
        return frame

    height, width = frame.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, -normalized, 1.0)
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    rotated_width = int(round((height * sin) + (width * cos)))
    rotated_height = int(round((height * cos) + (width * sin)))
    matrix[0, 2] += (rotated_width / 2.0) - center[0]
    matrix[1, 2] += (rotated_height / 2.0) - center[1]
    return cv2.warpAffine(
        frame,
        matrix,
        (rotated_width, rotated_height),
        flags=interpolation,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border_value,
    )


def resize_to_view(
    frame: np.ndarray,
    width: int,
    height: int,
    interpolation: int = cv2.INTER_AREA,
) -> np.ndarray:
    return cv2.resize(frame, (width, height), interpolation=interpolation)


def apply_view_transform(
    view: np.ndarray,
    args: argparse.Namespace,
    rotation_degrees: int,
    zoom_level: float,
    interpolation: int = cv2.INTER_AREA,
) -> np.ndarray:
    view_width, view_height = view_size(args)
    transformed = crop_center_for_zoom(view, zoom_level)
    transformed = rotate_image_bound(
        transformed,
        rotation_degrees,
        interpolation=interpolation,
        border_value=(0, 0, 0),
    )
    return resize_to_view(transformed, view_width, view_height, interpolation=interpolation)


def apply_mask_transform(
    mask: np.ndarray,
    args: argparse.Namespace,
    rotation_degrees: int,
    zoom_level: float,
) -> np.ndarray:
    view_width, view_height = view_size(args)
    mask_img = (mask.astype(np.uint8) * 255)
    transformed = crop_center_for_zoom(mask_img, zoom_level)
    transformed = rotate_image_bound(
        transformed,
        rotation_degrees,
        interpolation=cv2.INTER_NEAREST,
        border_value=0,
    )
    transformed = cv2.resize(
        transformed,
        (view_width, view_height),
        interpolation=cv2.INTER_NEAREST,
    )
    return transformed > 0


def shift_with_mask(frame: np.ndarray, offset_x: int, offset_y: int) -> Tuple[np.ndarray, np.ndarray]:
    height, width = frame.shape[:2]
    shifted = np.zeros_like(frame)
    mask = np.zeros((height, width), dtype=bool)

    src_x0 = max(0, -offset_x)
    src_y0 = max(0, -offset_y)
    dst_x0 = max(0, offset_x)
    dst_y0 = max(0, offset_y)
    copy_w = min(width - src_x0, width - dst_x0)
    copy_h = min(height - src_y0, height - dst_y0)
    if copy_w <= 0 or copy_h <= 0:
        return shifted, mask

    shifted[dst_y0 : dst_y0 + copy_h, dst_x0 : dst_x0 + copy_w] = frame[
        src_y0 : src_y0 + copy_h,
        src_x0 : src_x0 + copy_w,
    ]
    mask[dst_y0 : dst_y0 + copy_h, dst_x0 : dst_x0 + copy_w] = True
    return shifted, mask


def draw_text(frame: np.ndarray, text: str, position: Tuple[int, int]) -> None:
    cv2.putText(
        frame,
        text,
        position,
        cv2.FONT_HERSHEY_SIMPLEX,
        0.46,
        (0, 0, 0),
        3,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        text,
        position,
        cv2.FONT_HERSHEY_SIMPLEX,
        0.46,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )


def draw_panel_text(
    frame: np.ndarray,
    text: str,
    position: Tuple[int, int],
    font_scale: float = 0.43,
    color: Tuple[int, int, int] = (235, 235, 235),
    thickness: int = 1,
) -> None:
    cv2.putText(
        frame,
        text,
        position,
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


def draw_panel_rule(frame: np.ndarray, x: int, y: int, width: int) -> None:
    cv2.line(frame, (x, y), (x + width, y), (68, 68, 68), 1)


def draw_section_label(frame: np.ndarray, text: str, position: Tuple[int, int]) -> None:
    draw_panel_text(frame, text, position, font_scale=0.34, color=(165, 172, 168))


def draw_button(
    frame: np.ndarray,
    rect: Rect,
    label: str,
    active: bool = True,
    style: str = "neutral",
) -> None:
    x, y, width, height = rect
    palette = {
        "neutral": ((54, 58, 62), (110, 118, 122), (245, 245, 245)),
        "primary": ((55, 96, 72), (112, 196, 132), (255, 255, 255)),
        "danger": ((80, 52, 52), (190, 112, 112), (255, 255, 255)),
    }
    fill, border, text_color = palette.get(style, palette["neutral"])
    if not active:
        fill, border, text_color = (42, 42, 42), (80, 80, 80), (145, 145, 145)
    cv2.rectangle(frame, (x, y), (x + width, y + height), fill, -1)
    cv2.rectangle(frame, (x, y), (x + width, y + height), border, 1)

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.46
    thickness = 1
    text_w, text_h = cv2.getTextSize(label, font, font_scale, thickness)[0]
    while text_w > width - 8 and font_scale > 0.32:
        font_scale -= 0.02
        text_w, text_h = cv2.getTextSize(label, font, font_scale, thickness)[0]
    text_x = x + max(0, (width - text_w) // 2)
    text_y = y + max(text_h + 2, (height + text_h) // 2)
    cv2.putText(
        frame,
        label,
        (text_x, text_y),
        font,
        font_scale,
        text_color,
        thickness,
        cv2.LINE_AA,
    )


def point_in_rect(point: Tuple[int, int], rect: Rect) -> bool:
    x, y = point
    rect_x, rect_y, rect_w, rect_h = rect
    return rect_x <= x <= rect_x + rect_w and rect_y <= y <= rect_y + rect_h


def viewer_buttons(args: argparse.Namespace) -> Dict[str, Rect]:
    panel_x = args.window_width - args.panel_width
    margin = 10
    button_w = max(1, args.panel_width - margin * 2)
    gap = 6
    half_w = max(1, (button_w - gap) // 2)
    return {
        "csi": (panel_x + margin, 82, button_w, 19),
        "csi_rotate_left": (panel_x + margin, 104, half_w, 18),
        "csi_rotate_right": (panel_x + margin + half_w + gap, 104, half_w, 18),
        "csi_zoom_out": (panel_x + margin, 124, half_w, 18),
        "csi_zoom_in": (panel_x + margin + half_w + gap, 124, half_w, 18),
        "thermal": (panel_x + margin, 156, button_w, 19),
        "thermal_rotate_left": (panel_x + margin, 178, half_w, 18),
        "thermal_rotate_right": (panel_x + margin + half_w + gap, 178, half_w, 18),
        "thermal_zoom_out": (panel_x + margin, 198, half_w, 18),
        "thermal_zoom_in": (panel_x + margin + half_w + gap, 198, half_w, 18),
        "thermal_nudge_up": (panel_x + margin + half_w // 2, 228, half_w, 18),
        "thermal_nudge_left": (panel_x + margin, 248, half_w, 18),
        "thermal_nudge_right": (panel_x + margin + half_w + gap, 248, half_w, 18),
        "thermal_nudge_down": (panel_x + margin + half_w // 2, 268, half_w, 18),
        "capture": (panel_x + margin, 292, half_w, 22),
        "exit": (panel_x + margin + half_w + gap, 292, half_w, 22),
    }


def status_message(state: ViewerState) -> str:
    if state.message and time.monotonic() < state.message_until:
        return state.message
    if state.csi_on and state.thermal_on:
        return "Fusing"
    if state.csi_on:
        return "CSI only"
    if state.thermal_on:
        return "Thermal only"
    return "Cameras off"


def draw_control_panel(
    frame: np.ndarray,
    args: argparse.Namespace,
    state: ViewerState,
    fps: float,
    thermal_config: LeptonConfig,
) -> None:
    panel_x = args.window_width - args.panel_width
    margin = 10
    content_x = panel_x + margin
    content_w = max(1, args.panel_width - margin * 2)
    cv2.rectangle(frame, (panel_x, 0), (args.window_width, args.window_height), (28, 28, 28), -1)
    cv2.line(frame, (panel_x, 0), (panel_x, args.window_height), (76, 76, 76), 1)

    draw_panel_text(frame, "FUSION", (content_x, 18), font_scale=0.48, color=(245, 245, 245))
    state_color = (122, 216, 142) if state.csi_on and state.thermal_on else (220, 188, 112)
    if not state.csi_on and not state.thermal_on:
        state_color = (165, 165, 165)
    draw_panel_text(
        frame,
        status_message(state)[:8].upper(),
        (content_x, 36),
        font_scale=0.36,
        color=state_color,
    )
    draw_panel_text(frame, f"FPS {fps:.1f}" if fps > 0 else "FPS --", (content_x, 52), font_scale=0.34)
    draw_panel_text(
        frame,
        f"A {args.alpha:.2f} SPI {thermal_config.spi_bus}.{thermal_config.spi_device}",
        (content_x, 67),
        font_scale=0.32,
        color=(178, 178, 178),
    )
    draw_panel_rule(frame, content_x, 72, content_w)

    buttons = viewer_buttons(args)
    draw_section_label(
        frame,
        f"CSI R{rotation_label(state.csi_rotation_degrees)} Z{zoom_label(state.csi_zoom_level)}",
        (content_x, 78),
    )
    draw_button(
        frame,
        buttons["csi"],
        "CSI Off" if state.csi_on else "CSI On",
        active=True,
        style="danger" if state.csi_on else "primary",
    )
    draw_button(frame, buttons["csi_rotate_left"], "R<", active=True, style="neutral")
    draw_button(frame, buttons["csi_rotate_right"], "R>", active=True, style="neutral")
    draw_button(
        frame,
        buttons["csi_zoom_out"],
        "Z-",
        active=normalize_zoom(state.csi_zoom_level) > ZOOM_LEVELS[0],
        style="neutral",
    )
    draw_button(
        frame,
        buttons["csi_zoom_in"],
        "Z+",
        active=normalize_zoom(state.csi_zoom_level) < ZOOM_LEVELS[-1],
        style="neutral",
    )

    draw_section_label(
        frame,
        f"THM R{rotation_label(state.thermal_rotation_degrees)} Z{zoom_label(state.thermal_zoom_level)}",
        (content_x, 152),
    )
    draw_button(
        frame,
        buttons["thermal"],
        "THM Off" if state.thermal_on else "THM On",
        active=True,
        style="danger" if state.thermal_on else "primary",
    )
    draw_button(frame, buttons["thermal_rotate_left"], "R<", active=True, style="neutral")
    draw_button(frame, buttons["thermal_rotate_right"], "R>", active=True, style="neutral")
    draw_button(
        frame,
        buttons["thermal_zoom_out"],
        "Z-",
        active=normalize_zoom(state.thermal_zoom_level) > ZOOM_LEVELS[0],
        style="neutral",
    )
    draw_button(
        frame,
        buttons["thermal_zoom_in"],
        "Z+",
        active=normalize_zoom(state.thermal_zoom_level) < ZOOM_LEVELS[-1],
        style="neutral",
    )
    draw_section_label(
        frame,
        f"ALIGN X{state.thermal_offset_x:+d} Y{state.thermal_offset_y:+d}",
        (content_x, 224),
    )
    draw_button(frame, buttons["thermal_nudge_up"], "^", active=True, style="neutral")
    draw_button(frame, buttons["thermal_nudge_left"], "<", active=True, style="neutral")
    draw_button(frame, buttons["thermal_nudge_right"], ">", active=True, style="neutral")
    draw_button(frame, buttons["thermal_nudge_down"], "v", active=True, style="neutral")
    draw_button(
        frame,
        buttons["capture"],
        "Capture",
        active=state.last_fused_view is not None,
        style="primary",
    )
    draw_button(frame, buttons["exit"], "Exit", active=True, style="danger")


def apply_optional_thermal_flip(raw: np.ndarray, flip_code: str) -> np.ndarray:
    value = str(flip_code).strip().lower()
    if value in ("", "none"):
        return raw
    if value in ("-1", "180", "rotate180", "rotate-180"):
        return cv2.rotate(raw, cv2.ROTATE_180)
    return cv2.flip(raw, int(value))


def auto_color_range(temps_c: np.ndarray, args: argparse.Namespace) -> Tuple[float, float]:
    if args.thermal_min_c is not None and args.thermal_max_c is not None:
        return args.thermal_min_c, args.thermal_max_c

    low = float(np.percentile(temps_c, args.thermal_low_percentile))
    high = float(np.percentile(temps_c, args.thermal_high_percentile))
    if args.thermal_min_c is not None:
        low = args.thermal_min_c
    if args.thermal_max_c is not None:
        high = args.thermal_max_c
    if high <= low:
        return low, low + 1.0

    sensitivity = max(args.thermal_sensitivity, 0.1)
    center = (low + high) / 2.0
    half_span = (high - low) / (2.0 * sensitivity)
    return center - half_span, center + half_span


def render_camera_view(
    camera_frame: Optional[np.ndarray],
    args: argparse.Namespace,
    state: ViewerState,
) -> np.ndarray:
    view_width, view_height = view_size(args)
    if camera_frame is None:
        view = np.zeros((view_height, view_width, 3), dtype=np.uint8)
        draw_text(view, "CSI Off", (max(12, view_width // 2 - 40), view_height // 2))
        return view

    view, _, _, _ = fit_to_view(camera_frame, view_width, view_height, interpolation=cv2.INTER_AREA)
    if not args.no_overlay:
        height, width = camera_frame.shape[:2]
        draw_text(view, f"CSI {width}x{height}", (10, 22))
    return apply_view_transform(
        view,
        args,
        state.csi_rotation_degrees,
        state.csi_zoom_level,
        interpolation=cv2.INTER_AREA,
    )


def render_aligned_camera_view(
    camera_frame: np.ndarray,
    args: argparse.Namespace,
    state: ViewerState,
) -> np.ndarray:
    view_width, view_height = view_size(args)
    cropped = crop_frame(
        camera_frame,
        args.visible_crop_width_ratio,
        args.visible_crop_height_ratio,
        args.visible_offset_x,
        args.visible_offset_y,
    )
    view = resize_to_view(cropped, view_width, view_height, interpolation=cv2.INTER_AREA)
    if not args.no_overlay:
        height, width = cropped.shape[:2]
        draw_text(view, f"CSI crop {width}x{height}", (10, 22))
    return apply_view_transform(
        view,
        args,
        state.csi_rotation_degrees,
        state.csi_zoom_level,
        interpolation=cv2.INTER_AREA,
    )


def render_thermal_view(
    raw: Optional[np.ndarray],
    args: argparse.Namespace,
    state: ViewerState,
) -> np.ndarray:
    view_width, view_height = view_size(args)
    if raw is None:
        view = np.zeros((view_height, view_width, 3), dtype=np.uint8)
        draw_text(view, "Thermal Off", (max(12, view_width // 2 - 54), view_height // 2))
        return view

    raw = apply_optional_thermal_flip(raw, args.thermal_flip_code)
    temps_c = tlinear_to_celsius(raw, scale=args.tlinear_scale)
    min_temp, max_temp, min_loc, max_loc = cv2.minMaxLoc(temps_c)
    low, high = auto_color_range(temps_c, args)

    normalized = ((temps_c - low) * 255.0) / (high - low)
    normalized = np.clip(normalized, 0, 255).astype(np.uint8)
    colored = cv2.applyColorMap(normalized, cv2.COLORMAP_JET)
    view, scale, x_offset, y_offset = fit_to_view(
        colored,
        view_width,
        view_height,
        interpolation=cv2.INTER_NEAREST,
    )

    if not args.no_overlay:
        max_pt = (
            int(round(x_offset + (max_loc[0] + 0.5) * scale)),
            int(round(y_offset + (max_loc[1] + 0.5) * scale)),
        )
        min_pt = (
            int(round(x_offset + (min_loc[0] + 0.5) * scale)),
            int(round(y_offset + (min_loc[1] + 0.5) * scale)),
        )
        cv2.circle(view, max_pt, 7, (0, 0, 255), 2)
        cv2.circle(view, min_pt, 7, (255, 255, 255), 2)
        draw_text(view, f"HIGH {max_temp:.1f}C", (10, view_height - 34))
        draw_text(view, f"LOW {min_temp:.1f}C", (10, view_height - 12))
    return apply_view_transform(
        view,
        args,
        state.thermal_rotation_degrees,
        state.thermal_zoom_level,
        interpolation=cv2.INTER_NEAREST,
    )


def thermal_colormap(raw: np.ndarray, args: argparse.Namespace) -> Tuple[np.ndarray, float, float, Tuple[int, int], Tuple[int, int]]:
    raw = apply_optional_thermal_flip(raw, args.thermal_flip_code)
    temps_c = tlinear_to_celsius(raw, scale=args.tlinear_scale)
    min_temp, max_temp, min_loc, max_loc = cv2.minMaxLoc(temps_c)
    low, high = auto_color_range(temps_c, args)

    normalized = ((temps_c - low) * 255.0) / (high - low)
    normalized = np.clip(normalized, 0, 255).astype(np.uint8)
    return cv2.applyColorMap(normalized, cv2.COLORMAP_JET), min_temp, max_temp, min_loc, max_loc


def render_aligned_thermal_overlay(
    raw: np.ndarray,
    args: argparse.Namespace,
    state: ViewerState,
) -> Tuple[np.ndarray, np.ndarray, float, float, Tuple[int, int], Tuple[int, int]]:
    view_width, view_height = view_size(args)
    colored, min_temp, max_temp, min_loc, max_loc = thermal_colormap(raw, args)
    view = resize_to_view(colored, view_width, view_height, interpolation=cv2.INTER_NEAREST)
    view, mask = shift_with_mask(view, state.thermal_offset_x, state.thermal_offset_y)
    view = apply_view_transform(
        view,
        args,
        state.thermal_rotation_degrees,
        state.thermal_zoom_level,
        interpolation=cv2.INTER_NEAREST,
    )
    mask = apply_mask_transform(
        mask,
        args,
        state.thermal_rotation_degrees,
        state.thermal_zoom_level,
    )
    return view, mask, min_temp, max_temp, min_loc, max_loc


def draw_aligned_thermal_labels(
    frame: np.ndarray,
    args: argparse.Namespace,
    state: ViewerState,
    min_temp: float,
    max_temp: float,
    min_loc: Tuple[int, int],
    max_loc: Tuple[int, int],
) -> None:
    if args.no_overlay:
        return

    view_width, view_height = view_size(args)
    scale_x = view_width / 80.0
    scale_y = view_height / 60.0
    max_pt = (
        int(round((max_loc[0] + 0.5) * scale_x + state.thermal_offset_x)),
        int(round((max_loc[1] + 0.5) * scale_y + state.thermal_offset_y)),
    )
    min_pt = (
        int(round((min_loc[0] + 0.5) * scale_x + state.thermal_offset_x)),
        int(round((min_loc[1] + 0.5) * scale_y + state.thermal_offset_y)),
    )
    if 0 <= max_pt[0] < view_width and 0 <= max_pt[1] < view_height:
        cv2.circle(frame, max_pt, 7, (0, 0, 255), 2)
    if 0 <= min_pt[0] < view_width and 0 <= min_pt[1] < view_height:
        cv2.circle(frame, min_pt, 7, (255, 255, 255), 2)
    draw_text(frame, f"HIGH {max_temp:.1f}C", (10, view_height - 34))
    draw_text(frame, f"LOW {min_temp:.1f}C", (10, view_height - 12))


def create_fused_view(
    camera_frame: Optional[np.ndarray],
    thermal_raw: Optional[np.ndarray],
    args: argparse.Namespace,
    state: ViewerState,
) -> np.ndarray:
    if state.csi_on and camera_frame is not None and state.thermal_on and thermal_raw is not None:
        alpha = max(0.0, min(1.0, args.alpha))
        camera_view = render_aligned_camera_view(camera_frame, args, state)
        thermal_view, mask, min_temp, max_temp, min_loc, max_loc = render_aligned_thermal_overlay(
            thermal_raw,
            args,
            state,
        )
        blended_full = cv2.addWeighted(camera_view, 1.0 - alpha, thermal_view, alpha, 0.0)
        fused = camera_view.copy()
        fused[mask] = blended_full[mask]
        if (
            normalize_degrees(state.thermal_rotation_degrees) == 0
            and normalize_zoom(state.thermal_zoom_level) == ZOOM_LEVELS[0]
        ):
            draw_aligned_thermal_labels(fused, args, state, min_temp, max_temp, min_loc, max_loc)
        return fused
    if state.csi_on and camera_frame is not None:
        return render_camera_view(camera_frame, args, state)
    if state.thermal_on and thermal_raw is not None:
        return render_thermal_view(thermal_raw, args, state)

    view_width, view_height = view_size(args)
    view = np.zeros((view_height, view_width, 3), dtype=np.uint8)
    draw_text(view, "Fusion Idle", (max(12, view_width // 2 - 55), view_height // 2))
    return view

def render_window(
    fused_view: np.ndarray,
    args: argparse.Namespace,
    state: ViewerState,
    fps: float,
    thermal_config: LeptonConfig,
) -> np.ndarray:
    view_width, _ = view_size(args)
    frame = np.zeros((args.window_height, args.window_width, 3), dtype=np.uint8)
    frame[:, :view_width] = fused_view
    draw_control_panel(frame, args, state, fps, thermal_config)
    return frame


def message_frame(
    title: str,
    subtitle: str,
    args: argparse.Namespace,
    state: ViewerState,
    thermal_config: LeptonConfig,
) -> np.ndarray:
    view_width, view_height = view_size(args)
    view = np.zeros((view_height, view_width, 3), dtype=np.uint8)
    draw_text(view, title, (max(12, view_width // 2 - 72), view_height // 2 - 8))
    draw_text(view, subtitle, (max(12, view_width // 2 - 86), view_height // 2 + 18))
    return render_window(view, args, state, 0.0, thermal_config)


def error_view(message: str, args: argparse.Namespace) -> np.ndarray:
    view_width, view_height = view_size(args)
    view = np.zeros((view_height, view_width, 3), dtype=np.uint8)
    lines = ("Fusion error", message[:54], "Use Exit to quit")
    for index, line in enumerate(lines):
        draw_text(view, line, (16, view_height // 2 - 22 + index * 22))
    return view


def save_capture(frame: np.ndarray, results_dir: str, quality: int) -> Path:
    output_dir = Path(results_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"fusion_{time.strftime('%Y%m%d%H%M%S')}.jpg"

    ok = cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise OSError(f"Unable to write JPEG capture: {path}")
    return path


def window_exists(window_name: str) -> bool:
    try:
        return cv2.getWindowProperty(window_name, cv2.WND_PROP_AUTOSIZE) >= 0
    except cv2.error:
        return False


def window_visible(window_name: str) -> bool:
    try:
        visible = cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE)
        if visible < 0:
            return window_exists(window_name)
        return visible >= 1
    except cv2.error:
        return False


def read_window_key(delay_ms: int = 1) -> int:
    try:
        return cv2.waitKey(delay_ms) & 0xFF
    except cv2.error:
        return 255


def raise_window(window_name: str) -> None:
    try:
        cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)
        cv2.waitKey(1)
        cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 0)
    except cv2.error:
        pass


def on_mouse(event, x, y, flags, param) -> None:
    if event != cv2.EVENT_LBUTTONUP:
        return

    args, state = param
    buttons = viewer_buttons(args)
    if point_in_rect((x, y), buttons["csi"]):
        state.toggle_csi_requested = True
    elif point_in_rect((x, y), buttons["thermal"]):
        state.toggle_thermal_requested = True
    elif point_in_rect((x, y), buttons["csi_rotate_left"]):
        state.csi_rotation_delta_requested -= 90
    elif point_in_rect((x, y), buttons["csi_rotate_right"]):
        state.csi_rotation_delta_requested += 90
    elif point_in_rect((x, y), buttons["csi_zoom_out"]):
        state.csi_zoom_delta_requested -= 1
    elif point_in_rect((x, y), buttons["csi_zoom_in"]):
        state.csi_zoom_delta_requested += 1
    elif point_in_rect((x, y), buttons["thermal_rotate_left"]):
        state.thermal_rotation_delta_requested -= 90
    elif point_in_rect((x, y), buttons["thermal_rotate_right"]):
        state.thermal_rotation_delta_requested += 90
    elif point_in_rect((x, y), buttons["thermal_zoom_out"]):
        state.thermal_zoom_delta_requested -= 1
    elif point_in_rect((x, y), buttons["thermal_zoom_in"]):
        state.thermal_zoom_delta_requested += 1
    elif point_in_rect((x, y), buttons["thermal_nudge_up"]):
        state.thermal_offset_delta_y_requested -= THERMAL_OFFSET_NUDGE_PIXELS
    elif point_in_rect((x, y), buttons["thermal_nudge_left"]):
        state.thermal_offset_delta_x_requested -= THERMAL_OFFSET_NUDGE_PIXELS
    elif point_in_rect((x, y), buttons["thermal_nudge_right"]):
        state.thermal_offset_delta_x_requested += THERMAL_OFFSET_NUDGE_PIXELS
    elif point_in_rect((x, y), buttons["thermal_nudge_down"]):
        state.thermal_offset_delta_y_requested += THERMAL_OFFSET_NUDGE_PIXELS
    elif point_in_rect((x, y), buttons["capture"]):
        state.capture_requested = True
    elif point_in_rect((x, y), buttons["exit"]):
        state.quit_requested = True


def run_viewer(args: argparse.Namespace) -> None:
    camera_config = build_camera_config(args)
    thermal_config = fallback_thermal_config(args)
    camera: Optional[IMX219Camera] = None
    thermal: Optional[FLIRLepton25] = None

    try:
        cv2.startWindowThread()
    except cv2.error:
        pass
    cv2.namedWindow(args.window_name, cv2.WINDOW_NORMAL)
    print(f"Created OpenCV window '{args.window_name}'", flush=True)
    cv2.resizeWindow(args.window_name, args.window_width, args.window_height)
    cv2.moveWindow(args.window_name, 160, 160)
    raise_window(args.window_name)
    state = ViewerState(
        csi_rotation_degrees=normalize_degrees(args.csi_rotation_degrees),
        csi_zoom_level=normalize_zoom(args.csi_zoom_level),
        thermal_rotation_degrees=normalize_degrees(args.thermal_rotation_degrees),
        thermal_zoom_level=normalize_zoom(args.thermal_zoom_level),
        thermal_offset_x=int(args.thermal_offset_x),
        thermal_offset_y=int(args.thermal_offset_y),
    )
    cv2.setMouseCallback(args.window_name, on_mouse, (args, state))
    state.set_message("Starting")

    last_time = time.monotonic()
    fps = 0.0
    try:
        cv2.imshow(
            args.window_name,
            message_frame("Starting Fusion", "Opening cameras", args, state, thermal_config),
        )
        raise_window(args.window_name)
        for _ in range(20):
            key = read_window_key(50)
            if key in (ord("q"), 27) or not window_exists(args.window_name):
                print("OpenCV window closed during startup.", flush=True)
                return
        print("OpenCV window startup completed.", flush=True)

        while True:
            key = read_window_key(1)
            if key in (ord("q"), 27):
                print("Keyboard exit requested.", flush=True)
                break
            if not window_visible(args.window_name):
                print("OpenCV window closed.", flush=True)
                break

            if state.quit_requested:
                print("Exit requested from control panel.", flush=True)
                break

            if state.toggle_csi_requested:
                state.toggle_csi_requested = False
                state.csi_on = not state.csi_on
                state.set_message("CSI on" if state.csi_on else "CSI off")
                if not state.csi_on and camera is not None:
                    camera.release()
                    camera = None

            if state.toggle_thermal_requested:
                state.toggle_thermal_requested = False
                state.thermal_on = not state.thermal_on
                state.set_message("Thermal on" if state.thermal_on else "Thermal off")
                if not state.thermal_on and thermal is not None:
                    thermal.release()
                    thermal = None

            if state.csi_rotation_delta_requested:
                state.csi_rotation_degrees = normalize_degrees(
                    state.csi_rotation_degrees + state.csi_rotation_delta_requested
                )
                state.csi_rotation_delta_requested = 0
                save_viewer_settings(args, state)
                state.set_message(f"CSI rot {rotation_label(state.csi_rotation_degrees)}")

            if state.csi_zoom_delta_requested:
                state.csi_zoom_level = step_zoom(state.csi_zoom_level, state.csi_zoom_delta_requested)
                state.csi_zoom_delta_requested = 0
                save_viewer_settings(args, state)
                state.set_message(f"CSI zoom {zoom_label(state.csi_zoom_level)}")

            if state.thermal_rotation_delta_requested:
                state.thermal_rotation_degrees = normalize_degrees(
                    state.thermal_rotation_degrees + state.thermal_rotation_delta_requested
                )
                state.thermal_rotation_delta_requested = 0
                save_viewer_settings(args, state)
                state.set_message(f"THM rot {rotation_label(state.thermal_rotation_degrees)}")

            if state.thermal_zoom_delta_requested:
                state.thermal_zoom_level = step_zoom(
                    state.thermal_zoom_level,
                    state.thermal_zoom_delta_requested,
                )
                state.thermal_zoom_delta_requested = 0
                save_viewer_settings(args, state)
                state.set_message(f"THM zoom {zoom_label(state.thermal_zoom_level)}")

            if state.thermal_offset_delta_x_requested or state.thermal_offset_delta_y_requested:
                state.thermal_offset_x += state.thermal_offset_delta_x_requested
                state.thermal_offset_y += state.thermal_offset_delta_y_requested
                state.thermal_offset_delta_x_requested = 0
                state.thermal_offset_delta_y_requested = 0
                save_viewer_settings(args, state)
                state.set_message(f"THM X{state.thermal_offset_x:+d} Y{state.thermal_offset_y:+d}")

            if state.reset_thermal_requested:
                state.reset_thermal_requested = False
                state.set_message("Resetting FLIR")
                print("FLIR reset requested from fusion control panel.", flush=True)
                if thermal is None:
                    thermal = FLIRLepton25(thermal_config)
                try:
                    thermal.reset(reopen=False)
                    thermal = None
                    state.thermal_on = True
                    state.last_thermal_raw = None
                    fps = 0.0
                    state.set_message("FLIR reset")
                except (ThermalError, RuntimeError) as exc:
                    print(f"FLIR reset error: {exc}", file=sys.stderr, flush=True)
                    if thermal is not None:
                        thermal.release()
                        thermal = None
                    state.thermal_on = False
                    state.set_message("Reset failed")

            if state.csi_on:
                if camera is None:
                    camera = IMX219Camera(sensor_id=args.sensor_id, config=camera_config)
                    print(f"Using IMX219 sensor-id={args.sensor_id}", flush=True)
                    print(f"Pipeline: {camera.pipeline}", flush=True)
                try:
                    state.last_camera_frame = camera.get_frame()
                except (CameraError, RuntimeError) as exc:
                    print(f"CSI capture error: {exc}", file=sys.stderr, flush=True)
                    if camera is not None:
                        camera.release()
                        camera = None
                    state.csi_on = False
                    state.set_message("CSI error")
                    time.sleep(args.camera_error_sleep_s)
            else:
                if camera is not None:
                    camera.release()
                    camera = None

            if state.thermal_on:
                if thermal is None:
                    try:
                        state.set_message("Detecting FLIR")
                        thermal_config = build_thermal_config(args)
                        thermal = FLIRLepton25(thermal_config)
                        print(
                            f"Using /dev/spidev{thermal_config.spi_bus}.{thermal_config.spi_device} "
                            f"at {thermal_config.spi_speed_hz} Hz",
                            flush=True,
                        )
                    except ThermalError as exc:
                        print(f"FLIR setup error: {exc}", file=sys.stderr, flush=True)
                        state.thermal_on = False
                        state.set_message("Thermal setup error")
                        time.sleep(args.thermal_error_sleep_s)
                if thermal is not None:
                    try:
                        state.last_thermal_raw = thermal.get_raw_frame()
                    except (ThermalError, RuntimeError) as exc:
                        print(f"Thermal capture error: {exc}", file=sys.stderr, flush=True)
                        thermal.release()
                        thermal = None
                        state.thermal_on = False
                        state.set_message("Thermal error")
                        time.sleep(args.thermal_error_sleep_s)
            else:
                if thermal is not None:
                    thermal.release()
                    thermal = None

            fused_view = create_fused_view(
                state.last_camera_frame,
                state.last_thermal_raw,
                args,
                state,
            )
            state.last_fused_view = fused_view.copy()

            now = time.monotonic()
            elapsed = now - last_time
            last_time = now
            if elapsed > 0:
                instant_fps = 1.0 / elapsed
                fps = 0.8 * fps + 0.2 * instant_fps if fps > 0 else instant_fps

            if state.capture_requested:
                state.capture_requested = False
                if state.last_fused_view is None:
                    state.set_message("No frame yet")
                else:
                    try:
                        path = save_capture(state.last_fused_view, args.results_dir, args.jpeg_quality)
                        state.set_message(f"Saved {path.name}")
                        print(f"Saved {path}", flush=True)
                    except OSError as exc:
                        state.set_message(f"Save failed: {exc}")
                        print(f"Save failed: {exc}", file=sys.stderr, flush=True)

            frame = render_window(fused_view, args, state, fps, thermal_config)
            if not window_visible(args.window_name):
                print("OpenCV window closed.", flush=True)
                break
            cv2.imshow(args.window_name, frame)
            key = read_window_key(1)
            if key in (ord("q"), 27) or state.quit_requested or not window_visible(args.window_name):
                break
    finally:
        if camera is not None:
            camera.release()
        if thermal is not None:
            thermal.release()
        cv2.destroyAllWindows()


def main() -> int:
    args = build_parser().parse_args()
    settings = load_viewer_settings(args)
    fallback_rotation = settings.get("rotation_degrees", 0)
    if args.rotation_degrees is not None:
        fallback_rotation = args.rotation_degrees
    fallback_rotation = normalize_degrees(fallback_rotation)

    fallback_zoom = settings.get("zoom_level", 1.0)
    if args.zoom_level is not None:
        fallback_zoom = args.zoom_level
    fallback_zoom = normalize_zoom(fallback_zoom)

    if args.csi_rotation_degrees is None:
        args.csi_rotation_degrees = settings.get("csi_rotation_degrees", fallback_rotation)
    args.csi_rotation_degrees = normalize_degrees(args.csi_rotation_degrees)
    if args.csi_zoom_level is None:
        args.csi_zoom_level = settings.get("csi_zoom_level", fallback_zoom)
    args.csi_zoom_level = normalize_zoom(args.csi_zoom_level)

    if args.thermal_rotation_degrees is None:
        args.thermal_rotation_degrees = settings.get("thermal_rotation_degrees", fallback_rotation)
    args.thermal_rotation_degrees = normalize_degrees(args.thermal_rotation_degrees)
    if args.thermal_zoom_level is None:
        args.thermal_zoom_level = settings.get("thermal_zoom_level", fallback_zoom)
    args.thermal_zoom_level = normalize_zoom(args.thermal_zoom_level)
    if args.thermal_offset_x is None:
        args.thermal_offset_x = settings.get(
            "thermal_offset_x",
            env_int("FUSION_THERMAL_OFFSET_X", DEFAULT_THERMAL_OFFSET_X),
        )
    args.thermal_offset_x = int(args.thermal_offset_x)
    if args.thermal_offset_y is None:
        args.thermal_offset_y = settings.get(
            "thermal_offset_y",
            env_int("FUSION_THERMAL_OFFSET_Y", DEFAULT_THERMAL_OFFSET_Y),
        )
    args.thermal_offset_y = int(args.thermal_offset_y)

    if args.window_width <= 0 or args.window_height <= 0:
        print("Window width and height must be positive.", file=sys.stderr)
        return 2
    if args.panel_width < 112 or args.panel_width >= args.window_width:
        print("Panel width must be at least 112 and smaller than window width.", file=sys.stderr)
        return 2

    print(
        f"Opening {args.window_width}x{args.window_height} fusion viewer. "
        "Press q or Esc to quit.",
        flush=True,
    )
    try:
        run_viewer(args)
    except Exception as exc:
        print(f"Fusion viewer fatal error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    print("Fusion viewer exited.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
