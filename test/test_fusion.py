from pathlib import Path
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.camera import CameraConfig, IMX219Camera
from core.thermal import (
    FLIRLepton25,
    LeptonConfig,
    ThermalError,
    config_with_detected_spidev,
    parse_spi_candidates,
    tlinear_to_celsius,
)


def env_int(name, default):
    return int(os.getenv(name, str(default)))


def env_float(name, default):
    return float(os.getenv(name, str(default)))


def env_int_optional(name):
    value = os.getenv(name)
    return None if value is None else int(value)


def crop_visible(frame, crop_width, crop_height, x_offset, y_offset):
    height, width = frame.shape[:2]
    crop_width = min(crop_width, width)
    crop_height = min(crop_height, height)

    center_x = width // 2 + x_offset
    center_y = height // 2 + y_offset
    left = max(0, min(width - crop_width, center_x - crop_width // 2))
    top = max(0, min(height - crop_height, center_y - crop_height // 2))
    return frame[top : top + crop_height, left : left + crop_width], left, top


def colorize_temps(temps_c, min_c, max_c):
    if max_c <= min_c:
        max_c = min_c + 1.0

    normalized = ((temps_c - min_c) * 255.0) / (max_c - min_c)
    normalized = np.clip(normalized, 0, 255).astype(np.uint8)
    return cv2.applyColorMap(normalized, cv2.COLORMAP_JET)


def edge_overlay(visible_crop, thermal_color):
    gray = cv2.cvtColor(visible_crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(gray, 60, 140)
    edges = cv2.dilate(edges, np.ones((2, 2), dtype=np.uint8), iterations=1)

    output = thermal_color.copy()
    output[edges > 0] = (255, 255, 255)
    return output


def annotate(output, lines):
    line_height = 30
    panel_width = min(output.shape[1] - 16, 780)
    panel_height = 18 + line_height * len(lines)
    cv2.rectangle(output, (8, 8), (8 + panel_width, 8 + panel_height), (0, 0, 0), -1)
    for index, line in enumerate(lines):
        cv2.putText(
            output,
            line[:92],
            (16, 36 + index * line_height),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.72,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )


def main():
    results_dir = Path(__file__).resolve().parents[1] / "results"
    results_dir.mkdir(exist_ok=True)

    mode = os.getenv("FUSION_MODE", "classic").strip().lower()
    alpha = max(0.0, min(1.0, env_float("FUSION_ALPHA", 0.45)))
    threshold_c = env_float("FUSION_THRESHOLD_C", 35.0)
    crop_width_override = env_int_optional("FUSION_CROP_WIDTH")
    crop_height_override = env_int_optional("FUSION_CROP_HEIGHT")
    x_offset = env_int("FUSION_X_OFFSET_PX", 0)
    y_offset = env_int("FUSION_Y_OFFSET_PX", 0)
    tlinear_scale = env_float("FLIR_TLINEAR_SCALE", 100.0)
    output_scale = env_float("FUSION_OUTPUT_SCALE", 1.0)
    output_path = Path(os.getenv("FUSION_OUTPUT", results_dir / "test_fusion.jpg"))

    base_flir_config = LeptonConfig(
        spi_bus=env_int("FLIR_SPI_BUS", LeptonConfig.spi_bus),
        spi_device=env_int("FLIR_SPI_DEVICE", LeptonConfig.spi_device),
        spi_speed_hz=env_int("FLIR_SPI_SPEED_HZ", LeptonConfig.spi_speed_hz),
        max_frame_attempts=env_int("FLIR_MAX_FRAME_ATTEMPTS", 8),
        max_sync_packets=env_int("FLIR_MAX_SYNC_PACKETS", 20_000),
        resync_delay_s=env_float("FLIR_RESYNC_DELAY_S", LeptonConfig.resync_delay_s),
    )
    forced_spi = "FLIR_SPI_BUS" in os.environ or "FLIR_SPI_DEVICE" in os.environ
    auto_detect = os.getenv("FLIR_AUTO_DETECT", "1").strip().lower() not in ("0", "false", "no")
    flir_config = base_flir_config
    if auto_detect and not forced_spi:
        flir_config = config_with_detected_spidev(
            base_flir_config,
            candidates=parse_spi_candidates(os.getenv("FLIR_SPI_CANDIDATES", "0.0,0.1,1.0,1.1")),
            probe_speed_hz=env_int("FLIR_PROBE_SPEED_HZ", 2_000_000),
        )

    camera_config = CameraConfig(
        capture_width=env_int("CAMERA_CAPTURE_WIDTH", CameraConfig.capture_width),
        capture_height=env_int("CAMERA_CAPTURE_HEIGHT", CameraConfig.capture_height),
        display_width=env_int("CAMERA_DISPLAY_WIDTH", CameraConfig.display_width),
        display_height=env_int("CAMERA_DISPLAY_HEIGHT", CameraConfig.display_height),
        framerate=env_int("CAMERA_FRAMERATE", CameraConfig.framerate),
        flip_method=env_int("CAMERA_FLIP_METHOD", CameraConfig.flip_method),
        sensor_mode=env_int_optional("CAMERA_SENSOR_MODE"),
    )
    camera = IMX219Camera(sensor_id=env_int("CAMERA_SENSOR_ID", 0), config=camera_config)
    flir = FLIRLepton25(flir_config)

    try:
        visible = camera.get_frame()
        crop_width = crop_width_override or round(visible.shape[1] * 0.633)
        crop_height = crop_height_override or round(visible.shape[0] * 0.750)
        try:
            raw = flir.get_raw_frame()
        except (ThermalError, RuntimeError) as exc:
            visible_crop, left, top = crop_visible(
                visible,
                crop_width=crop_width,
                crop_height=crop_height,
                x_offset=x_offset,
                y_offset=y_offset,
            )
            output = visible.copy()
            cv2.rectangle(
                output,
                (left, top),
                (left + visible_crop.shape[1] - 1, top + visible_crop.shape[0] - 1),
                (0, 255, 255),
                2,
            )
            annotate(
                output,
                [
                    "Fusion diagnostic: visible capture OK",
                    f"Thermal capture failed: {exc}",
                    f"Crop: {visible_crop.shape[1]}x{visible_crop.shape[0]} at {left},{top}",
                ],
            )
            if output_scale != 1.0:
                output = cv2.resize(output, None, fx=output_scale, fy=output_scale)
            if not cv2.imwrite(str(output_path), output):
                raise RuntimeError(f"Unable to write {output_path}")
            print(f"Wrote {output_path} with thermal diagnostic")
            return

        flip_code = os.getenv("FLIR_FLIP_CODE", "0").strip().lower()
        if flip_code not in ("", "none"):
            raw = cv2.flip(raw, int(flip_code))

        temps_c = tlinear_to_celsius(raw, scale=tlinear_scale)
        min_c = env_float("FUSION_THERMAL_MIN_C", float(np.percentile(temps_c, 2)))
        max_c = env_float("FUSION_THERMAL_MAX_C", float(np.percentile(temps_c, 98)))

        visible_crop, left, top = crop_visible(
            visible,
            crop_width=crop_width,
            crop_height=crop_height,
            x_offset=x_offset,
            y_offset=y_offset,
        )

        target_size = (visible_crop.shape[1], visible_crop.shape[0])
        thermal_color = colorize_temps(temps_c, min_c=min_c, max_c=max_c)
        thermal_color = cv2.resize(thermal_color, target_size, interpolation=cv2.INTER_CUBIC)
        temps_resized = cv2.resize(temps_c, target_size, interpolation=cv2.INTER_CUBIC)

        blended = cv2.addWeighted(thermal_color, alpha, visible_crop, 1.0 - alpha, 0)
        if mode == "classic":
            fused_crop = blended
        elif mode == "edge":
            fused_crop = edge_overlay(visible_crop, thermal_color)
        elif mode == "threshold":
            mask = temps_resized >= threshold_c
            fused_crop = visible_crop.copy()
            fused_crop[mask] = blended[mask]
        else:
            raise ValueError("FUSION_MODE must be classic, edge, or threshold")

        output = visible.copy()
        output[top : top + fused_crop.shape[0], left : left + fused_crop.shape[1]] = fused_crop
        cv2.rectangle(
            output,
            (left, top),
            (left + fused_crop.shape[1] - 1, top + fused_crop.shape[0] - 1),
            (255, 255, 255),
            2,
        )
        annotate(
            output,
            [
                f"Fusion: {mode} alpha={alpha:.2f}",
                f"Temp: {float(np.min(temps_c)):.1f}C..{float(np.max(temps_c)):.1f}C",
                f"Crop: {visible_crop.shape[1]}x{visible_crop.shape[0]} at {left},{top}",
            ],
        )

        if output_scale != 1.0:
            output = cv2.resize(output, None, fx=output_scale, fy=output_scale)
        if not cv2.imwrite(str(output_path), output):
            raise RuntimeError(f"Unable to write {output_path}")

        print(f"Wrote {output_path}")
    finally:
        camera.release()
        flir.release()


if __name__ == "__main__":
    main()
