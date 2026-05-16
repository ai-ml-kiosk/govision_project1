# Hardware Interfaces

This document defines expected Jetson Nano hardware connections and
software-visible paths. All commands here are read-only unless explicitly
marked otherwise.

Use Jetson Nano J41 physical pin numbers in wiring notes. Jetson GPIO is 3.3V
logic only. Do not feed 5V logic into GPIO, SPI, I2C, PWM, or reset pins.

## Resource Summary

Current and planned bus allocation:

| Resource | Assignment | Notes |
|---|---|---|
| CSI connector | IMX219 visible camera | Does not consume J41 GPIO pins. |
| SPI0 `/dev/spidev0.0` | FLIR Lepton VoSPI | Active path observed on this Jetson. |
| SPI0 `/dev/spidev0.1` | Spare on SPI0 | Keep available for future SPI hardware. |
| I2C0 `/dev/i2c-0` | FLIR Lepton CCI/control | Expected address `0x2A`. |
| I2C1 `/dev/i2c-1` | Mini OLED | Expected address `0x3C`. |
| `/sys/devices/pwm-fan` | Jetson fan controller | Sysfs fan path, not J41 SPI. |

## J41 Pin Allocation

| J41 pin | Current or planned use | Signal |
|---:|---|---|
| 1 or 17 | 3.3V logic power | 3.3V |
| 2 or 4 | Optional 5V module power | 5V, only if breakout supports it |
| 3 | OLED SDA | I2C1 SDA |
| 5 | OLED SCL | I2C1 SCL |
| 6, 9, 14, 20, 25, 30, 34, 39 | Ground | GND |
| 19 | FLIR SPI data out from Jetson | SPI0 MOSI |
| 21 | FLIR SPI data into Jetson | SPI0 MISO |
| 23 | FLIR SPI clock | SPI0 SCK |
| 24 | FLIR SPI chip select | SPI0 CS0, `/dev/spidev0.0` |
| 26 | Spare SPI0 chip select | SPI0 CS1, `/dev/spidev0.1` |
| 27 | FLIR CCI/control SDA | I2C0 SDA |
| 28 | FLIR CCI/control SCL | I2C0 SCL |

## IMX219 CSI Camera

Default module: IMX219-83 CSI camera, including the current twin-lens CSI
camera assembly.

- Interface: Jetson CSI camera connector.
- Software path: Argus/GStreamer through `nvarguscamerasrc`.
- Default single sensor: `sensor-id=0`.
- Default dual sensors: `sensor-id=0` and `sensor-id=1`.
- J41 impact: none.

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
- SPI bus/device: `/dev/spidev0.0`
- SPI mode: `3`
- SPI speed: `18_000_000`
- Packet size: `164`
- Frame size: `80x60`

Current fusion mount geometry:

- The twin CSI lenses are separated by about 55mm.
- The FLIR is mounted near the middle of the twin-lens module, about 27.5mm
  horizontally from either CSI lens.
- The FLIR is about 8mm below the CSI lens centerline.
- The FLIR module is physically rotated 180 degrees compared with the previous
  mount.
- Initial fusion viewer defaults are `FUSION_THERMAL_OFFSET_X=19`,
  `FUSION_THERMAL_OFFSET_Y=-4`, and `FUSION_THERMAL_FLIP_CODE=none`. Use
  `FUSION_THERMAL_OFFSET_X=-19` instead if the active CSI lens is on the other
  side of the FLIR.

Jetson Nano J41 wiring:

| FLIR signal | J41 physical pin | Jetson signal |
|---|---:|---|
| VIN/VCC | 1 or 17 | 3.3V, unless the carrier explicitly requires 5V |
| GND | Any J41 GND | Ground |
| CCI SDA | 27 | I2C0 SDA |
| CCI SCL | 28 | I2C0 SCL |
| SPI SCK | 23 | SPI0 SCK |
| SPI MISO / VoSPI data | 21 | SPI0 MISO |
| SPI MOSI, if present on carrier | 19 | SPI0 MOSI |
| SPI CS | 24 | SPI0 CS0, `/dev/spidev0.0` |
| RESET/RST/EN, optional | Unassigned | Any unused 3.3V GPIO, configured as `FLIR_RESET_BOARD_PIN` |

Optional reset notes:

- The reset/enable line is not required for normal FLIR capture.
- Only wire it if the FLIR breakout exposes a documented `RESET`, `RST`, `EN`,
  or `PWR_EN` input.
- Use Jetson J41 physical pin numbering for `FLIR_RESET_BOARD_PIN`.
- Do not reuse OLED, fan, CSI, SPI0, or I2C pins for FLIR reset.
- The software default reset pulse is active-low; use `--reset-active-high`
  only when the breakout documents an active-high input.

Validation:

```bash
i2cdetect -y -r 0
ls -l /sys/class/spidev
python3 test/test_flir.py --scan-only
python3 test/test_flir.py
```

Expected I2C response:

```text
0x2A
```

Boot requirement:

- Install `systemd/modules-load.d/govision-spidev.conf` to
  `/etc/modules-load.d/` on each Jetson. This replaces the manual
  `sudo modprobe spidev` step after reboot.

## Mini OLED 128x64 I2C

Display: 0.96 inch I2C serial white OLED, usually SSD1306.

Jetson Nano J41 wiring:

| OLED signal | J41 physical pin | Jetson signal |
|---|---:|---|
| VCC | 1 or 17 | 3.3V |
| GND | Any J41 GND | Ground |
| SDA | 3 | I2C1 SDA |
| SCL | 5 | I2C1 SCL |

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
