"""Temperature-based PWM fan controller for NVIDIA Jetson."""

from __future__ import annotations

import argparse
import os
import signal
import time
from dataclasses import dataclass
from glob import glob
from typing import Dict, Iterable, List, Optional, Tuple


PWM_FAN_DIR = "/sys/devices/pwm-fan"
QUIET_FAN_CURVE: Tuple[Tuple[float, int], ...] = (
    (35.0, 0),
    (45.0, 0),
    (55.0, 80),
    (65.0, 120),
    (75.0, 180),
    (82.0, 255),
)
COOL_FAN_CURVE: Tuple[Tuple[float, int], ...] = (
    (30.0, 70),
    (45.0, 80),
    (55.0, 120),
    (65.0, 160),
    (75.0, 220),
    (82.0, 255),
)
FAN_CURVE_PRESETS = {
    "quiet": QUIET_FAN_CURVE,
    "cool": COOL_FAN_CURVE,
}


@dataclass(frozen=True)
class FanConfig:
    """Configuration for Jetson pwm-fan control."""

    fan_dir: str = PWM_FAN_DIR
    interval_s: float = 5.0
    min_pwm: int = 0
    max_pwm: int = 255
    temp_control_auto: bool = False
    curve: Tuple[Tuple[float, int], ...] = QUIET_FAN_CURVE


@dataclass(frozen=True)
class FanStatus:
    """Current temperature and fan state."""

    cpu_temp_c: Optional[float]
    gpu_temp_c: Optional[float]
    control_temp_c: Optional[float]
    target_pwm: int
    current_pwm: Optional[int]
    rpm: Optional[int]


class FanControlError(RuntimeError):
    """Raised when pwm-fan control is unavailable or unsafe."""


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return None


def _read_float(path: str) -> Optional[float]:
    value = _read_text(path)
    if value is None:
        return None

    try:
        return float(value.split()[0])
    except (IndexError, ValueError):
        return None


def _read_int(path: str) -> Optional[int]:
    value = _read_float(path)
    if value is None:
        return None
    return int(value)


def _write_int(path: str, value: int) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f"{value}\n")


def thermal_zone_temps() -> Dict[str, float]:
    """Read thermal zone temperatures in Celsius."""

    temps: Dict[str, float] = {}
    for zone in glob("/sys/class/thermal/thermal_zone*"):
        name = _read_text(os.path.join(zone, "type"))
        raw_temp = _read_float(os.path.join(zone, "temp"))
        if not name or raw_temp is None:
            continue

        temps[name.lower()] = raw_temp / 1000.0 if raw_temp > 1000 else raw_temp
    return temps


def _pick_temp(temps: Dict[str, float], keywords: Iterable[str]) -> Optional[float]:
    for keyword in keywords:
        for name, value in temps.items():
            if keyword in name:
                return value
    return None


def cpu_gpu_temps() -> Tuple[Optional[float], Optional[float]]:
    temps = thermal_zone_temps()
    cpu = _pick_temp(temps, ("cpu", "aotag"))
    gpu = _pick_temp(temps, ("gpu",))
    return cpu, gpu


def pwm_for_temp(temp_c: Optional[float], curve: Tuple[Tuple[float, int], ...]) -> int:
    """Map temperature to PWM using linear interpolation between curve points."""

    if temp_c is None:
        return max(pwm for _, pwm in curve)

    ordered = tuple(sorted(curve))
    if temp_c <= ordered[0][0]:
        return ordered[0][1]

    for (low_temp, low_pwm), (high_temp, high_pwm) in zip(ordered, ordered[1:]):
        if temp_c <= high_temp:
            span = high_temp - low_temp
            if span <= 0:
                return high_pwm
            ratio = (temp_c - low_temp) / span
            return round(low_pwm + ratio * (high_pwm - low_pwm))

    return ordered[-1][1]


