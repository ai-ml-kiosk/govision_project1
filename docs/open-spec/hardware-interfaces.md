# Hardware Interfaces

This document defines expected Jetson Nano hardware connections and
software-visible paths. All commands here are read-only unless explicitly
marked otherwise.

Use Jetson Nano J41 physical pin numbers in wiring notes. Jetson GPIO is 3.3V
logic only. Do not feed 5V logic into GPIO, SPI, I2C, PWM, reset, DC/RS, or
touch interrupt pins.

## Resource Summary

Current and planned bus allocation:

| Resource | Assignment | Notes |
|---|---|---|
| CSI connector | IMX219 visible camera | Does not consume J41 GPIO pins. |
| SPI0 `/dev/spidev0.0` | FLIR Lepton VoSPI | Active path observed on this Jetson. |
| SPI0 `/dev/spidev0.1` | Spare on SPI0 | Avoid for LCD while FLIR uses SPI0. |
| I2C0 `/dev/i2c-0` | FLIR Lepton CCI/control | Expected address `0x2A`. |
| I2C1 `/dev/i2c-1` | Mini OLED | Expected address `0x3C`. |
| SPI1 `/dev/spidev1.0` | Planned 2.4 inch LCD chip select | Proposed LCD data channel. |
| SPI1 `/dev/spidev1.1` | Planned touch chip select | Proposed touch controller channel. |
| `/sys/devices/pwm-fan` | Jetson fan controller | Sysfs fan path, not J41 SPI. |

SPI1 is the preferred location for the 2.4 inch SPI LCD/touch module so the
display does not share the FLIR thermal VoSPI bus.

## J41 Pin Allocation

| J41 pin | Current or planned use | Signal |
|---:|---|---|
| 1 or 17 | 3.3V logic power | 3.3V |
| 2 or 4 | Optional 5V module power | 5V, only if breakout supports it |
| 3 | OLED SDA | I2C1 SDA |
| 5 | OLED SCL | I2C1 SCL |
| 6, 9, 14, 20, 25, 30, 34, 39 | Ground | GND |
| 13 | Planned LCD/touch SPI clock | SPI1 SCK |
| 15 | Planned LCD DC/RS | GPIO12 |
| 16 | Planned touch chip select | SPI1 CS1, `/dev/spidev1.1` |
| 18 | Planned LCD chip select | SPI1 CS0, `/dev/spidev1.0` |
| 19 | FLIR SPI data out from Jetson | SPI0 MOSI |
| 21 | FLIR SPI data into Jetson | SPI0 MISO |
| 22 | Planned LCD/touch SPI data into Jetson | SPI1 MISO |
| 23 | FLIR SPI clock | SPI0 SCK |
| 24 | FLIR SPI chip select | SPI0 CS0, `/dev/spidev0.0` |
| 26 | Spare SPI0 chip select | SPI0 CS1, `/dev/spidev0.1` |
| 27 | FLIR CCI/control SDA | I2C0 SDA |
| 28 | FLIR CCI/control SCL | I2C0 SCL |
| 31 | Planned LCD reset | GPIO11 |
| 32 | Planned LCD backlight enable/PWM | GPIO07, PWM-capable on some images |
| 36 | Planned touch interrupt | GPIO input |
| 37 | Planned LCD/touch SPI data out from Jetson | SPI1 MOSI |

Do not confuse a display-board label such as `LCD DC / RS 9` with Jetson
physical pin 9. Jetson physical pin 9 is ground. The proposed Jetson pin for
LCD `DC`/`RS` is physical pin 15.

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

## 2.4 Inch SPI Touch LCD 480x320

Status: planned hardware addition. The LCD controller is not confirmed yet;
common 480x320 SPI modules use ILI9488, ST7796, or similar controllers. The
touch pins suggest an XPT2046-compatible resistive touch controller.

Recommended bus allocation:

- LCD framebuffer/data: SPI1 CS0, `/dev/spidev1.0`
- Touch controller: SPI1 CS1, `/dev/spidev1.1`
- Shared SPI lines: SCK, MOSI, MISO on SPI1
- Separate GPIO: LCD DC/RS, reset, backlight, touch IRQ

Jetson Nano J41 wiring:

| LCD/touch signal | J41 physical pin | Jetson signal |
|---|---:|---|
| VCC | 1 or 17 for 3.3V, or 2/4 for 5V only if supported | Module power |
| GND | Any J41 GND | Ground |
| LCD SCK / Touch T_CLK | 13 | SPI1 SCK |
| LCD SDO / Touch T_DO | 22 | SPI1 MISO |
| LCD SDI / Touch T_DIN | 37 | SPI1 MOSI |
| LCD CS | 18 | SPI1 CS0, `/dev/spidev1.0` |
| LCD DC / RS | 15 | GPIO12 |
| LCD RESET | 31 | GPIO11 |
| LCD LED / backlight | 32 | GPIO07 / optional PWM-capable pin |
| Touch T_CS | 16 | SPI1 CS1, `/dev/spidev1.1` |
| Touch T_IRQ | 36 | GPIO input |

Backlight caution:

- Drive `LCD LED` from pin 32 only if the LCD board expects a logic-level
  backlight enable/PWM input.
- If the backlight input powers LEDs directly, use a transistor/MOSFET or the
  display board's documented backlight supply circuit instead of a Jetson GPIO.

Performance expectation:

- A 480x320 RGB565 frame is about 2.46 Mbit before protocol overhead.
- FLIR thermal preview is a good match because the Lepton is about 8.6 fps.
- Fusion preview should be practical around 5 to 8 fps.
- CSI camera preview is usable as a small local preview, but not as a smooth
  30 fps primary monitor. HDMI/DSI remains better for full-motion camera view.

Validation before code:

```bash
ls -l /sys/class/spidev
```

Expected entries include:

```text
spidev1.0
spidev1.1
```

If SPI1 entries are missing, enable the second SPI group with Jetson-IO and
reboot before adding LCD software support.

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
