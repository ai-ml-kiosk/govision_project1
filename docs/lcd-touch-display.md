# SPI Touch LCD Guide

This guide captures the planned 2.4 inch SPI touch LCD addition for the
Jetson Nano GoVision build. It is documentation-first: confirm the exact LCD
controller before adding driver code.

## Hardware Status

Target display:

- Size: 2.4 inch
- Resolution: 480x320
- Interface: SPI LCD plus SPI resistive touch
- LCD controller: to be confirmed from the module datasheet or board marking
- Touch controller: likely XPT2046-compatible, based on `T_CLK`, `T_DO`,
  `T_DIN`, `T_CS`, and `T_IRQ` pin names

Current GoVision resources:

- FLIR Lepton already uses SPI0, active path `/dev/spidev0.0`.
- The OLED status display uses I2C1, address `0x3C`.
- The proposed LCD should use SPI1, with LCD on `/dev/spidev1.0` and touch on
  `/dev/spidev1.1`.

This keeps the LCD refresh traffic away from the FLIR VoSPI thermal stream.

## Jetson Nano Wiring

Use Jetson Nano J41 physical pin numbers.

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

Important notes:

- Jetson GPIO and SPI logic are 3.3V only.
- Jetson physical pin 9 is ground. If the LCD board label says `DC / RS 9`,
  treat `9` as the board's own pin number, not the Jetson pin number.
- Only connect `LCD LED` to pin 32 when the LCD board exposes a logic-level
  backlight input. If it drives LED current directly, use a transistor/MOSFET
  or the module's documented backlight circuit.

## Expected SPI Devices

Read-only check:

```bash
ls -l /sys/class/spidev
```

Expected entries:

```text
spidev0.0
spidev0.1
spidev1.0
spidev1.1
```

Allocation:

| Device | Assignment |
|---|---|
| `/dev/spidev0.0` | FLIR Lepton VoSPI |
| `/dev/spidev0.1` | Spare SPI0 chip select |
| `/dev/spidev1.0` | LCD chip select |
| `/dev/spidev1.1` | Touch chip select |

If `spidev1.0` or `spidev1.1` are missing, enable the second SPI group using
Jetson-IO and reboot before adding display code.

## Performance Expectation

A 480x320 RGB565 frame is:

```text
480 x 320 x 16 bits = 2,457,600 bits, about 2.46 Mbit
```

Approximate display suitability:

| Workload | Expected fit |
|---|---|
| FLIR thermal preview | Good, because FLIR is about 8.6 fps |
| Fusion preview | Practical around 5 to 8 fps |
| CSI camera preview | Usable as local preview, not smooth 30 fps |
| Primary high-FPS monitor | Prefer HDMI or DSI |

Design target for LCD code:

- Keep LCD refresh independent from FLIR capture.
- Drop stale camera frames rather than queueing them.
- Target 8 to 12 fps for CSI preview and 5 to 8 fps for fusion if CPU/SPI load
  stays acceptable.
- Prefer partial redraws for UI controls when practical.

## Driver Information To Confirm

Before implementation, identify these from the display module:

- LCD controller name, for example ILI9488, ST7796, ILI9341, or similar.
- Pixel format supported by the controller, usually RGB565 or RGB666.
- Maximum reliable SPI clock on the Jetson wiring.
- Backlight input type: logic enable, PWM input, or direct LED power.
- Touch controller protocol and calibration orientation.

Record confirmed values in the deployment profile before enabling the display
in a service.
