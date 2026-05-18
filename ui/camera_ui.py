"""Standalone 480x320 live viewer for the IMX219 CSI camera."""

from __future__ import annotations

import argparse
import json
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


DEFAULT_WINDOW_WIDTH = 480
DEFAULT_WINDOW_HEIGHT = 320
DEFAULT_WINDOW_NAME = "GoVision Camera UI"
DEFAULT_PANEL_WIDTH = 128
DEFAULT_VIEW_WIDTH = DEFAULT_WINDOW_WIDTH - DEFAULT_PANEL_WIDTH
DEFAULT_VIEW_HEIGHT = DEFAULT_WINDOW_HEIGHT
DEFAULT_SENSOR_MODE = 4
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "results"
DEFAULT_SETTINGS_PATH = Path("~/.config/govision/camera_ui.json")
LEGACY_SETTINGS_PATH = Path("~/.config/govision/camera_self.json")
ZOOM_LEVELS = (1.0, 1.5, 2.0, 3.0, 4.0)


Rect = Tuple[int, int, int, int]


@dataclass
class ViewerState:
    camera_on: bool = True
    toggle_requested: bool = False
    rotation_delta_requested: int = 0
    rotation_degrees: int = 0
    zoom_delta_requested: int = 0
    zoom_level: float = 1.0
    capture_requested: bool = False
    quit_requested: bool = False
    last_camera_frame: Optional[np.ndarray] = None
    last_view_frame: Optional[np.ndarray] = None
    message: str = "Starting"
    message_until: float = 0.0

    def set_message(self, message: str, ttl_s: float = 3.0) -> None:
        self.message = message
        self.message_until = time.monotonic() + ttl_s


