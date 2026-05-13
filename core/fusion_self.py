"""Standalone 480x320 live fusion viewer for CSI and FLIR Lepton cameras."""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

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
DEFAULT_WINDOW_NAME = "GoVision Fusion Self"
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
DEFAULT_THERMAL_OFFSET_X = 0
DEFAULT_THERMAL_OFFSET_Y = -24
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "results"


Rect = Tuple[int, int, int, int]


@dataclass
class ViewerState:
    csi_on: bool = True
    thermal_on: bool = True
    toggle_csi_requested: bool = False
    toggle_thermal_requested: bool = False
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


def env_optional_float(name: str) -> Optional[float]:
    value = os.getenv(name)
    return None if value is None else float(value)


def env_int_optional(name: str) -> Optional[int]:
    value = os.getenv(name)
    return None if value is None else int(value)


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
        default=env_int("FUSION_THERMAL_OFFSET_X", DEFAULT_THERMAL_OFFSET_X),
        help="Thermal overlay x shift in final view pixels; positive moves right",
    )
    parser.add_argument(
        "--thermal-offset-y",
        type=int,
        default=env_int("FUSION_THERMAL_OFFSET_Y", DEFAULT_THERMAL_OFFSET_Y),
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

    parser.add_argument("--thermal-flip-code", default=os.getenv("FLIR_FLIP_CODE", "0"))
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
    )


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


def resize_to_view(
    frame: np.ndarray,
    width: int,
    height: int,
    interpolation: int = cv2.INTER_AREA,
) -> np.ndarray:
    return cv2.resize(frame, (width, height), interpolation=interpolation)


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


def draw_panel_text(frame: np.ndarray, text: str, position: Tuple[int, int]) -> None:
    cv2.putText(
        frame,
        text,
        position,
        cv2.FONT_HERSHEY_SIMPLEX,
        0.43,
        (235, 235, 235),
        1,
        cv2.LINE_AA,
    )


