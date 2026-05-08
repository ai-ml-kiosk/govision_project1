from pathlib import Path
import os
import sys

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.thermal import (
    FLIRLepton25,
    LeptonConfig,
    apply_jet_colormap,
    tlinear_to_celsius,
)

results_dir = Path(__file__).resolve().parents[1] / "results"
results_dir.mkdir(exist_ok=True)
config = LeptonConfig(
    spi_bus=int(os.getenv("FLIR_SPI_BUS", LeptonConfig.spi_bus)),
    spi_device=int(os.getenv("FLIR_SPI_DEVICE", LeptonConfig.spi_device)),
    spi_speed_hz=int(os.getenv("FLIR_SPI_SPEED_HZ", LeptonConfig.spi_speed_hz)),
)
flir = FLIRLepton25(config)
scale = int(os.getenv("FLIR_OUTPUT_SCALE", "8"))
tlinear_scale = float(os.getenv("FLIR_TLINEAR_SCALE", "100"))
flip_code = int(os.getenv("FLIR_FLIP_CODE", "0"))

try:
    raw = flir.get_raw_frame()
    raw = cv2.flip(raw, flip_code)
    temps_c = tlinear_to_celsius(raw, scale=tlinear_scale)
    min_temp, max_temp, min_loc, max_loc = cv2.minMaxLoc(temps_c)
    frame = apply_jet_colormap(raw)
    if scale > 1:
        frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)

    min_pt = (min_loc[0] * scale, min_loc[1] * scale)
    max_pt = (max_loc[0] * scale, max_loc[1] * scale)
    cv2.circle(frame, min_pt, 8, (255, 255, 255), 2)
    cv2.circle(frame, max_pt, 8, (0, 0, 0), 2)
    cv2.rectangle(frame, (8, 8), (250, 74), (0, 0, 0), -1)
    cv2.putText(
        frame,
        f"Min: {min_temp:.2f} C",
        (16, 34),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
    )
    cv2.putText(
        frame,
        f"Max: {max_temp:.2f} C",
        (16, 64),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
    )

    if not cv2.imwrite(str(results_dir / "test_flir.jpg"), frame):
        raise RuntimeError("Unable to write results/test_flir.jpg")
finally:
    flir.release()
