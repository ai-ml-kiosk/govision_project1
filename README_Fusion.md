# Sensor Fusion Specification: Vertical Stack

Status: Draft implementation plan

## 1. Hardware Geometry

- **Primary (Visible):** IMX219-83 CSI camera in the lower position.
- **Secondary (Thermal):** FLIR Lepton 2.5 in the upper position.
- **Orientation:** Vertical stack, with the optical axes intended to be roughly parallel.
- **Physical Offset:** The FLIR is mounted above the midpoint of the twin-lens CSI module with about a 35mm vertical baseline. Final alignment must still be tuned in software because parallax changes with subject distance.

## 2. Feasibility Summary

This plan is feasible for a calibrated kiosk-style overlay where the subject distance is reasonably stable. It should not be treated as perfect 3D registration across all depths, because the visible and thermal sensors are physically separated. Close objects and far objects will need slightly different offsets due to parallax.

The current GoVision camera implementation defaults to 1280x720, not 1080p. Fusion should be validated at 1280x720 first, then generalized if a later visible stream profile uses 1920x1080.

Known optical assumptions:

- IMX219-83 lens: about 83° diagonal, 73° horizontal, 50° vertical.
- FLIR Lepton 2.5: 80x60, about 50° horizontal, 63.5° diagonal, 8.6Hz output.

Because the visible camera is wider than the thermal camera horizontally, the visible frame needs a center crop before overlay. The vertical crop/offset should be calibrated rather than hard-coded from the physical offset alone.

## 3. Image Registration Logic

Recommended registration pipeline:

1. Capture the latest visible BGR frame and one raw thermal frame.
2. Crop the visible frame to approximate the Lepton field of view.
3. Apply calibrated x/y offsets for the vertical stack and mounting tolerances.
4. Resize the 80x60 thermal frame to the cropped visible dimensions.
5. Colorize or threshold the thermal data depending on the selected fusion mode.
6. Blend or composite the result back into a stream-sized output frame.

Initial crop estimates for the fusion self-viewer:

- Visible crop width ratio: start around `0.64`, based on 50° thermal horizontal FoV over 73° visible horizontal FoV.
- Visible crop height ratio: start at `1.0` for the 480x320 self-viewer surface, then tune using calibration captures.
- Thermal y offset: start around `-24` display pixels because the FLIR is above the CSI center; negative y shifts the thermal overlay up.
- Offset controls: expose at least `x_offset_px` and `y_offset_px` because physical mounting and working distance dominate the final alignment.

These numbers are only starting points. The saved calibration should be the source of truth for each device.

## 4. Fusion Modes

### Classic Overlay

Blend thermal color over visible:

```python
fused = alpha * thermal_color + (1.0 - alpha) * visible_crop
```

Use fixed or slowly adapting thermal min/max values. Per-frame min/max normalization will make colors flicker and can hide real temperature changes.

### Edge-Infused Overlay

Extract Canny edges from the visible crop and draw them over the thermal colormap. This is MSX-style, not true FLIR MSX.

Expected flow:

1. Convert visible crop to grayscale.
2. Run light blur plus Canny.
3. Dilate edges by 1px if needed.
4. Draw dark or bright edge pixels over the resized thermal color frame.

### Thermal Threshold

Use raw thermal values converted to Celsius, not colorized pixels.

Expected flow:

1. Convert raw Lepton TLinear data to Celsius.
2. Resize the Celsius map to the visible crop dimensions.
3. Create a mask where temperature is above the threshold, such as 35°C.
4. Show thermal color only inside the mask; show visible pixels elsewhere.

The threshold should be configurable because radiometric accuracy, emissivity, environment, and calibration state affect measured temperature.

## 5. Implementation Plan

Add `core/fusion.py` with:

- `FusionConfig`
- `FusionMode`
- `crop_visible_for_thermal()`
- `resize_thermal_to_visible()`
- `fuse_classic_overlay()`
- `fuse_edge_overlay()`
- `fuse_thermal_threshold()`
- `create_fusion_frame()`

Add a Flask route:

```text
/fusion_feed
```

Useful query/config options:

```text
mode=classic|edge|threshold
alpha=0.45
threshold_c=35
x_offset_px=0
y_offset_px=0
thermal_min_c=20
thermal_max_c=45
```

Add a lightweight calibration tool that captures synchronized visible/thermal pairs into `results/` with the active fusion parameters. The tool should not write calibration into the repository by default; per-device calibration belongs in a deployment profile.

## 6. Validation Plan

### Local Software Validation

- `python3 -m py_compile app.py core/*.py`
- Synthetic unit checks for crop bounds, resize shape, alpha blending, and threshold masks.
- Flask route import check:

```bash
python3 -c "from app import app; print(app.url_map)"
```

### Jetson Hardware Validation

Use read-only diagnostics first:

```bash
ls -l /dev/video*
ls -l /dev/spidev*
i2cdetect -y -r 0
python3 test/test_cam.py
python3 test/test_flir.py
```

Expected hardware paths from the open spec:

- Visible camera: `sensor-id=0`
- Lepton CCI/I2C: bus `0`, address `0x2A`
- Lepton SPI: `/dev/spidev0.0`

### Alignment Validation

Use a target visible to both cameras:

- A flat board with visible corner marks.
- Small warm points or a warm object placed at known corners/center.
- Captures at the expected kiosk distance, plus near and far sanity checks.

Acceptance target:

- Warm landmarks should land within about 1 to 2 Lepton pixels at the chosen deployment distance.
- Alignment drift at other distances should be documented, not hidden.

### Runtime Validation

- Confirm `/fusion_feed` stays responsive for at least 10 minutes.
- Measure output FPS; expect the fused stream to be limited by the Lepton's 8.6Hz frame rate.
- Confirm visible-only and thermal-only streams still work after fusion stream errors.
- Confirm all camera and SPI resources are released on process exit.

## 7. Risks And Mitigations

- **Depth-dependent parallax:** Calibrate for the main kiosk distance and document expected drift.
- **Thermal frame rate:** Run fusion at thermal speed and reuse the latest visible frame.
- **Color flicker:** Avoid per-frame min/max for operator-facing views.
- **Orientation mismatch:** Keep `flip_method`, `flip_code`, and offsets configurable.
- **Temperature threshold accuracy:** Treat thresholds as operational heuristics unless calibrated against a known reference.
- **CPU load:** Prefer simple OpenCV operations first; optimize only after measuring on the Jetson.

## 8. Helpful Codex Skills To Add

These project-specific skills would make execution easier:

- `govision-hardware-check`: safe read-only Jetson diagnostics for camera, SPI, I2C, fan, OpenCV/GStreamer, and systemd status.
- `govision-fusion-calibrate`: workflow for capturing paired frames, tuning crop/offset/threshold values, and writing non-secret calibration output.
- `govision-flask-stream`: patterns for adding defensive MJPEG routes that open hardware lazily and release resources cleanly.
- `govision-service-deploy`: systemd validation, install notes, rollback steps, and service log triage for GoVision deployments.

The first two are the highest-value skills before implementation because they encode the hardware safety rules and the calibration workflow that will be repeated on each Jetson.
