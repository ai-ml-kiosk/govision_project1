# GoVision Open Spec

Status: Draft v0.1
Scope: GoVision Jetson kiosk deployments with visible camera, thermal camera,
OLED status display, PWM fan control, Flask MJPEG streams, and hardware health
monitoring.

## Goals

- Keep hardware behavior consistent across multiple Jetson devices.
- Make each deployment reproducible from a written profile.
- Separate device-specific values from reusable Python modules.
- Prefer read-only diagnostics before touching hardware.
- Keep services restartable, observable, and safe after reboot.
- Avoid storing secrets, private keys, Wi-Fi credentials, or site-specific
identifiers in the repository.

## Spec Documents

- [Device Profile](device-profile.md): required per-device configuration fields.
- [Hardware Interfaces](hardware-interfaces.md): expected wiring, buses, and
  sysfs paths.
- [Module Contracts](module-contracts.md): Python class/API contracts.
- [Runtime Services](runtime-services.md): systemd behavior and permissions.
- [Operations](operations.md): commissioning, validation, and maintenance.
- [Deployment Profile Example](deployment-profile.example.toml): copyable
  template for new devices.
- [Camera Test Guide](../camera-testing.md): IMX219 still capture, live
  streaming, orientation, resolution, and troubleshooting examples.
- [FLIR Test Guide](../flir-testing.md): SPI auto-detect, still capture,
  live streaming, tuning, and troubleshooting examples.

## Baseline Implementation

The current implementation uses:

- `core/camera.py` for IMX219 CSI camera capture.
- `core/thermal.py` for FLIR Lepton 2.5 VoSPI capture.
- `core/mini_oled.py` for SSD1306 OLED health display.
- `core/fan_control.py` for temperature-based PWM fan control.
- `app.py` for Flask MJPEG routes.
- `systemd/` for boot-time service templates.

## Versioning Rules

- Spec changes should be committed with implementation changes when behavior
  changes.
- New hardware support must update the device profile schema and hardware
  interface notes.
- Existing profile keys should remain backward compatible where practical.
- Breaking changes should increment the draft version and include migration
  notes in [Operations](operations.md).
