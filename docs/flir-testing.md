# FLIR Lepton Test Guide

This guide covers the GoVision FLIR Lepton 2.5 test utilities and the core
thermal helpers they use.

## Files

- `core/thermal.py`: reusable Lepton capture, SPI probing, color conversion,
  and temperature conversion helpers.
- `test/test_flir.py`: one-shot diagnostic capture that writes
  `results/test_flir.jpg`.
- `test/test_video_flir.py`: live OpenCV viewer or MJPEG browser stream.
- `test/test_fusion.py`: visible plus thermal fusion sample.

Generated images are written to `results/`, which should not be committed.

## Hardware Defaults

The Lepton uses:

- I2C/CCI control at address `0x2A`.
- SPI/VoSPI video packets.
- SPI mode `3`.
- Packet size `164`.
- Raw frame size `80x60`.

GoVision now probes common SPI nodes and selects the first active
Lepton-looking stream:

```text
0.0, 0.1, 1.0, 1.1
```

On the current Jetson, `spidev0.0` is the active video path and the other
devices return flat zero data.

## Read-Only Checks

Check FLIR I2C control:

```bash
i2cdetect -y -r 0
```

Expected address:

```text
0x2A
```

Check SPI module and registered devices:

```bash
lsmod | grep spidev
ls -l /sys/class/spidev
```

## One-Shot Capture

Scan SPI devices only:

```bash
python3 test/test_flir.py --scan-only
```

Example active device output:

```text
spidev0.0 0fffffffdcd0dcaddcd2dcaddcd4dcad unique: [...] score=5 active-candidate
spidev0.1 00000000000000000000000000000000 unique: [0] score=0 flat
spidev1.0 00000000000000000000000000000000 unique: [0] score=0 flat
spidev1.1 00000000000000000000000000000000 unique: [0] score=0 flat
```

Capture one frame with auto-detect:

```bash
python3 test/test_flir.py
```

Output:

```text
results/test_flir.jpg
```

Force a known SPI device:

```bash
python3 test/test_flir.py --no-scan --bus 0 --device 0
```

or:

```bash
FLIR_SPI_BUS=0 FLIR_SPI_DEVICE=0 python3 test/test_flir.py
```

## Live Viewer

Open a local OpenCV window on the Jetson display:

```bash
python3 test/test_video_flir.py
```

Quit with `q` or `Esc`.

Serve an MJPEG stream over the LAN:

```bash
python3 test/test_video_flir.py --http
```

Open:

```text
http://<jetson-ip>:5001/
```

Use a different port:

```bash
python3 test/test_video_flir.py --http --port 5002
```

## Orientation

The test utilities use OpenCV `flipCode` values:

```text
0  = vertical flip
1  = horizontal flip
-1 = both axes
none = no flip
```

Examples:

```bash
python3 test/test_flir.py --flip-code none
python3 test/test_video_flir.py --flip-code 0
```

Environment variable:

```bash
FLIR_FLIP_CODE=none python3 test/test_video_flir.py
```

## Sensitivity And Color Range

For live viewing, automatic color scaling uses percentiles and a sensitivity
factor. Higher sensitivity narrows the color range and makes smaller
temperature changes more visible.

```bash
python3 test/test_video_flir.py --http --sensitivity 2.0
```

Tune automatic percentiles:

```bash
python3 test/test_video_flir.py --http --auto-low-percentile 5 --auto-high-percentile 95
```

Use a fixed temperature range for stable colors:

```bash
python3 test/test_video_flir.py --http --min-c 20 --max-c 45
```

The live viewer labels the hottest and coldest detected points directly on the
image:

```text
HIGH xx.xC
LOW xx.xC
```

## Latency Tuning

The live viewer uses lower-latency defaults than the one-shot capture test:

```text
max-frame-attempts = 2
max-sync-packets   = 6000
resync-delay-s     = 0.0
error-sleep-s      = 0.1
```

If the live feed is responsive but occasionally drops frames, increase the sync
budget slightly:

```bash
python3 test/test_video_flir.py --http --max-sync-packets 10000
```

If sync is unreliable, use the more patient still-capture settings:

```bash
python3 test/test_video_flir.py --http \
  --max-frame-attempts 8 \
  --max-sync-packets 20000 \
  --resync-delay-s 0.2
```

Browser streams also send no-cache/no-buffer headers to reduce stale-frame
latency.

## Fusion Sample

Generate a visible plus thermal fusion sample:

```bash
python3 test/test_fusion.py
```

Generate a 1080p visible capture before overlay:

```bash
CAMERA_CAPTURE_WIDTH=1920 \
CAMERA_CAPTURE_HEIGHT=1080 \
CAMERA_DISPLAY_WIDTH=1920 \
CAMERA_DISPLAY_HEIGHT=1080 \
CAMERA_FRAMERATE=30 \
python3 test/test_fusion.py
```

The Lepton remains `80x60`, so higher visible resolution improves the visible
context and saved JPEG size but does not add true thermal detail.

## Core API Examples

Find the active SPI path:

```python
from core.thermal import find_active_spidev

probe = find_active_spidev()
if probe is None:
    raise RuntimeError("No active FLIR SPI stream found")

print(probe.bus, probe.device, probe.prefix_hex, probe.unique_values)
```

Create a config using the detected active SPI path:

```python
from core.thermal import FLIRLepton25, LeptonConfig, config_with_detected_spidev

config = config_with_detected_spidev(
    LeptonConfig(
        spi_speed_hz=18_000_000,
        max_frame_attempts=8,
        max_sync_packets=20_000,
    )
)

with FLIRLepton25(config) as flir:
    raw = flir.get_raw_frame()
```

Convert raw TLinear values to Celsius:

```python
from core.thermal import tlinear_to_celsius

temps_c = tlinear_to_celsius(raw, scale=100.0)
```

## Troubleshooting

### `No active FLIR-like SPI device found`

Run:

```bash
python3 test/test_flir.py --scan-only
```

If all devices are flat zeros or errors, check SPI enablement, wiring, and module
loading.

### `Unable to capture a complete FLIR Lepton 2.5 frame`

The SPI path opened, but VoSPI did not sync to a full frame. Try:

```bash
python3 test/test_flir.py --max-frame-attempts 12 --max-sync-packets 50000
```

For live viewing:

```bash
python3 test/test_video_flir.py --http \
  --max-frame-attempts 8 \
  --max-sync-packets 20000 \
  --resync-delay-s 0.2
```

### Browser stream feels delayed

Use the live script's HTTP mode and avoid proxy buffering:

```bash
python3 test/test_video_flir.py --http --port 5001
```

If latency remains high, lower JPEG quality or output scale:

```bash
python3 test/test_video_flir.py --http --jpeg-quality 70 --scale 6
```

### Colors flicker too much

Use a fixed range:

```bash
python3 test/test_video_flir.py --http --min-c 20 --max-c 45
```

or reduce sensitivity:

```bash
python3 test/test_video_flir.py --http --sensitivity 1.0
```
