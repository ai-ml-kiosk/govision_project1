# Device Profile Spec

Each physical GoVision device should have a deployment profile. The profile is
the single source of truth for hardware identity, bus numbers, service choices,
and local overrides.

## Required Sections

### `[device]`

- `id`: Stable non-secret device identifier.
- `site`: Human-readable deployment location or lab name.
- `role`: Device role, such as `kiosk`, `bench`, or `demo`.
- `timezone`: IANA timezone name. Use `system` to follow OS local time.

### `[network]`

- `hostname`: Expected OS hostname.
- `interface`: Preferred network interface, such as `wlan0` or `eth0`.
- `display_ip_on_oled`: Boolean.

### `[visible_camera]`

- `enabled`: Boolean.
- `type`: `imx219`.
- `sensor_ids`: List of CSI sensor IDs. Use `[0]` for single camera or
  `[0, 1]` for dual capture.
- `capture_width`, `capture_height`, `display_width`, `display_height`.
- `framerate`.
- `flip_method`.
- `sensor_mode`: Optional Jetson Argus sensor mode.

### `[thermal_camera]`

- `enabled`: Boolean.
- `type`: `flir_lepton_2_5`.
- `i2c_bus`: CCI/I2C bus where address `0x2A` responds.
- `spi_bus`, `spi_device`: VoSPI device path components.
- `spi_speed_hz`: Tested SPI speed.
- `width`, `height`, `packet_size`.
- `tlinear_scale`: Usually `100` when output is Kelvin times 100.
- `flip_code`: OpenCV flip code for deployment orientation.

### `[oled]`

- `enabled`: Boolean.
- `type`: `ssd1306_128x64_i2c`.
- `i2c_port`.
- `i2c_address`.
- `rotate`.
- `refresh_s`.
- `show_power`: Boolean.
- `show_ip`: Boolean.

### `[fan]`

- `enabled`: Boolean.
- `controller`: `pwm-fan`.
- `fan_dir`: Usually `/sys/devices/pwm-fan`.
- `interval_s`.
- `curve`: Temperature-to-PWM points as `["30:70", "45:80", ...]`.
- `restore_kernel_auto_on_stop`: Boolean.

### `[services]`

- `flask_enabled`: Boolean.
- `oled_enabled`: Boolean.
- `fan_control_enabled`: Boolean.
- `install_user`: User that owns the project checkout.

## Profile Storage

Profiles can live outside the repo, for example:

```text
/etc/govision/device.toml
```

If profiles are stored in the repository for development, keep only non-secret
example profiles. Production profiles should not include credentials or private
network material.
