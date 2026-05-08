from pathlib import Path
import sys; sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
from core.camera import IMX219Camera
Path("results").mkdir(exist_ok=True); cam = IMX219Camera(); frame = cam.get_frame(); cv2.imwrite("results/test.jpg", frame); cam.release()
