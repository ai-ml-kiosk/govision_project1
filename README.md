# GoVision Project

GoVision is a Jetson Nano vision and kiosk hardware project. It combines CSI
visible camera capture, FLIR Lepton thermal capture, visible/thermal fusion
experiments, a local OLED status display, PWM fan control, desktop viewers,
and Flask MJPEG streams.

The project is designed for live NVIDIA Jetson hardware. Camera, SPI, I2C,
thermal, display, fan, and GPIO paths should be inspected before changing
behavior, and device-specific calibration or generated captures should stay out
of source control.

## Current Hardware Scope

| Hardware | Interface | Current or planned path |
|---|---|---|
| IMX219 visible camera | CSI | `nvarguscamerasrc`, usually `sensor-id=0` |
| FLIR Lepton 2.5 | SPI0 plus I2C0 | `/dev/spidev0.0`, I2C `0x2A` |
| Mini OLED 128x64 | I2C1 | `/dev/i2c-1`, address `0x3C` |
| Jetson fan | pwm-fan sysfs | `/sys/devices/pwm-fan` |

All J41 GPIO, SPI, I2C, and PWM wiring must use 3.3V logic. Do not connect 5V
logic to Jetson GPIO pins.

## Current Capabilities

- Visible IMX219 capture through Jetson GStreamer and OpenCV.
- FLIR Lepton 2.5 VoSPI capture with SPI auto-detection helpers.
- One-shot visible, thermal, and visible-plus-thermal fusion sample captures.
- Desktop-launched visible, thermal, and fusion viewers with capture controls.
- Live visible and thermal viewers with local OpenCV windows or MJPEG browser
  streams.
- Flask MJPEG routes for visible and thermal feeds.
- SSD1306 mini OLED health display for IP, temperature, load, fan RPM, memory,
  disk, power, uptime, and warnings.
- Quiet temperature-based Jetson PWM fan controller.
- systemd service templates for OLED, fan control, and boot-time SPI module
  loading.

## Repository Layout

- [app.py](app.py): Flask MJPEG application entrypoint.
- [core/camera.py](core/camera.py): IMX219 camera helpers.
- [core/thermal.py](core/thermal.py): FLIR Lepton capture, SPI probing, and
  frame conversion helpers.
- [core/mini_oled.py](core/mini_oled.py): mini OLED health display renderer.
- [core/fan_control.py](core/fan_control.py): Jetson PWM fan controller.
- `core/camera_self.py`, `core/thermal_self.py`, `core/fusion_self.py`:
  desktop-launched local viewers with capture controls.
- [test/](test): hardware test and live-view utilities.
- [systemd/](systemd): service templates and module-load configuration.
- [desktop/](desktop): local desktop launchers for self-viewer apps.
- [docs/](docs): operating guides and open specification documents.
- `results/`: generated sample images and logs. Do not commit deployment
  captures or calibration artifacts unless they are intentionally sanitized.

## Documentation Map

- [Open Spec](docs/open-spec/README.md): project goals, implementation
  baseline, and spec index.
- [Hardware Interfaces](docs/open-spec/hardware-interfaces.md): Jetson Nano bus
  allocation and J41 pin wiring for the camera stack, FLIR, OLED, and fan.
- [Device Profile](docs/open-spec/device-profile.md): expected per-device
  configuration fields.
- [Deployment Profile Example](docs/open-spec/deployment-profile.example.toml):
  copyable profile template for a new Jetson deployment.
- [Module Contracts](docs/open-spec/module-contracts.md): reusable Python API
  and behavior contracts.
- [Runtime Services](docs/open-spec/runtime-services.md): systemd service
  behavior, commands, permissions, and failure policy.
- [Operations](docs/open-spec/operations.md): commissioning, validation,
  maintenance, and rollback procedures.
- [Camera Test Guide](docs/camera-testing.md): visible-camera still capture,
  live viewing, orientation, resolution, and latency tuning.
- [FLIR Test Guide](docs/flir-testing.md): FLIR SPI auto-detect, still capture,
  live viewing, sensitivity tuning, and troubleshooting.
- [Fusion Plan](README_Fusion.md): visible and thermal sensor-fusion
  feasibility, calibration, implementation, and validation plan.
- [Source Management](docs/source-management.md): required branch workflow,
  approval policy, and GitHub main-branch protection guidance.
- [Agent Instructions](AGENTS.md): project-specific hardware safety and
  repository workflow rules for Codex or other coding agents.

## Common Hardware Checks

Use read-only diagnostics before changing hardware-facing behavior:

```bash
ls -l /dev/video*
ls -l /dev/spidev*
i2cdetect -y -r 0
python3 core/fan_control.py --status
systemctl is-active govision-oled.service govision-fan-control.service
```

Run lightweight Python checks before service deployment:

```bash
python3 -m py_compile app.py core/*.py
```

## Test Utilities

Visible camera:

```bash
python3 test/test_cam.py
python3 test/test_video_cam.py --http
```

FLIR thermal camera:

```bash
python3 test/test_flir.py --scan-only
python3 test/test_flir.py
python3 test/test_video_flir.py --http
```

Fusion sample:

```bash
python3 test/test_fusion.py
```

Generated images are written to `results/`.

## Services

The service templates live in [systemd/](systemd):

- `govision-oled.service`
- `govision-fan-control.service`
- `modules-load.d/govision-spidev.conf`

See [Runtime Services](docs/open-spec/runtime-services.md) and
[Operations](docs/open-spec/operations.md) before installing, restarting, or
rolling back services on a live Jetson.

## Source Management

Direct pushes to `main` are not part of the project workflow. Commit and push
requests should use a feature branch, wait for explicit approval, and merge back
to `main` only after approval.

See [Source Management](docs/source-management.md) for the full workflow and
GitHub branch protection setup.
