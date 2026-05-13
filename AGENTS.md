# AGENTS.md

## Project Context

GoVision_proj1 is intended to run on NVIDIA Jetson hardware with local camera,
serial, and kiosk-style hardware integrations.

## Jetson / Hardware Rules

- Treat the Jetson as a live hardware target. Do not assume cameras, serial
  devices, GPIO, USB peripherals, or display outputs are safe to access without
  checking the current environment first.
- Before changing hardware-facing behavior, inspect the existing code paths and
  preserve established device names, baud rates, camera indexes, GStreamer
  pipelines, and timing assumptions unless the task explicitly requires a change.
- Do not run destructive hardware, power, firmware, flash, or system service
  commands unless the user explicitly asks for them.
- Prefer read-only diagnostics first for hardware troubleshooting, such as
  listing `/dev/video*`, `/dev/tty*`, USB devices, process status, and relevant
  logs.
- Keep camera handling defensive. Always release OpenCV camera resources and
  handle missing or busy cameras gracefully.
- Keep serial handling defensive. Use explicit timeouts, close ports cleanly,
  and avoid blocking the Flask request thread indefinitely.
- Avoid committing device-specific secrets, tokens, credentials, private keys,
  Wi-Fi details, or production kiosk identifiers.
- When adding dependencies, keep them compatible with Jetson Linux and Python
  environments. Prefer common packages already supported on ARM64.
- For web UI changes, keep the Flask app usable locally on the Jetson display
  and over the LAN when appropriate.
- Verify changes with lightweight local checks when hardware is unavailable,
  and clearly note any behavior that still needs validation on the physical
  Jetson.

## Repository Workflow

- Keep implementation changes scoped and easy to inspect.
- Do not overwrite user changes or generated calibration/configuration files.
- Use Git history intentionally: make small commits only when requested.
- Do not commit or push directly to `main`. When a commit and push is requested,
  create a feature branch first, commit and push that branch, report the branch
  and validation results, then wait for explicit approval before merging back to
  `main`.
