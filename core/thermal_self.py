"""Standalone 480x320 live viewer for the FLIR Lepton thermal camera."""

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
DEFAULT_WINDOW_NAME = "GoVision FLIR Self"
DEFAULT_PANEL_WIDTH = 128
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "results"


Rect = Tuple[int, int, int, int]


@dataclass
class ViewerState:
    camera_on: bool = True
    toggle_requested: bool = False
    capture_requested: bool = False
    quit_requested: bool = False
    last_raw: Optional[np.ndarray] = None
    last_frame: Optional[np.ndarray] = None
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open a 480x320 live FLIR Lepton thermal viewing window"
    )
    parser.add_argument("--window-name", default=os.getenv("FLIR_WINDOW_NAME", DEFAULT_WINDOW_NAME))
    parser.add_argument(
        "--window-width",
        type=int,
        default=env_int("FLIR_WINDOW_WIDTH", DEFAULT_WINDOW_WIDTH),
    )
    parser.add_argument(
        "--window-height",
        type=int,
        default=env_int("FLIR_WINDOW_HEIGHT", DEFAULT_WINDOW_HEIGHT),
    )
    parser.add_argument(
        "--panel-width",
        type=int,
        default=env_int("FLIR_PANEL_WIDTH", DEFAULT_PANEL_WIDTH),
    )
    parser.add_argument(
        "--results-dir",
        default=os.getenv("FLIR_RESULTS_DIR", str(DEFAULT_RESULTS_DIR)),
        help="Directory for Capture button JPEG output",
    )
    parser.add_argument("--flip-code", default=os.getenv("FLIR_FLIP_CODE", "0"))
    parser.add_argument("--min-c", type=float, default=env_optional_float("FLIR_MIN_C"))
    parser.add_argument("--max-c", type=float, default=env_optional_float("FLIR_MAX_C"))
    parser.add_argument("--auto-low-percentile", type=float, default=env_float("FLIR_LOW_PCT", 2.0))
    parser.add_argument("--auto-high-percentile", type=float, default=env_float("FLIR_HIGH_PCT", 98.0))
    parser.add_argument(
        "--sensitivity",
        type=float,
        default=env_float("FLIR_SENSITIVITY", 1.4),
        help="Narrow auto color range; higher values make smaller changes more visible",
    )
    parser.add_argument("--tlinear-scale", type=float, default=env_float("FLIR_TLINEAR_SCALE", 100.0))
    parser.add_argument("--no-overlay", action="store_true", help="Hide status text and hot/cold markers")
    parser.add_argument("--bus", type=int, default=None, help="Force SPI bus")
    parser.add_argument("--device", type=int, default=None, help="Force SPI device")
    parser.add_argument("--speed-hz", type=int, default=env_int("FLIR_SPI_SPEED_HZ", 18_000_000))
    parser.add_argument("--probe-speed-hz", type=int, default=env_int("FLIR_PROBE_SPEED_HZ", 2_000_000))
    parser.add_argument(
        "--candidates",
        default=os.getenv("FLIR_SPI_CANDIDATES", "0.0,0.1,1.0,1.1"),
        help="Comma-separated bus.device list for auto-detect",
    )
    parser.add_argument("--no-auto-detect", action="store_true")
    parser.add_argument("--max-frame-attempts", type=int, default=env_int("FLIR_MAX_FRAME_ATTEMPTS", 2))
    parser.add_argument("--max-sync-packets", type=int, default=env_int("FLIR_MAX_SYNC_PACKETS", 6_000))
    parser.add_argument("--resync-delay-s", type=float, default=env_float("FLIR_RESYNC_DELAY_S", 0.0))
    parser.add_argument("--error-sleep-s", type=float, default=env_float("FLIR_ERROR_SLEEP_S", 0.1))
    return parser


def build_config(args: argparse.Namespace) -> LeptonConfig:
    config = LeptonConfig(
        spi_bus=args.bus if args.bus is not None else env_int("FLIR_SPI_BUS", LeptonConfig.spi_bus),
        spi_device=args.device
        if args.device is not None
        else env_int("FLIR_SPI_DEVICE", LeptonConfig.spi_device),
        spi_speed_hz=args.speed_hz,
        max_frame_attempts=args.max_frame_attempts,
        max_sync_packets=args.max_sync_packets,
        resync_delay_s=args.resync_delay_s,
    )
    forced_spi = args.bus is not None or args.device is not None
    env_forced_spi = "FLIR_SPI_BUS" in os.environ or "FLIR_SPI_DEVICE" in os.environ

    if args.no_auto_detect or forced_spi or env_forced_spi:
        return config

    return config_with_detected_spidev(
        config,
        candidates=parse_spi_candidates(args.candidates),
        probe_speed_hz=args.probe_speed_hz,
    )


