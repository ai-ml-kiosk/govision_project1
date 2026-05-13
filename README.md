# GoVision Project

GoVision is a Jetson Nano vision and hardware integration project. It combines
CSI visible camera capture, FLIR Lepton thermal capture, visible/thermal fusion
experiments, a small OLED status display, fan control, and planned local
touchscreen controls.

## Current Hardware Scope

| Hardware | Interface | Current or planned path |
|---|---|---|
| IMX219 visible camera | CSI | `nvarguscamerasrc`, usually `sensor-id=0` |
| FLIR Lepton 2.5 | SPI0 plus I2C0 | `/dev/spidev0.0`, I2C `0x2A` |
| Mini OLED 128x64 | I2C1 | `/dev/i2c-1`, address `0x3C` |
| 2.4 inch SPI touch LCD | SPI1 plus GPIO | Planned LCD `/dev/spidev1.0`, touch `/dev/spidev1.1` |
| Jetson fan | pwm-fan sysfs | `/sys/devices/pwm-fan` |

All J41 GPIO, SPI, I2C, and PWM wiring must use 3.3V logic. Do not connect 5V
logic to Jetson GPIO pins.

## Key Entry Points

- `app.py`: Flask MJPEG routes for camera and thermal streams.
- `core/camera.py`: IMX219 CSI capture helpers.
- `core/thermal.py`: FLIR Lepton SPI capture helpers.
- `core/mini_oled.py`: OLED status display and system health rendering.
- `core/fan_control.py`: Jetson PWM fan controller.
- `core/camera_self.py`, `core/thermal_self.py`, `core/fusion_self.py`:
  desktop-launched local viewers with capture controls.
- `test/`: hardware test and live-view scripts.
- `systemd/`: service templates and module-load configuration.
- `desktop/`: local desktop launchers for self-viewer apps.

## Documentation

- [Open Spec](docs/open-spec/README.md): project-wide hardware, profile,
  services, and operations specification.
- [Hardware Interfaces](docs/open-spec/hardware-interfaces.md): Jetson Nano
  bus allocation and J41 pin wiring for the camera stack, FLIR, OLED, fan, and
  planned LCD/touch display.
- [Device Profile](docs/open-spec/device-profile.md): deployment profile
  fields for each physical unit.
- [Deployment Profile Example](docs/open-spec/deployment-profile.example.toml):
  copyable non-secret example profile.
- [Operations](docs/open-spec/operations.md): commissioning and maintenance
  checks.
- [Camera Test Guide](docs/camera-testing.md): visible camera capture and live
  viewing examples.
- [FLIR Test Guide](docs/flir-testing.md): FLIR SPI auto-detect, still capture,
  live viewing, and troubleshooting.
- [SPI Touch LCD Guide](docs/lcd-touch-display.md): planned 480x320 SPI LCD
  wiring, performance expectations, and driver details to confirm.
- [Fusion Plan](README_Fusion.md): visible/thermal fusion feasibility,
  alignment, and validation notes.

## Source Management

Do not commit or push directly to `main`. When a commit and push is requested,
create a `codex/...` feature branch, commit and push that branch, report the
branch and validation results, then wait for explicit approval before merging
back to `main`.
