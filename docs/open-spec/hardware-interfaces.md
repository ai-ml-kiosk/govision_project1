# Hardware Interfaces

This document defines expected hardware connections and software-visible paths.
All commands here are read-only unless explicitly marked otherwise.

## IMX219 CSI Camera

Default module: IMX219-83 CSI camera.

- Interface: Jetson CSI camera connector.
- Software path: Argus/GStreamer through `nvarguscamerasrc`.
- Default single sensor: `sensor-id=0`.
- Default dual sensors: `sensor-id=0` and `sensor-id=1`.

Validation:

```bash
ls -l /dev/video*
python3 test/test_cam.py
```

## FLIR Lepton 2.5

The Lepton uses two interfaces:

- I2C/CCI for control at address `0x2A`.
- SPI/VoSPI for thermal frames.

Current tested defaults:

- CCI/I2C bus: `0`
- CCI address: `0x2A`
- SPI bus/device: `/dev/spidev0.1`
- SPI mode: `3`
- SPI speed: `18_000_000`
- Packet size: `164`
- Frame size: `80x60`

Validation:

```bash
sudo systemctl restart systemd-modules-load.service
i2cdetect -y -r 0
ls -l /dev/spidev*
python3 test/test_flir.py
```

Boot requirement:

- Install `systemd/modules-load.d/govision-spidev.conf` to
  `/etc/modules-load.d/` on each Jetson. This replaces the manual
  `sudo modprobe spidev` step after reboot.

Expected I2C response:

```text
0x2A
```

## Mini OLED 128x64 I2C

Display: 0.96 inch I2C serial white OLED, usually SSD1306.

Jetson Nano 40-pin wiring:

```text
OLED VCC -> Jetson 3.3V, physical pin 1 or 17
OLED GND -> Jetson GND, physical pin 6, 9, 14, 20, 25, 30, 34, or 39
OLED SDA -> Jetson I2C1 SDA, physical pin 3
OLED SCL -> Jetson I2C1 SCL, physical pin 5
```

Defaults:

- I2C port: `/dev/i2c-1`
- Address: `0x3C`
- Resolution: `128x64`

Validation:

```bash
i2cdetect -y -r 1
python3 core/mini_oled.py
```

Use 3.3V I2C logic. Only use 5V VCC if the OLED breakout explicitly supports
it.

## PWM Fan

Software-visible fan path:

```text
/sys/devices/pwm-fan
```

Expected files:

```text
target_pwm
cur_pwm
temp_control
rpm_measured
pwm_cap
```

PWM range:

```text
0..255
```

Typical mapping observed on this Jetson:

```text
0   = off
80  ~= 1000 RPM
120 ~= 2000 RPM
160 ~= 3000 RPM
255 = max
```

Read-only validation:

```bash
cat /sys/devices/pwm-fan/pwm_cap
cat /sys/devices/pwm-fan/temp_control
cat /sys/devices/pwm-fan/target_pwm
cat /sys/devices/pwm-fan/cur_pwm
cat /sys/devices/pwm-fan/rpm_measured
python3 core/fan_control.py --status
```

## Power Monitor

Some Jetson images expose INA power rails through IIO sysfs.

Common rail:

```text
POM_5V_IN
```

Common values:

```text
in_voltage*_input -> millivolts
in_current*_input -> milliamps
in_power*_input   -> milliwatts
```

On some images these files are root-only. Services that display voltage/current
may need to run as root or use a local permission policy.