def env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def env_int_optional(name: str) -> Optional[int]:
    value = os.getenv(name)
    return None if value is None else int(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open a 480x320 live IMX219 CSI camera viewing window"
    )
    parser.add_argument("--window-name", default=os.getenv("CAMERA_WINDOW_NAME", DEFAULT_WINDOW_NAME))
    parser.add_argument(
        "--window-width",
        type=int,
        default=env_int("CAMERA_WINDOW_WIDTH", DEFAULT_WINDOW_WIDTH),
    )
    parser.add_argument(
        "--window-height",
        type=int,
        default=env_int("CAMERA_WINDOW_HEIGHT", DEFAULT_WINDOW_HEIGHT),
    )
    parser.add_argument(
        "--panel-width",
        type=int,
        default=env_int("CAMERA_PANEL_WIDTH", DEFAULT_PANEL_WIDTH),
    )
    parser.add_argument(
        "--results-dir",
        default=os.getenv("CAMERA_RESULTS_DIR", str(DEFAULT_RESULTS_DIR)),
        help="Directory for Capture button JPEG output",
    )
    parser.add_argument(
        "--settings-file",
        default=os.getenv(
            "CAMERA_UI_SETTINGS_FILE",
            os.getenv("CAMERA_SELF_SETTINGS_FILE", str(DEFAULT_SETTINGS_PATH)),
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
        help="Initial clockwise display rotation in degrees; overrides saved setting",
    )
    parser.add_argument(
        "--zoom-level",
        type=float,
        default=None,
        help="Initial display zoom; overrides saved setting",
    )
    parser.add_argument("--sensor-id", type=int, default=env_int("CAMERA_SENSOR_ID", 0))
    parser.add_argument("--capture-width", type=int, default=env_int("CAMERA_CAPTURE_WIDTH", 1280))
    parser.add_argument("--capture-height", type=int, default=env_int("CAMERA_CAPTURE_HEIGHT", 720))
    parser.add_argument("--display-width", type=int, default=env_int("CAMERA_DISPLAY_WIDTH", DEFAULT_VIEW_WIDTH))
    parser.add_argument("--display-height", type=int, default=env_int("CAMERA_DISPLAY_HEIGHT", DEFAULT_VIEW_HEIGHT))
    parser.add_argument("--framerate", type=int, default=env_int("CAMERA_FRAMERATE", 30))
    parser.add_argument("--flip-method", type=int, default=env_int("CAMERA_FLIP_METHOD", 2))
    parser.add_argument(
        "--sensor-mode",
        type=int,
        default=env_int("CAMERA_SENSOR_MODE", DEFAULT_SENSOR_MODE),
    )
    parser.add_argument("--jpeg-quality", type=int, default=env_int("CAMERA_JPEG_QUALITY", 95))
    parser.add_argument("--error-sleep-s", type=float, default=env_float("CAMERA_ERROR_SLEEP_S", 0.25))
    parser.add_argument("--no-overlay", action="store_true", help="Hide view-area status overlay")
    return parser


def build_config(args: argparse.Namespace) -> CameraConfig:
    return CameraConfig(
        capture_width=args.capture_width,
        capture_height=args.capture_height,
        display_width=args.display_width,
        display_height=args.display_height,
        framerate=args.framerate,
        flip_method=args.flip_method,
        sensor_mode=args.sensor_mode,
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
        print(f"Unable to load camera viewer settings from {path}: {exc}", file=sys.stderr)
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
    return settings


def save_viewer_settings(args: argparse.Namespace, state: ViewerState) -> None:
    if args.no_save_settings:
        return

    path = settings_path(args)
    payload = {
        "rotation_degrees": normalize_degrees(state.rotation_degrees),
        "zoom_level": normalize_zoom(state.zoom_level),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except OSError as exc:
        print(f"Unable to save camera viewer settings to {path}: {exc}", file=sys.stderr)


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


def rotate_image_bound(frame: np.ndarray, degrees: int) -> np.ndarray:
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
        flags=cv2.INTER_AREA,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )


def fit_to_view(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    source_h, source_w = frame.shape[:2]
    scale = min(width / source_w, height / source_h)
    resized_w = max(1, int(round(source_w * scale)))
    resized_h = max(1, int(round(source_h * scale)))
    resized = cv2.resize(frame, (resized_w, resized_h), interpolation=cv2.INTER_AREA)

    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    x_offset = (width - resized_w) // 2
    y_offset = (height - resized_h) // 2
    canvas[y_offset : y_offset + resized_h, x_offset : x_offset + resized_w] = resized
    return canvas


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
        "toggle": (panel_x + margin, 106, button_w, 28),
        "rotate_left": (panel_x + margin, 166, half_w, 24),
        "rotate_right": (panel_x + margin + half_w + gap, 166, half_w, 24),
        "zoom_out": (panel_x + margin, 206, half_w, 24),
        "zoom_in": (panel_x + margin + half_w + gap, 206, half_w, 24),
        "capture": (panel_x + margin, 248, button_w, 28),
        "exit": (panel_x + margin, 286, button_w, 24),
    }


def status_message(state: ViewerState) -> str:
    if state.message and time.monotonic() < state.message_until:
        return state.message
    return "Streaming" if state.camera_on else "Camera off"


def draw_control_panel(
    frame: np.ndarray,
    args: argparse.Namespace,
    state: ViewerState,
    fps: float,
) -> None:
    panel_x = args.window_width - args.panel_width
    margin = 10
    content_x = panel_x + margin
    content_w = max(1, args.panel_width - margin * 2)
    cv2.rectangle(frame, (panel_x, 0), (args.window_width, args.window_height), (28, 28, 28), -1)
    cv2.line(frame, (panel_x, 0), (panel_x, args.window_height), (76, 76, 76), 1)

    draw_panel_text(frame, "CSI", (content_x, 21), font_scale=0.52, color=(245, 245, 245))
    state_color = (122, 216, 142) if state.camera_on else (165, 165, 165)
    draw_panel_text(
        frame,
        "ON" if state.camera_on else "OFF",
        (content_x + 74, 21),
        font_scale=0.42,
        color=state_color,
    )
    draw_panel_text(frame, f"FPS {fps:.1f}" if fps > 0 else "FPS --", (content_x, 43), font_scale=0.38)
    draw_panel_text(frame, f"Sensor {args.sensor_id}", (content_x, 60), font_scale=0.36, color=(178, 178, 178))
    draw_panel_text(frame, f"Flip {args.flip_method}", (content_x, 77), font_scale=0.36, color=(178, 178, 178))
    draw_panel_rule(frame, content_x, 88, content_w)

    buttons = viewer_buttons(args)
    draw_section_label(frame, "CAMERA", (content_x, 102))
    draw_button(
        frame,
        buttons["toggle"],
        "Cam Off" if state.camera_on else "Cam On",
        active=True,
        style="danger" if state.camera_on else "primary",
    )

    draw_section_label(frame, "VIEW", (content_x, 150))
    draw_panel_text(frame, f"Rot {rotation_label(state.rotation_degrees)}", (content_x, 162), font_scale=0.37)
    draw_button(frame, buttons["rotate_left"], "-90", active=True, style="neutral")
    draw_button(frame, buttons["rotate_right"], "+90", active=True, style="neutral")
    draw_panel_text(frame, f"Zoom {zoom_label(state.zoom_level)}", (content_x, 202), font_scale=0.37)
    draw_button(
        frame,
        buttons["zoom_out"],
        "-",
        active=normalize_zoom(state.zoom_level) > ZOOM_LEVELS[0],
        style="neutral",
    )
    draw_button(
        frame,
        buttons["zoom_in"],
        "+",
        active=normalize_zoom(state.zoom_level) < ZOOM_LEVELS[-1],
        style="neutral",
    )

    draw_section_label(frame, "ACTION", (content_x, 242))
    draw_button(
        frame,
        buttons["capture"],
        "Capture",
        active=state.last_view_frame is not None,
        style="primary",
    )
    draw_button(frame, buttons["exit"], "Exit", active=True, style="danger")

    message = status_message(state)
    for index, chunk in enumerate(message[i : i + 15] for i in range(0, len(message), 15)):
        if index >= 1:
            break
        draw_panel_text(frame, chunk, (content_x, args.window_height - 4), font_scale=0.34, color=(190, 190, 190))


def render_frame(
    camera_frame: np.ndarray,
    args: argparse.Namespace,
    fps: float,
    state: Optional[ViewerState] = None,
) -> np.ndarray:
    state = state or ViewerState()
    view_width, view_height = view_size(args)
    view_source = crop_center_for_zoom(camera_frame, state.zoom_level)
    view_source = rotate_image_bound(view_source, state.rotation_degrees)
    view = fit_to_view(view_source, view_width, view_height)

    if not args.no_overlay:
        height, width = camera_frame.shape[:2]
        draw_text(view, f"{width}x{height}", (10, 22))

    state.last_view_frame = view.copy()
    frame = np.zeros((args.window_height, args.window_width, 3), dtype=np.uint8)
    frame[:, :view_width] = view
    draw_control_panel(frame, args, state, fps)
    return frame


def idle_frame(args: argparse.Namespace, state: ViewerState, fps: float = 0.0) -> np.ndarray:
    view_width, view_height = view_size(args)
    frame = np.zeros((args.window_height, args.window_width, 3), dtype=np.uint8)
    view = frame[:, :view_width]
    draw_text(view, "Camera Off", (max(12, view_width // 2 - 54), view_height // 2 - 8))
    draw_text(view, "Click On to start", (max(12, view_width // 2 - 76), view_height // 2 + 18))
    draw_control_panel(frame, args, state, fps)
    return frame


def message_frame(title: str, subtitle: str, args: argparse.Namespace, state: ViewerState) -> np.ndarray:
    view_width, view_height = view_size(args)
    frame = np.zeros((args.window_height, args.window_width, 3), dtype=np.uint8)
    view = frame[:, :view_width]
    draw_text(view, title, (max(12, view_width // 2 - 76), view_height // 2 - 8))
    draw_text(view, subtitle, (max(12, view_width // 2 - 92), view_height // 2 + 18))
    draw_control_panel(frame, args, state, 0.0)
    return frame


def error_frame(message: str, args: argparse.Namespace, state: ViewerState) -> np.ndarray:
    view_width, height = view_size(args)
    frame = np.zeros((args.window_height, args.window_width, 3), dtype=np.uint8)
    view = frame[:, :view_width]
    lines = ("Camera error", message[:54], "Use Exit to quit")
    for index, line in enumerate(lines):
        draw_text(view, line, (16, height // 2 - 22 + index * 22))
    draw_control_panel(frame, args, state, 0.0)
    return frame


def save_capture(frame: np.ndarray, results_dir: str, quality: int) -> Path:
    output_dir = Path(results_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"camera_{time.strftime('%Y%m%d%H%M%S')}.jpg"

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
    if point_in_rect((x, y), buttons["toggle"]):
        state.toggle_requested = True
    elif point_in_rect((x, y), buttons["rotate_left"]):
        state.rotation_delta_requested -= 90
    elif point_in_rect((x, y), buttons["rotate_right"]):
        state.rotation_delta_requested += 90
    elif point_in_rect((x, y), buttons["zoom_out"]):
        state.zoom_delta_requested -= 1
    elif point_in_rect((x, y), buttons["zoom_in"]):
        state.zoom_delta_requested += 1
    elif point_in_rect((x, y), buttons["capture"]):
        state.capture_requested = True
    elif point_in_rect((x, y), buttons["exit"]):
        state.quit_requested = True


def run_viewer(args: argparse.Namespace) -> None:
    config = build_config(args)
    camera: Optional[IMX219Camera] = None

    try:
        cv2.startWindowThread()
    except cv2.error:
        pass
    cv2.namedWindow(args.window_name, cv2.WINDOW_NORMAL)
    print(f"Created OpenCV window '{args.window_name}'", flush=True)
    cv2.resizeWindow(args.window_name, args.window_width, args.window_height)
    cv2.moveWindow(args.window_name, 120, 120)
    raise_window(args.window_name)
    state = ViewerState(
        rotation_degrees=normalize_degrees(args.rotation_degrees),
        zoom_level=normalize_zoom(args.zoom_level),
    )
    cv2.setMouseCallback(args.window_name, on_mouse, (args, state))
    state.set_message("Starting")

    last_time = time.monotonic()
    fps = 0.0
    try:
        cv2.imshow(
            args.window_name,
            message_frame("Starting Camera", "Opening sensor", args, state),
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

            if state.toggle_requested:
                state.toggle_requested = False
                state.camera_on = not state.camera_on
                state.set_message("Camera on" if state.camera_on else "Camera off")
                if not state.camera_on and camera is not None:
                    camera.release()
                    camera = None

            if state.rotation_delta_requested:
                state.rotation_degrees = normalize_degrees(
                    state.rotation_degrees + state.rotation_delta_requested
                )
                state.rotation_delta_requested = 0
                save_viewer_settings(args, state)
                state.set_message(f"Rotation {rotation_label(state.rotation_degrees)}")
                if state.last_camera_frame is not None:
                    frame = render_frame(state.last_camera_frame, args, fps, state)

            if state.zoom_delta_requested:
                state.zoom_level = step_zoom(state.zoom_level, state.zoom_delta_requested)
                state.zoom_delta_requested = 0
                save_viewer_settings(args, state)
                state.set_message(f"Zoom {zoom_label(state.zoom_level)}")
                if state.last_camera_frame is not None:
                    frame = render_frame(state.last_camera_frame, args, fps, state)

            if state.camera_on:
                if camera is None:
                    camera = IMX219Camera(sensor_id=args.sensor_id, config=config)
                    print(f"Using IMX219 sensor-id={args.sensor_id}", flush=True)
                    print(f"Pipeline: {camera.pipeline}", flush=True)

                try:
                    camera_frame = camera.get_frame()
                    state.last_camera_frame = camera_frame.copy()
                    now = time.monotonic()
                    elapsed = now - last_time
                    last_time = now
                    if elapsed > 0:
                        instant_fps = 1.0 / elapsed
                        fps = 0.85 * fps + 0.15 * instant_fps if fps > 0 else instant_fps
                    frame = render_frame(camera_frame, args, fps, state)
                except (CameraError, RuntimeError) as exc:
                    print(f"Camera capture error: {exc}", file=sys.stderr, flush=True)
                    if camera is not None:
                        camera.release()
                        camera = None
                    state.camera_on = False
                    state.set_message("Capture error")
                    frame = error_frame(str(exc), args, state)
                    time.sleep(args.error_sleep_s)
            else:
                if camera is not None:
                    camera.release()
                    camera = None
                fps = 0.0
                frame = idle_frame(args, state)

            if state.capture_requested:
                state.capture_requested = False
                if state.last_view_frame is None:
                    state.set_message("No frame yet")
                else:
                    try:
                        path = save_capture(state.last_view_frame, args.results_dir, args.jpeg_quality)
                        state.set_message(f"Saved {path.name}")
                        print(f"Saved {path}", flush=True)
                    except OSError as exc:
                        state.set_message(f"Save failed: {exc}")
                        print(f"Save failed: {exc}", file=sys.stderr, flush=True)

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
        cv2.destroyAllWindows()


def main() -> int:
    args = build_parser().parse_args()
    settings = load_viewer_settings(args)
    if args.rotation_degrees is None:
        args.rotation_degrees = settings.get("rotation_degrees", 0)
    args.rotation_degrees = normalize_degrees(args.rotation_degrees)
    if args.zoom_level is None:
        args.zoom_level = settings.get("zoom_level", 1.0)
    args.zoom_level = normalize_zoom(args.zoom_level)

    if args.window_width <= 0 or args.window_height <= 0:
        print("Window width and height must be positive.", file=sys.stderr)
        return 2
    if args.panel_width < 96 or args.panel_width >= args.window_width:
        print("Panel width must be at least 96 and smaller than window width.", file=sys.stderr)
        return 2

    print(
        f"Opening {args.window_width}x{args.window_height} CSI camera viewer. "
        "Press q or Esc to quit.",
        flush=True,
    )
    try:
        run_viewer(args)
    except Exception as exc:
        print(f"Camera viewer fatal error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    print("Camera viewer exited.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