def fallback_config(args: argparse.Namespace) -> LeptonConfig:
    """Build a display-safe config without probing SPI."""

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


def apply_optional_flip(raw: np.ndarray, flip_code: str) -> np.ndarray:
    value = str(flip_code).strip().lower()
    if value in ("", "none"):
        return raw
    return cv2.flip(raw, int(value))


def auto_color_range(temps_c: np.ndarray, args: argparse.Namespace) -> Tuple[float, float]:
    if args.min_c is not None and args.max_c is not None:
        return args.min_c, args.max_c

    low = float(np.percentile(temps_c, args.auto_low_percentile))
    high = float(np.percentile(temps_c, args.auto_high_percentile))
    if args.min_c is not None:
        low = args.min_c
    if args.max_c is not None:
        high = args.max_c
    if high <= low:
        return low, low + 1.0

    sensitivity = max(args.sensitivity, 0.1)
    center = (low + high) / 2.0
    half_span = (high - low) / (2.0 * sensitivity)
    return center - half_span, center + half_span


def fit_to_window(frame: np.ndarray, width: int, height: int) -> Tuple[np.ndarray, float, int, int]:
    source_h, source_w = frame.shape[:2]
    scale = min(width / source_w, height / source_h)
    resized_w = max(1, int(round(source_w * scale)))
    resized_h = max(1, int(round(source_h * scale)))
    resized = cv2.resize(frame, (resized_w, resized_h), interpolation=cv2.INTER_NEAREST)

    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    x_offset = (width - resized_w) // 2
    y_offset = (height - resized_h) // 2
    canvas[y_offset : y_offset + resized_h, x_offset : x_offset + resized_w] = resized
    return canvas, scale, x_offset, y_offset


def thermal_view_size(args: argparse.Namespace) -> Tuple[int, int]:
    return args.window_width - args.panel_width, args.window_height


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
        "toggle": (panel_x + margin, 74, button_w, 42),
        "capture": (panel_x + margin, 130, button_w, 42),
        "exit": (panel_x + margin, args.window_height - 52, button_w, 38),
    }


def status_message(state: ViewerState) -> str:
    if state.message and time.monotonic() < state.message_until:
        return state.message
    return "Streaming" if state.camera_on else "Camera off"


def draw_control_panel(
    frame: np.ndarray,
    args: argparse.Namespace,
    config: LeptonConfig,
    state: ViewerState,
    fps: float,
) -> None:
    panel_x = args.window_width - args.panel_width
    cv2.rectangle(frame, (panel_x, 0), (args.window_width, args.window_height), (30, 30, 30), -1)
    cv2.line(frame, (panel_x, 0), (panel_x, args.window_height), (80, 80, 80), 1)

    draw_panel_text(frame, "FLIR", (panel_x + 12, 22))
    draw_panel_text(frame, f"Cam: {'On' if state.camera_on else 'Off'}", (panel_x + 12, 48))
    draw_panel_text(frame, f"FPS: {fps:.1f}" if fps > 0 else "FPS: --", (panel_x + 12, 66))

    buttons = viewer_buttons(args)
    draw_button(frame, buttons["toggle"], "Off" if state.camera_on else "On", active=state.camera_on)
    draw_button(frame, buttons["capture"], "Capture", active=state.last_frame is not None)
    draw_button(frame, buttons["exit"], "Exit", active=False)

    draw_panel_text(frame, f"SPI: {config.spi_bus}.{config.spi_device}", (panel_x + 12, 198))
    message = status_message(state)
    for index, chunk in enumerate(message[i : i + 15] for i in range(0, len(message), 15)):
        if index >= 4:
            break
        draw_panel_text(frame, chunk, (panel_x + 12, 224 + index * 18))


def map_point(point: Tuple[int, int], scale: float, x_offset: int, y_offset: int) -> Tuple[int, int]:
    return (
        int(round(x_offset + (point[0] + 0.5) * scale)),
        int(round(y_offset + (point[1] + 0.5) * scale)),
    )