class FanController:
    """Control Jetson pwm-fan from CPU/GPU temperature."""

    def __init__(self, config: Optional[FanConfig] = None) -> None:
        self.config = config or FanConfig()
        self._running = False

    def status(self) -> FanStatus:
        cpu_temp, gpu_temp = cpu_gpu_temps()
        usable_temps = [temp for temp in (cpu_temp, gpu_temp) if temp is not None]
        control_temp = max(usable_temps) if usable_temps else None
        target = self._target_pwm(control_temp)

        return FanStatus(
            cpu_temp_c=cpu_temp,
            gpu_temp_c=gpu_temp,
            control_temp_c=control_temp,
            target_pwm=target,
            current_pwm=_read_int(os.path.join(self.config.fan_dir, "cur_pwm")),
            rpm=_read_int(os.path.join(self.config.fan_dir, "rpm_measured")),
        )

    def apply_once(self) -> FanStatus:
        """Apply one PWM update and return the resulting status snapshot."""

        self._ensure_available()
        status = self.status()
        self._set_manual_control()
        _write_int(os.path.join(self.config.fan_dir, "target_pwm"), status.target_pwm)
        return status

    def run_forever(self) -> None:
        """Update the fan until interrupted."""

        self._ensure_available()
        self._running = True
        signal.signal(signal.SIGTERM, self._stop)
        signal.signal(signal.SIGINT, self._stop)

        while self._running:
            status = self.apply_once()
            print(
                "fan "
                f"cpu={_fmt_temp(status.cpu_temp_c)} "
                f"gpu={_fmt_temp(status.gpu_temp_c)} "
                f"pwm={status.target_pwm} "
                f"cur={_fmt_int(status.current_pwm)} "
                f"rpm={_fmt_int(status.rpm)}",
                flush=True,
            )
            time.sleep(self.config.interval_s)

        self.restore_auto_control()

    def restore_auto_control(self) -> None:
        if self.config.temp_control_auto:
            return

        temp_control = os.path.join(self.config.fan_dir, "temp_control")
        if os.path.exists(temp_control):
            _write_int(temp_control, 1)

    def _target_pwm(self, temp_c: Optional[float]) -> int:
        target = pwm_for_temp(temp_c, self.config.curve)
        return max(self.config.min_pwm, min(self.config.max_pwm, target))

    def _ensure_available(self) -> None:
        if not os.path.isdir(self.config.fan_dir):
            raise FanControlError(f"Jetson pwm-fan path not found: {self.config.fan_dir}")

        target_pwm = os.path.join(self.config.fan_dir, "target_pwm")
        if not os.path.exists(target_pwm):
            raise FanControlError(f"Jetson fan target PWM path not found: {target_pwm}")

    def _set_manual_control(self) -> None:
        if self.config.temp_control_auto:
            return

        temp_control = os.path.join(self.config.fan_dir, "temp_control")
        if os.path.exists(temp_control):
            _write_int(temp_control, 0)

    def _stop(self, signum, frame) -> None:
        self._running = False


def _fmt_temp(value: Optional[float]) -> str:
    return "--" if value is None else f"{value:.1f}C"


def _fmt_int(value: Optional[int]) -> str:
    return "--" if value is None else str(value)


def _parse_curve(value: str) -> Tuple[Tuple[float, int], ...]:
    points: List[Tuple[float, int]] = []
    for item in value.split(","):
        temp, pwm = item.split(":", 1)
        points.append((float(temp), int(pwm)))
    return tuple(points)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Temperature-based Jetson fan control")
    parser.add_argument("--once", action="store_true", help="Apply one update and exit")
    parser.add_argument("--status", action="store_true", help="Print status without writing PWM")
    parser.add_argument("--restore-auto", action="store_true", help="Restore kernel fan auto control")
    parser.add_argument("--interval", type=float, default=FanConfig.interval_s)
    parser.add_argument(
        "--preset",
        choices=sorted(FAN_CURVE_PRESETS),
        default="quiet",
        help="Named fan curve preset",
    )
    parser.add_argument(
        "--curve",
        type=_parse_curve,
        default=None,
        help="Override fan curve as comma-separated TEMP:PWM points",
    )
    parser.add_argument("--min-pwm", type=int, default=FanConfig.min_pwm)
    parser.add_argument("--max-pwm", type=int, default=FanConfig.max_pwm)
    parser.add_argument(
        "--keep-kernel-auto",
        action="store_true",
        help="Do not disable kernel temp_control before writing PWM",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    curve = args.curve if args.curve is not None else FAN_CURVE_PRESETS[args.preset]
    controller = FanController(
        FanConfig(
            interval_s=args.interval,
            min_pwm=args.min_pwm,
            max_pwm=args.max_pwm,
            temp_control_auto=args.keep_kernel_auto,
            curve=curve,
        )
    )

    if args.restore_auto:
        controller.restore_auto_control()
        print("restored kernel fan auto control")
        return 0

    if args.status:
        status = controller.status()
        print(
            f"cpu={_fmt_temp(status.cpu_temp_c)} "
            f"gpu={_fmt_temp(status.gpu_temp_c)} "
            f"target_pwm={status.target_pwm} "
            f"cur_pwm={_fmt_int(status.current_pwm)} "
            f"rpm={_fmt_int(status.rpm)}"
        )
        return 0

    if args.once:
        status = controller.apply_once()
        print(
            f"applied target_pwm={status.target_pwm} "
            f"cpu={_fmt_temp(status.cpu_temp_c)} "
            f"gpu={_fmt_temp(status.gpu_temp_c)}"
        )
        return 0

    controller.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
