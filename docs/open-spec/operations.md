# Operations

This document defines repeatable checks for commissioning and maintaining a
GoVision deployment.

## Commissioning Checklist

1. Confirm OS time and timezone.

```bash
date '+%Y-%m-%d %H:%M %Z %z'
```

2. Confirm camera hardware.

```bash
ls -l /dev/video*
python3 test/test_cam.py
```

3. Confirm FLIR control path.

```bash
i2cdetect -y -r 0
```

Expected address:

```text
0x2A
```

4. Confirm FLIR SPI path.

```bash
sudo systemctl restart systemd-modules-load.service
ls -l /dev/spidev*
python3 test/test_flir.py
```

5. Confirm OLED I2C path.

```bash
i2cdetect -y -r 1
python3 core/mini_oled.py
```

Expected address:

```text
0x3C
```

6. Confirm fan status.

```bash
python3 core/fan_control.py --status
```

7. Confirm Flask imports and routes.

```bash
python3 -c "from app import app; print(app.url_map)"
```

## Service Validation

```bash
systemd-analyze verify systemd/govision-oled.service
systemd-analyze verify systemd/govision-fan-control.service
```

After installation:

```bash
sudo systemctl status govision-oled.service
sudo systemctl status govision-fan-control.service
```

## Rollback

Restore kernel fan auto control:

```bash
sudo python3 core/fan_control.py --restore-auto
sudo systemctl stop govision-fan-control.service
sudo systemctl disable govision-fan-control.service
```

Stop OLED service:

```bash
sudo systemctl stop govision-oled.service
sudo systemctl disable govision-oled.service
```

## Generated Artifacts

The following should not be committed:

```text
results/
__pycache__/
test/lepton_success.jpg
```

## Deployment Notes

- Record all bus numbers and addresses in a deployment profile.
- Install `systemd/modules-load.d/govision-spidev.conf` to
  `/etc/modules-load.d/` so `spidev` loads automatically after reboot.
- Record any camera orientation flips.
- Record fan behavior after installation.
- Keep production secrets outside the repository.
- When troubleshooting hardware, prefer read-only commands first.
