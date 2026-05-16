from pathlib import Path
import argparse
import os
import sys
import time
from typing import Optional, Tuple

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.thermal import (
    FLIRLepton25,
    LeptonConfig,
    ThermalError,
    config_with_detected_spidev,
    parse_spi_candidates,
    tlinear_to_celsius,
)


MJPEG_MIMETYPE = "multipart/x-mixed-replace; boundary=frame"


def env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_optional_int(name: str) -> Optional[int]:
    value = os.getenv(name)
    return None if value is None else int(value)


def env_optional_float(name: str) -> Optional[float]:
    value = os.getenv(name)
    return None if value is None else float(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live FLIR Lepton thermal viewer/stream")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Serve an MJPEG stream instead of opening an OpenCV window",
    )
    parser.add_argument("--host", default=os.getenv("FLIR_STREAM_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=env_int("FLIR_STREAM_PORT", 5001))
    parser.add_argument("--window-name", default="GoVision FLIR")
    parser.add_argument("--scale", type=int, default=env_int("FLIR_OUTPUT_SCALE", 8))
    parser.add_argument("--flip-code", default=os.getenv("FLIR_FLIP_CODE", "-1"))
    parser.add_argument("--min-c", type=float, default=env_optional_float("FLIR_MIN_C"))
    parser.add_argument("--max-c", type=float, default=env_optional_float("FLIR_MAX_C"))
    parser.add_argument("--auto-low-percentile", type=float, default=env_float("FLIR_LOW_PCT", 2.0))
    parser.add_argument("--auto-high-percentile", type=float, default=env_float("FLIR_HIGH_PCT", 98.0))
    parser.add_argument(
        "--sensitivity",
        type=float,
        default=env_float("FLIR_SENSITIVITY", 1.4),
        help="Narrow auto color range; higher values make smaller temperature changes more visible",
    )
    parser.add_argument("--tlinear-scale", type=float, default=env_float("FLIR_TLINEAR_SCALE", 100.0))
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
    parser.add_argument(
        "--reset-on-error",
        action="store_true",
        default=env_bool("FLIR_RESET_ON_ERROR", False),
        help="Pulse configured reset pin, or soft-reset SPI, after capture errors",
    )
    parser.add_argument(
        "--reset-board-pin",
        type=int,
        default=env_optional_int("FLIR_RESET_BOARD_PIN"),
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
    parser.add_argument("--jpeg-quality", type=int, default=85)
    return parser


def build_config(args: argparse.Namespace) -> LeptonConfig:
    forced_spi = args.bus is not None or args.device is not None
    env_forced_spi = "FLIR_SPI_BUS" in os.environ or "FLIR_SPI_DEVICE" in os.environ
    config = LeptonConfig(
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

    if args.no_auto_detect or forced_spi or env_forced_spi:
        return config

    return config_with_detected_spidev(
        config,
        candidates=parse_spi_candidates(args.candidates),
        probe_speed_hz=args.probe_speed_hz,
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


def draw_temp_label(
    frame: np.ndarray,
    point: Tuple[int, int],
    text: str,
    color: Tuple[int, int, int],
) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.56
    thickness = 2
    padding = 5
    text_w, text_h = cv2.getTextSize(text, font, font_scale, thickness)[0]
    x = min(max(point[0] + 10, 0), max(0, frame.shape[1] - text_w - padding * 2))
    y = min(max(point[1] - 10, text_h + padding * 2), frame.shape[0] - padding)
    top_left = (x, y - text_h - padding * 2)
    bottom_right = (x + text_w + padding * 2, y + padding)
    cv2.rectangle(frame, top_left, bottom_right, (0, 0, 0), -1)
    cv2.rectangle(frame, top_left, bottom_right, color, 1)
    cv2.putText(
        frame,
        text,
        (x + padding, y - padding),
        font,
        font_scale,
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )


def render_frame(raw: np.ndarray, args: argparse.Namespace, fps: float = 0.0) -> np.ndarray:
    raw = apply_optional_flip(raw, args.flip_code)
    temps_c = tlinear_to_celsius(raw, scale=args.tlinear_scale)

    min_temp, max_temp, min_loc, max_loc = cv2.minMaxLoc(temps_c)
    low, high = auto_color_range(temps_c, args)

    normalized = ((temps_c - low) * 255.0) / (high - low)
    normalized = np.clip(normalized, 0, 255).astype(np.uint8)
    frame = cv2.applyColorMap(normalized, cv2.COLORMAP_JET)

    if args.scale > 1:
        frame = cv2.resize(frame, None, fx=args.scale, fy=args.scale, interpolation=cv2.INTER_NEAREST)

    min_pt = (min_loc[0] * args.scale, min_loc[1] * args.scale)
    max_pt = (max_loc[0] * args.scale, max_loc[1] * args.scale)
    cv2.rectangle(frame, (8, 8), (330, 104), (0, 0, 0), -1)
    lines = (
        f"Min {min_temp:.2f} C",
        f"Max {max_temp:.2f} C",
        f"Scale {low:.1f}..{high:.1f} C",
        f"FPS {fps:.1f}" if fps > 0 else "FPS --",
    )
    for index, line in enumerate(lines):
        cv2.putText(
            frame,
            line,
            (16, 34 + index * 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
    cv2.circle(frame, min_pt, 8, (255, 255, 255), 2)
    cv2.circle(frame, max_pt, 8, (0, 0, 0), 2)
    draw_temp_label(frame, min_pt, f"LOW {min_temp:.1f}C", (255, 255, 255))
    draw_temp_label(frame, max_pt, f"HIGH {max_temp:.1f}C", (0, 0, 255))
    return frame


def error_frame(message: str, width: int = 640, height: int = 480) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.putText(
        frame,
        message[:80],
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


def reset_flir(flir: FLIRLepton25, reopen: bool = False) -> None:
    flir.reset(reopen=reopen)
    print("Reset FLIR capture", flush=True)


def frame_loop(flir: FLIRLepton25, args: argparse.Namespace, lock=None):
    last_time = time.monotonic()
    fps = 0.0
    while True:
        try:
            if lock is None:
                raw = flir.get_raw_frame()
            else:
                with lock:
                    raw = flir.get_raw_frame()
            now = time.monotonic()
            elapsed = now - last_time
            last_time = now
            if elapsed > 0:
                fps = 0.8 * fps + 0.2 * (1.0 / elapsed) if fps > 0 else 1.0 / elapsed
            yield render_frame(raw, args, fps=fps)
        except (ThermalError, RuntimeError) as exc:
            if lock is None:
                if args.reset_on_error:
                    reset_flir(flir, reopen=False)
                else:
                    flir.release()
            else:
                with lock:
                    if args.reset_on_error:
                        reset_flir(flir, reopen=False)
                    else:
                        flir.release()
            yield error_frame(str(exc))
            time.sleep(args.error_sleep_s)


def run_window(flir: FLIRLepton25, args: argparse.Namespace) -> None:
    try:
        for frame in frame_loop(flir, args):
            cv2.imshow(args.window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("r"):
                reset_flir(flir, reopen=False)
    finally:
        flir.release()
        cv2.destroyAllWindows()


def run_http(flir: FLIRLepton25, args: argparse.Namespace) -> None:
    from flask import Flask, Response, stream_with_context
    from threading import Lock

    app = Flask(__name__)
    flir_lock = Lock()

    @app.get("/")
    def index():
        return (
            '<form action="/reset" method="post"><button type="submit">Reset FLIR</button></form>'
            '<img src="/thermal_feed" style="image-rendering: pixelated; max-width: 100%;">'
        )

    @app.get("/thermal_feed")
    def thermal_feed():
        def generate():
            for frame in frame_loop(flir, args, flir_lock):
                yield mjpeg_chunk(frame, args.jpeg_quality)

        response = Response(stream_with_context(generate()), content_type=MJPEG_MIMETYPE)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    @app.route("/reset", methods=["GET", "POST"])
    def reset_route():
        with flir_lock:
            reset_flir(flir, reopen=False)
        return "FLIR reset requested\n", 200, {"Content-Type": "text/plain"}

    try:
        print(f"Serving FLIR stream at http://{args.host}:{args.port}/")
        app.run(host=args.host, port=args.port, threaded=True)
    finally:
        flir.release()


def main() -> int:
    args = build_parser().parse_args()
    config = build_config(args)
    print(f"Using FLIR SPI /dev/spidev{config.spi_bus}.{config.spi_device}")
    flir = FLIRLepton25(config)

    if args.http:
        run_http(flir, args)
    else:
        run_window(flir, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
