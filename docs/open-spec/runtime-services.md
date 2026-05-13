# Runtime Services

GoVision services are managed with systemd templates in `systemd/`.

## Service Inventory

### `govision-oled.service`

Purpose:

- Display time, IP, temperatures, health, voltage/current/power, and uptime on
  the mini OLED.

Runs as:

- `root`, because INA3221 voltage/current/power sysfs files may be root-only.

Command:

```bash
/usr/bin/python3 /home/jetson/workspace/GoVision_proj1/core/mini_oled.py
```

### `govision-fan-control.service`

Purpose:

- Apply temperature-based PWM fan control after boot.

Runs as:

- `root`, because `/sys/devices/pwm-fan/target_pwm` and `temp_control` require
  root writes.

Command:

```bash
/usr/bin/python3 /home/jetson/workspace/GoVision_proj1/core/fan_control.py --interval 5
```

### Planned `govision-lcd-touch.service`

Status: not implemented yet.

Expected purpose:

- Drive the 2.4 inch 480x320 SPI LCD and touch controller for local preview and
  controls.
- Use SPI1 only: LCD on `/dev/spidev1.0`, touch on `/dev/spidev1.1`.
- Avoid sharing the FLIR SPI0 bus.
- Drop stale preview frames instead of queueing them.

## Installation

Install Python dependencies:

```bash
cd /home/jetson/workspace/GoVision_proj1
sudo python3 -m pip install -r requirements.txt
```

Install boot-time kernel module loading:

```bash
sudo cp systemd/modules-load.d/govision-spidev.conf /etc/modules-load.d/
sudo systemctl restart systemd-modules-load.service
```

Install services:

```bash
sudo cp systemd/govision-oled.service /etc/systemd/system/
sudo cp systemd/govision-fan-control.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable govision-oled.service
sudo systemctl enable govision-fan-control.service
```

Start services:

```bash
sudo systemctl start govision-oled.service
sudo systemctl start govision-fan-control.service
```

Check services:

```bash
sudo systemctl status govision-oled.service
sudo systemctl status govision-fan-control.service
journalctl -u govision-oled.service -f
journalctl -u govision-fan-control.service -f
```

## Failure Policy

- Services use `Restart=always`.
- Hardware-specific modules should raise clear errors when devices are absent.
- Missing optional metrics should show `--` rather than fail the process.
- Fan service should restore kernel fan auto control on graceful stop.

## Permissions

Root is currently required for:

- INA3221 voltage/current/power sysfs reads on some images.
- PWM fan writes.
- Installing boot-time kernel module configuration under `/etc/modules-load.d`.

If a deployment must avoid root services, create a local udev or tmpfiles policy
that grants read/write access only to the required sysfs paths.
