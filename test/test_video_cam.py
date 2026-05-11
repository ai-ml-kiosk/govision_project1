from pathlib import Path
import argparse
import os
import sys
import time
from typing import Optional

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.camera import CameraConfig, CameraError, IMX219Camera


MJPEG_MIMETYPE = "multipart/x-mixed-replace; boundary=frame"


def env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def env_int_optional(name: str) -> Optional[int]:
    value = os.getenv(name)
    return None if value is None else int(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live IMX219 CSI camera viewer/stream")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Serve an MJPEG stream instead of opening an OpenCV window",
    )
    parser.add_argument("--host", default=os.getenv("CAMERA_STREAM_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=env_int("CAMERA_STREAM_PORT", 5002))
    parser.add_argument("--window-name", default="GoVision Camera")
    parser.add_argument("--sensor-id", type=int, default=env_int("CAMERA_SENSOR_ID", 0))
    parser.add_argument("--capture-width", type=int, default=env_int("CAMERA_CAPTURE_WIDTH", 1280))
    parser.add_argument("--capture-height", type=int, default=env_int("CAMERA_CAPTURE_HEIGHT", 720))
    parser.add_argument("--display-width", type=int, default=env_int("CAMERA_DISPLAY_WIDTH", 1280))
    parser.add_argument("--display-height", type=int, default=env_int("CAMERA_DISPLAY_HEIGHT", 720))
    parser.add_argument("--framerate", type=int, default=env_int("CAMERA_FRAMERATE", 30))
    parser.add_argument("--flip-method", type=int, default=env_int("CAMERA_FLIP_METHOD", 2))
    parser.add_argument("--sensor-mode", type=int, default=env_int_optional("CAMERA_SENSOR_MODE"))
    parser.add_argument("--jpeg-quality", type=int, default=env_int("CAMERA_JPEG_QUALITY", 85))
    parser.add_argument("--error-sleep-s", type=float, default=env_float("CAMERA_ERROR_SLEEP_S", 0.25))
    show_overlay_default = os.getenv("CAMERA_SHOW_OVERLAY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )
    parser.set_defaults(show_overlay=show_overlay_default)
    parser.add_argument("--show-overlay", dest="show_overlay", action="store_true")
    parser.add_argument("--no-overlay", dest="show_overlay", action="store_false")
    parser.add_argument("--resize-width", type=int, default=env_int_optional("CAMERA_OUTPUT_WIDTH"))
    parser.add_argument("--resize-height", type=int, default=env_int_optional("CAMERA_OUTPUT_HEIGHT"))
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


def resize_output(frame: np.ndarray, args: argparse.Namespace) -> np.ndarray:
    if args.resize_width is None and args.resize_height is None:
        return frame

    height, width = frame.shape[:2]
    if args.resize_width is None:
        scale = args.resize_height / float(height)
        target_size = (round(width * scale), args.resize_height)
    elif args.resize_height is None:
        scale = args.resize_width / float(width)
        target_size = (args.resize_width, round(height * scale))
    else:
        target_size = (args.resize_width, args.resize_height)

    return cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)


def draw_overlay(frame: np.ndarray, args: argparse.Namespace, fps: float) -> np.ndarray:
    if not args.show_overlay:
        return frame

    output = frame.copy()
    height, width = output.shape[:2]
    lines = (
        f"Sensor {args.sensor_id}  {width}x{height}",
        f"Capture {args.capture_width}x{args.capture_height} @ {args.framerate} fps",
        f"Flip {args.flip_method}  FPS {fps:.1f}" if fps > 0 else f"Flip {args.flip_method}  FPS --",
    )
    panel_width = min(width - 16, 620)
    panel_height = 18 + 26 * len(lines)
    cv2.rectangle(output, (8, 8), (8 + panel_width, 8 + panel_height), (0, 0, 0), -1)
    for index, line in enumerate(lines):
        cv2.putText(
            output,
            line,
            (16, 34 + index * 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.68,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
    return output


def error_frame(message: str, width: int = 640, height: int = 360) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.putText(
        frame,
        message[:84],
        (20, height // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return frame


def encode_jpeg(frame: np.ndarray, quality: int) -> bytes:
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("Unable to encode frame as JPEG")
    return encoded.tobytes()


def mjpeg_chunk(frame: np.ndarray, quality: int) -> bytes:
    return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + encode_jpeg(frame, quality) + b"\r\n"


def frame_loop(camera: IMX219Camera, args: argparse.Namespace):
    last_time = time.monotonic()
    fps = 0.0
    while True:
        try:
            frame = camera.get_frame()
            now = time.monotonic()
            elapsed = now - last_time
            last_time = now
            if elapsed > 0:
                fps = 0.85 * fps + 0.15 * (1.0 / elapsed) if fps > 0 else 1.0 / elapsed
            frame = resize_output(frame, args)
            yield draw_overlay(frame, args, fps)
        except (CameraError, RuntimeError) as exc:
            camera.release()
            yield error_frame(str(exc))
            time.sleep(args.error_sleep_s)


def run_window(camera: IMX219Camera, args: argparse.Namespace) -> None:
    try:
        for frame in frame_loop(camera, args):
            cv2.imshow(args.window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


def run_http(camera: IMX219Camera, args: argparse.Namespace) -> None:
    from flask import Flask, Response, stream_with_context

    app = Flask(__name__)

    @app.get("/")
    def index():
        return '<img src="/video_feed" style="max-width: 100%;">'

    @app.get("/video_feed")
    def video_feed():
        def generate():
            for frame in frame_loop(camera, args):
                yield mjpeg_chunk(frame, args.jpeg_quality)

        response = Response(stream_with_context(generate()), content_type=MJPEG_MIMETYPE)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    try:
        print(f"Serving camera stream at http://{args.host}:{args.port}/")
        app.run(host=args.host, port=args.port, threaded=True)
    finally:
        camera.release()


def main() -> int:
    args = build_parser().parse_args()
    config = build_config(args)
    print(f"Using IMX219 sensor-id={args.sensor_id}")
    print(f"Pipeline: {IMX219Camera(sensor_id=args.sensor_id, config=config).pipeline}")
    camera = IMX219Camera(sensor_id=args.sensor_id, config=config)

    if args.http:
        run_http(camera, args)
    else:
        run_window(camera, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
