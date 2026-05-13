# Module Contracts

This document defines stable Python interfaces for the GoVision core modules.

## Camera

Module: `core.camera`

Classes:

- `CameraConfig`
- `IMX219Camera`
- `DualIMX219Camera`
- `CameraError`

Contract:

- Constructors must not touch hardware.
- `open()` opens hardware lazily.
- `get_frame()` returns BGR `numpy.ndarray` frames.
- `release()` frees OpenCV resources.
- Missing or busy cameras raise `CameraError`.
- Dual capture returns `(left_frame, right_frame)`.

Default visible camera behavior:

```python
from core.camera import IMX219Camera

camera = IMX219Camera(sensor_id=0)
frame = camera.get_frame()
camera.release()
```

## Thermal

Module: `core.thermal`

Classes and helpers:

- `LeptonConfig`
- `FLIRLepton25`
- `ThermalError`
- `normalize_14bit_to_8bit()`
- `apply_jet_colormap()`
- `tlinear_to_celsius()`

Contract:

- Constructors must not touch SPI hardware.
- `open()` opens `/dev/spidevX.Y` lazily.
- `get_raw_frame()` returns an `80x60 uint16` raw frame.
- `get_frame(colorize=True)` returns OpenCV JET BGR output.
- `release()` closes SPI.
- TLinear temperature conversion assumes Kelvin-scaled raw values.
- SPI capture uses VoSPI packet scanning and resets on row `0`.

Default tested thermal path:

```text
/dev/spidev0.0 at 18 MHz
```

## Mini OLED

Module: `core.mini_oled`

Classes and helpers:

- `OLEDConfig`
- `DeviceHealth`
- `MiniOLED`
- `OLEDDisplayError`
- `collect_device_health()`

Contract:

- Constructors must not touch I2C hardware.
- `collect_device_health()` must work without OLED hardware.
- `show_status()` collects health and renders OLED lines.
- Local OS timezone is used by default.
- Missing `luma.oled` raises `OLEDDisplayError` only when display access is
  attempted.
- Voltage/current/power display should show `--` when sysfs readings are not
  available or not readable.
- Load should be displayed as 1-minute load normalized by CPU count, not raw
  load average.
- Fan RPM is read best-effort from `/sys/devices/pwm-fan/rpm_measured` and
  shown as `--` when unavailable.
- Status rows below the IP line should use compact two-column formatting with
  field labels ending in `:`.

## SPI Touch LCD

Status: planned hardware addition; no stable Python module contract exists yet.

Expected future module shape:

- Constructor must not touch SPI or GPIO hardware.
- Display open/init should happen lazily.
- LCD should use `/dev/spidev1.0` by default.
- Touch should use `/dev/spidev1.1` by default.
- LCD DC/RS, reset, backlight, and touch IRQ must be configurable by J41
  physical pin number.
- Refresh loops should drop stale preview frames instead of queueing them.
- Missing LCD or touch hardware should not break CSI, FLIR, OLED, fan, or Flask
  behavior.

## Fan Control

Module: `core.fan_control`

Classes and helpers:

- `FanConfig`
- `FanStatus`
- `FanController`
- `FanControlError`
- `pwm_for_temp()`
- `cpu_gpu_temps()`

Contract:

- `--status` must not write PWM.
- `apply_once()` writes one PWM update.
- `run_forever()` updates PWM on an interval.
- PWM output must be clamped to configured min/max.
- The controller should restore kernel fan auto control on service stop.

Default quiet fan curve:

```text
35C -> PWM 0
45C -> PWM 0
55C -> PWM 80
65C -> PWM 120
75C -> PWM 180
82C -> PWM 255
```

The previous more aggressive cooling behavior remains available with
`--preset cool`.

## Flask App

Module: `app.py`

Routes:

- `/video_feed`
- `/thermal_feed`

Contract:

- Routes use MJPEG streaming with:

```text
multipart/x-mixed-replace; boundary=frame
```

- Hardware is opened lazily.
- Hardware errors should produce placeholder frames instead of crashing the
  stream generator.
- Resources are released on process exit where practical.