def render_thermal_view(raw: np.ndarray, args: argparse.Namespace) -> np.ndarray:
    raw = apply_optional_flip(raw, args.flip_code)
    temps_c = tlinear_to_celsius(raw, scale=args.tlinear_scale)
    min_temp, max_temp, min_loc, max_loc = cv2.minMaxLoc(temps_c)
    low, high = auto_color_range(temps_c, args)

    normalized = ((temps_c - low) * 255.0) / (high - low)
    normalized = np.clip(normalized, 0, 255).astype(np.uint8)
    colored = cv2.applyColorMap(normalized, cv2.COLORMAP_JET)
    view_width, view_height = thermal_view_size(args)
    view, scale, x_offset, y_offset = fit_to_window(colored, view_width, view_height)

    if not args.no_overlay:
        low_pt = map_point(min_loc, scale, x_offset, y_offset)
        high_pt = map_point(max_loc, scale, x_offset, y_offset)
        cv2.circle(view, low_pt, 7, (255, 255, 255), 2)
        cv2.circle(view, high_pt, 7, (0, 0, 255), 2)
        draw_text(view, f"LOW {min_temp:.1f}C", (10, view_height - 34))
        draw_text(view, f"HIGH {max_temp:.1f}C", (10, view_height - 12))

    return view


def render_frame(
    raw: np.ndarray,
    args: argparse.Namespace,
    config: LeptonConfig,
    fps: float,
    state: Optional[ViewerState] = None,
) -> np.ndarray:
    state = state or ViewerState()
    view = render_thermal_view(raw, args)
    view_width, _ = thermal_view_size(args)

    frame = np.zeros((args.window_height, args.window_width, 3), dtype=np.uint8)
    frame[:, :view_width] = view
    draw_control_panel(frame, args, config, state, fps)

    return frame