def draw_button(frame: np.ndarray, rect: Rect, label: str, active: bool = True) -> None:
    x, y, width, height = rect
    fill = (64, 92, 74) if active else (74, 74, 74)
    border = (118, 190, 132) if active else (150, 150, 150)
    cv2.rectangle(frame, (x, y), (x + width, y + height), fill, -1)
    cv2.rectangle(frame, (x, y), (x + width, y + height), border, 1)

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.48
    thickness = 1
    text_w, text_h = cv2.getTextSize(label, font, font_scale, thickness)[0]
    text_x = x + max(0, (width - text_w) // 2)
    text_y = y + max(text_h + 2, (height + text_h) // 2)
    cv2.putText(
        frame,
        label,
        (text_x, text_y),
        font,
        font_scale,
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )


def point_in_rect(point: Tuple[int, int], rect: Rect) -> bool:
    x, y = point
    rect_x, rect_y, rect_w, rect_h = rect
    return rect_x <= x <= rect_x + rect_w and rect_y <= y <= rect_y + rect_h


def viewer_buttons(args: argparse.Namespace) -> Dict[str, Rect]:
    panel_x = args.window_width - args.panel_width
    margin = 12
    button_w = max(1, args.panel_width - margin * 2)
    return {
        "csi": (panel_x + margin, 70, button_w, 34),
        "thermal": (panel_x + margin, 112, button_w, 34),
        "capture": (panel_x + margin, 164, button_w, 38),
        "exit": (panel_x + margin, args.window_height - 52, button_w, 38),
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
    cv2.rectangle(frame, (panel_x, 0), (args.window_width, args.window_height), (30, 30, 30), -1)
    cv2.line(frame, (panel_x, 0), (panel_x, args.window_height), (80, 80, 80), 1)

    draw_panel_text(frame, "FUSION", (panel_x + 12, 22))
    draw_panel_text(frame, f"CSI: {'On' if state.csi_on else 'Off'}", (panel_x + 12, 46))
    draw_panel_text(frame, f"THM: {'On' if state.thermal_on else 'Off'}", (panel_x + 12, 64))

    buttons = viewer_buttons(args)
    draw_button(frame, buttons["csi"], "CSI Off" if state.csi_on else "CSI On", active=state.csi_on)
    draw_button(
        frame,
        buttons["thermal"],
        "THM Off" if state.thermal_on else "THM On",
        active=state.thermal_on,
    )
    draw_button(frame, buttons["capture"], "Capture", active=state.last_fused_view is not None)
    draw_button(frame, buttons["exit"], "Exit", active=False)

    message = status_message(state)
    draw_panel_text(frame, message[:15], (panel_x + 12, 216))
    draw_panel_text(frame, f"FPS: {fps:.1f}" if fps > 0 else "FPS: --", (panel_x + 12, 234))
    draw_panel_text(frame, f"A:{args.alpha:.2f} Y:{args.thermal_offset_y:+d}", (panel_x + 12, 252))
    draw_panel_text(frame, f"SPI:{thermal_config.spi_bus}.{thermal_config.spi_device}", (panel_x + 12, 264))


def apply_optional_thermal_flip(raw: np.ndarray, flip_code: str) -> np.ndarray:
    value = str(flip_code).strip().lower()
    if value in ("", "none"):
        return raw
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


def render_camera_view(camera_frame: Optional[np.ndarray], args: argparse.Namespace) -> np.ndarray:
    view_width, view_height = view_size(args)
    if camera_frame is None:
        view = np.zeros((view_height, view_width, 3), dtype=np.uint8)
        draw_text(view, "CSI Off", (max(12, view_width // 2 - 40), view_height // 2))
        return view

    view, _, _, _ = fit_to_view(camera_frame, view_width, view_height, interpolation=cv2.INTER_AREA)
    if not args.no_overlay:
        height, width = camera_frame.shape[:2]
        draw_text(view, f"CSI {width}x{height}", (10, 22))
    return view


def render_aligned_camera_view(camera_frame: np.ndarray, args: argparse.Namespace) -> np.ndarray:
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
    return view


def render_thermal_view(raw: Optional[np.ndarray], args: argparse.Namespace) -> np.ndarray:
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
    return view


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
) -> Tuple[np.ndarray, np.ndarray, float, float, Tuple[int, int], Tuple[int, int]]:
    view_width, view_height = view_size(args)
    colored, min_temp, max_temp, min_loc, max_loc = thermal_colormap(raw, args)
    view = resize_to_view(colored, view_width, view_height, interpolation=cv2.INTER_NEAREST)
    view, mask = shift_with_mask(view, args.thermal_offset_x, args.thermal_offset_y)
    return view, mask, min_temp, max_temp, min_loc, max_loc


def draw_aligned_thermal_labels(
    frame: np.ndarray,
    args: argparse.Namespace,
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
        int(round((max_loc[0] + 0.5) * scale_x + args.thermal_offset_x)),
        int(round((max_loc[1] + 0.5) * scale_y + args.thermal_offset_y)),
    )
    min_pt = (
        int(round((min_loc[0] + 0.5) * scale_x + args.thermal_offset_x)),
        int(round((min_loc[1] + 0.5) * scale_y + args.thermal_offset_y)),
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
        camera_view = render_aligned_camera_view(camera_frame, args)
        thermal_view, mask, min_temp, max_temp, min_loc, max_loc = render_aligned_thermal_overlay(
            thermal_raw,
            args,
        )
        blended_full = cv2.addWeighted(camera_view, 1.0 - alpha, thermal_view, alpha, 0.0)
        fused = camera_view.copy()
        fused[mask] = blended_full[mask]
        draw_aligned_thermal_labels(fused, args, min_temp, max_temp, min_loc, max_loc)
        return fused
    if state.csi_on and camera_frame is not None:
        return render_camera_view(camera_frame, args)
    if state.thermal_on and thermal_raw is not None:
        return render_thermal_view(thermal_raw, args)

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
    state = ViewerState()
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
            cv2.waitKey(50)
            if not window_exists(args.window_name):
                print("OpenCV window closed during startup.", flush=True)
                return
        print("OpenCV window startup completed.", flush=True)

        while True:
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
            cv2.imshow(args.window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27) or state.quit_requested or not window_exists(args.window_name):
                break
    finally:
        if camera is not None:
            camera.release()
        if thermal is not None:
            thermal.release()
        cv2.destroyAllWindows()


def main() -> int:
    args = build_parser().parse_args()
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
