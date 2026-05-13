"""Standalone 480x320 live viewer for the IMX219 CSI camera."""

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


DEFAULT_WINDOW_WIDTH = 480
DEFAULT_WINDOW_HEIGHT = 320
DEFAULT_WINDOW_NAME = "GoVision Camera Self"
DEFAULT_PANEL_WIDTH = 128
DEFAULT_VIEW_WIDTH = DEFAULT_WINDOW_WIDTH - DEFAULT_PANEL_WIDTH
DEFAULT_VIEW_HEIGHT = DEFAULT_WINDOW_HEIGHT
DEFAULT_SENSOR_MODE = 4
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "results"


Rect = Tuple[int, int, int, int]


@dataclass
class ViewerState:
    camera_on: bool = True
    toggle_requested: bool = False
    capture_requested: bool = False
    quit_requested: bool = False
    last_camera_frame: Optional[np.ndarray] = None
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


def view_size(args: argparse.Namespace) -> Tuple[int, int]:
    return args.window_width - args.panel_width, args.window_height


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
    state: ViewerState,
    fps: float,
) -> None:
    panel_x = args.window_width - args.panel_width
    cv2.rectangle(frame, (panel_x, 0), (args.window_width, args.window_height), (30, 30, 30), -1)
    cv2.line(frame, (panel_x, 0), (panel_x, args.window_height), (80, 80, 80), 1)

    draw_panel_text(frame, "CAMERA", (panel_x + 12, 22))
    draw_panel_text(frame, f"Cam: {'On' if state.camera_on else 'Off'}", (panel_x + 12, 48))
    draw_panel_text(frame, f"FPS: {fps:.1f}" if fps > 0 else "FPS: --", (panel_x + 12, 66))

    buttons = viewer_buttons(args)
    draw_button(frame, buttons["toggle"], "Off" if state.camera_on else "On", active=state.camera_on)
    draw_button(frame, buttons["capture"], "Capture", active=state.last_camera_frame is not None)
    draw_button(frame, buttons["exit"], "Exit", active=False)

    draw_panel_text(frame, f"Sensor: {args.sensor_id}", (panel_x + 12, 198))
    draw_panel_text(frame, f"Flip: {args.flip_method}", (panel_x + 12, 216))
    message = status_message(state)
    for index, chunk in enumerate(message[i : i + 15] for i in range(0, len(message), 15)):
        if index >= 3:
            break
        draw_panel_text(frame, chunk, (panel_x + 12, 242 + index * 18))


def render_frame(
    camera_frame: np.ndarray,
    args: argparse.Namespace,
    fps: float,
    state: Optional[ViewerState] = None,
) -> np.ndarray:
    state = state or ViewerState()
    view_width, view_height = view_size(args)
    view = fit_to_view(camera_frame, view_width, view_height)

    if not args.no_overlay:
        height, width = camera_frame.shape[:2]
        draw_text(view, f"{width}x{height}", (10, 22))

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
    state = ViewerState()
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
                if not state.camera_on and camera is not None:
                    camera.release()
                    camera = None

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
                if state.last_camera_frame is None:
                    state.set_message("No frame yet")
                else:
                    try:
                        path = save_capture(state.last_camera_frame, args.results_dir, args.jpeg_quality)
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
        if camera is not None:
            camera.release()
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