def idle_frame(args: argparse.Namespace, config: LeptonConfig, state: ViewerState, fps: float = 0.0) -> np.ndarray:
    view_width, view_height = thermal_view_size(args)
    frame = np.zeros((args.window_height, args.window_width, 3), dtype=np.uint8)
    view = frame[:, :view_width]
    draw_text(view, "Camera Off", (max(12, view_width // 2 - 54), view_height // 2 - 8))
    draw_text(view, "Click On to start", (max(12, view_width // 2 - 76), view_height // 2 + 18))
    draw_control_panel(frame, args, config, state, fps)
    return frame


def message_frame(
    title: str,
    subtitle: str,
    args: argparse.Namespace,
    config: LeptonConfig,
    state: ViewerState,
) -> np.ndarray:
    view_width, view_height = thermal_view_size(args)
    frame = np.zeros((args.window_height, args.window_width, 3), dtype=np.uint8)
    view = frame[:, :view_width]
    draw_text(view, title, (max(12, view_width // 2 - 70), view_height // 2 - 8))
    draw_text(view, subtitle, (max(12, view_width // 2 - 92), view_height // 2 + 18))
    draw_control_panel(frame, args, config, state, 0.0)
    return frame


def error_frame(message: str, args: argparse.Namespace, config: LeptonConfig, state: ViewerState) -> np.ndarray:
    view_width, height = thermal_view_size(args)
    frame = np.zeros((args.window_height, args.window_width, 3), dtype=np.uint8)
    view = frame[:, :view_width]
    lines = ("FLIR error", message[:54], "Press q or Esc to quit")
    for index, line in enumerate(lines):
        draw_text(view, line, (16, height // 2 - 22 + index * 22))
    draw_control_panel(frame, args, config, state, 0.0)
    return frame


def save_capture(frame: np.ndarray, results_dir: str) -> Path:
    output_dir = Path(results_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"thermal_{time.strftime('%Y%m%d%H%M%S')}.jpg"

    ok = cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if not ok:
        raise OSError(f"Unable to write JPEG capture: {path}")
    return path


def window_exists(window_name: str) -> bool:
    try:
        return cv2.getWindowProperty(window_name, cv2.WND_PROP_AUTOSIZE) >= 0
    except cv2.error:
        return False


def on_mouse(event, x, y, flags, param) -> None:
    if event != cv2.EVENT_LBUTTONUP:
        return

    args, state = param
    buttons = viewer_buttons(args)
    if point_in_rect((x, y), buttons["toggle"]):
        state.toggle_requested = True
    elif point_in_rect((x, y), buttons["capture"]):
        state.capture_requested = True
    elif point_in_rect((x, y), buttons["exit"]):
        state.quit_requested = True


def run_viewer(args: argparse.Namespace) -> None:
    config = fallback_config(args)
    flir: Optional[FLIRLepton25] = None

    try:
        cv2.startWindowThread()
    except cv2.error:
        pass
    cv2.namedWindow(args.window_name, cv2.WINDOW_NORMAL)
    print(f"Created OpenCV window '{args.window_name}'", flush=True)
    cv2.resizeWindow(args.window_name, args.window_width, args.window_height)
    cv2.moveWindow(args.window_name, 80, 80)
    state = ViewerState()
    cv2.setMouseCallback(args.window_name, on_mouse, (args, state))
    state.set_message("Starting")

    last_time = time.monotonic()
    fps = 0.0
    try:
        cv2.imshow(
            args.window_name,
            message_frame("Starting FLIR", "Detecting camera", args, config, state),
        )
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

            if state.toggle_requested:
                state.toggle_requested = False
                state.camera_on = not state.camera_on
                state.set_message("Camera on" if state.camera_on else "Camera off")
                if not state.camera_on:
                    if flir is not None:
                        flir.release()
                        flir = None

            if state.camera_on:
                if flir is None:
                    try:
                        state.set_message("Detecting FLIR")
                        config = build_config(args)
                        flir = FLIRLepton25(config)
                        print(
                            f"Using /dev/spidev{config.spi_bus}.{config.spi_device} "
                            f"at {config.spi_speed_hz} Hz",
                            flush=True,
                        )
                    except ThermalError as exc:
                        print(f"FLIR setup error: {exc}", file=sys.stderr, flush=True)
                        state.camera_on = False
                        state.set_message("Setup failed")
                        frame = error_frame(str(exc), args, config, state)
                        time.sleep(args.error_sleep_s)
                    else:
                        frame = idle_frame(args, config, state, fps)
                else:
                    try:
                        raw = flir.get_raw_frame()
                        state.last_raw = raw.copy()
                        now = time.monotonic()
                        elapsed = now - last_time
                        last_time = now
                        if elapsed > 0:
                            instant_fps = 1.0 / elapsed
                            fps = 0.8 * fps + 0.2 * instant_fps if fps > 0 else instant_fps
                        frame = render_frame(raw, args, config, fps, state)
                        state.last_frame = render_thermal_view(raw, args)
                    except (ThermalError, RuntimeError) as exc:
                        print(f"FLIR capture error: {exc}", file=sys.stderr, flush=True)
                        flir.release()
                        flir = None
                        state.camera_on = False
                        state.set_message("Capture error")
                        frame = error_frame(str(exc), args, config, state)
                        time.sleep(args.error_sleep_s)
            else:
                if flir is not None:
                    flir.release()
                    flir = None
                fps = 0.0
                frame = idle_frame(args, config, state)

            if state.capture_requested:
                state.capture_requested = False
                if state.last_frame is None:
                    state.set_message("No frame yet")
                else:
                    try:
                        path = save_capture(state.last_frame, args.results_dir)
                        state.set_message(f"Saved {path.name}")
                        print(f"Saved {path}", flush=True)
                    except OSError as exc:
                        state.set_message(f"Save failed: {exc}")
                        print(f"Save failed: {exc}", file=sys.stderr, flush=True)

            cv2.imshow(args.window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27) or state.quit_requested or not window_exists(args.window_name):
                break
    finally:
        if flir is not None:
            flir.release()
        cv2.destroyAllWindows()


def main() -> int:
    args = build_parser().parse_args()
    if args.window_width <= 0 or args.window_height <= 0:
        print("Window width and height must be positive.", file=sys.stderr)
        return 2
    if args.panel_width < 96 or args.panel_width >= args.window_width:
        print("Panel width must be at least 96 and smaller than window width.", file=sys.stderr)
        return 2

    print(
        f"Opening {args.window_width}x{args.window_height} FLIR viewer. "
        "Press q or Esc to quit.",
        flush=True,
    )
    try:
        run_viewer(args)
    except Exception as exc:
        print(f"Thermal viewer fatal error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    print("Thermal viewer exited.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
