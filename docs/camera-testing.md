# IMX219 Camera Test Guide

This guide covers GoVision visible-camera test utilities for the IMX219 CSI
camera.

## Files

- `core/camera.py`: reusable IMX219 GStreamer/OpenCV camera helpers.
- `test/test_cam.py`: one-shot visible capture that writes `results/test.jpg`.
- `test/test_video_cam.py`: live OpenCV viewer or MJPEG browser stream.
- `test/test_fusion.py`: visible plus thermal fusion sample.

Generated images are written to `results/`, which should not be committed.

## Hardware Defaults

The current visible camera path uses:

- Camera: IMX219 CSI.
- Source: `nvarguscamerasrc`.
- Default sensor: `sensor-id=0`.
- Default capture/display: `1280x720`.
- Default framerate: `30`.
- Default GStreamer flip method: `2`.

The camera pipeline uses:

```text
appsink drop=true max-buffers=1 sync=false
```

This keeps live viewing low-latency by dropping old frames instead of queuing
them.

## Read-Only Checks

List video nodes:

```bash
ls -l /dev/video*
```

Check OpenCV GStreamer support:

```bash
python3 -c "import cv2; print(cv2.__version__); print([line.strip() for line in cv2.getBuildInformation().splitlines() if 'GStreamer' in line])"
```

Expected OpenCV build information should include:

```text
GStreamer: YES
```

## One-Shot Capture

Capture a single visible frame:

```bash
python3 test/test_cam.py
```

Output:

```text
results/test.jpg
```

## Live Viewer

Open a local OpenCV window on the Jetson display:

```bash
python3 test/test_video_cam.py
```

Quit with `q` or `Esc`.

Serve an MJPEG stream over the LAN:

```bash
python3 test/test_video_cam.py --http
```

Open:

```text
http://<jetson-ip>:5002/
```

Use a different port:

```bash
python3 test/test_video_cam.py --http --port 5010
```

## Orientation

The visible camera uses Jetson `nvvidconv flip-method` values. Common values:

```text
0 = none
1 = rotate counterclockwise 90 degrees
2 = rotate 180 degrees
3 = rotate clockwise 90 degrees
4 = horizontal flip
5 = upper-right diagonal flip
6 = vertical flip
7 = upper-left diagonal flip
```

Examples:

```bash
python3 test/test_video_cam.py --flip-method 0
python3 test/test_video_cam.py --http --flip-method 2
```

Environment variable:

```bash
CAMERA_FLIP_METHOD=0 python3 test/test_video_cam.py
```

## Resolution And Sensor Modes

Default 720p:

```bash
python3 test/test_video_cam.py \
  --capture-width 1280 \
  --capture-height 720 \
  --display-width 1280 \
  --display-height 720 \
  --framerate 30
```

1080p:

```bash
python3 test/test_video_cam.py \
  --capture-width 1920 \
  --capture-height 1080 \
  --display-width 1920 \
  --display-height 1080 \
  --framerate 30
```

If Argus chooses an unexpected mode, force a sensor mode:

```bash
python3 test/test_video_cam.py \
  --sensor-mode 2 \
  --capture-width 1920 \
  --capture-height 1080 \
  --display-width 1920 \
  --display-height 1080 \
  --framerate 30
```

Resize the displayed or streamed output while keeping the capture mode:

```bash
python3 test/test_video_cam.py --http --resize-width 960
```

## Latency Tuning

The camera pipeline already drops old frames. For browser viewing, the test
server also sends no-cache/no-buffer headers.

If browser latency is high, reduce JPEG quality or output size:

```bash
python3 test/test_video_cam.py --http --jpeg-quality 70 --resize-width 960
```

If local window display is too heavy, reduce display size:

```bash
python3 test/test_video_cam.py --display-width 960 --display-height 540
```

If the stream stalls after a camera error, the script releases the camera and
retries after `--error-sleep-s`:

```bash
python3 test/test_video_cam.py --http --error-sleep-s 1.0
```

## HTTP Route

The standalone camera stream serves:

```text
/
/video_feed
```

The MJPEG content type is:

```text
multipart/x-mixed-replace; boundary=frame
```

## Core API Example

Create a configured camera and read one frame:

```python
from core.camera import CameraConfig, IMX219Camera

config = CameraConfig(
    capture_width=1280,
    capture_height=720,
    display_width=1280,
    display_height=720,
    framerate=30,
    flip_method=2,
)

camera = IMX219Camera(sensor_id=0, config=config)
try:
    frame = camera.get_frame()
finally:
    camera.release()
```

## Troubleshooting

### `Unable to open IMX219 camera sensor-id=0`

Check that the CSI cable is connected and no other process owns Argus:

```bash
ls -l /dev/video*
```

Then stop any other app using the camera before retrying.

### OpenCV GStreamer warning about video position

This warning is common for live GStreamer camera streams:

```text
Cannot query video position
```

It is usually harmless when frames are still displayed.

### Stream is rotated or upside down

Try a different flip method:

```bash
python3 test/test_video_cam.py --flip-method 0
python3 test/test_video_cam.py --flip-method 2
python3 test/test_video_cam.py --flip-method 6
```

### 1080p does not open

Try explicitly selecting the 1080p sensor mode:

```bash
python3 test/test_video_cam.py \
  --sensor-mode 2 \
  --capture-width 1920 \
  --capture-height 1080 \
  --display-width 1920 \
  --display-height 1080 \
  --framerate 30
```
