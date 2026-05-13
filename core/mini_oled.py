"""Mini OLED status display helpers for a Jetson 128x64 I2C SSD1306 panel."""

from __future__ import annotations

import os
import shutil
import socket
import time
from dataclasses import dataclass, field
from glob import glob
from typing import Any, Dict, Iterable, List, Optional, Tuple


GPIO_CONNECTION_INFO = """0.96 inch I2C OLED 128x64, usually SSD1306:
OLED VCC -> Jetson 3.3V, physical pin 1 or 17
OLED GND -> Jetson GND, physical pin 6, 9, 14, 20, 25, 30, 34, or 39
OLED SDA -> Jetson I2C1 SDA, physical pin 3
OLED SCL -> Jetson I2C1 SCL, physical pin 5
Default bus/address: /dev/i2c-1 at 0x3C. Check with: i2cdetect -y -r 1
Use 3.3V I2C logic. Only use 5V VCC if the OLED breakout explicitly supports it.
"""

PWM_FAN_DIR = "/sys/devices/pwm-fan"


@dataclass(frozen=True)
class OLEDConfig:
    """Configuration for a 128x64 I2C SSD1306 OLED."""

    i2c_port: int = 1
    i2c_address: int = 0x3C
    width: int = 128
    height: int = 64
    rotate: int = 0
    timezone: Optional[str] = None
    refresh_s: float = 1.0
    max_chars: int = 21


@dataclass(frozen=True)
class DeviceHealth:
    """Snapshot of Jetson health for the OLED status screen."""

    timestamp: str
    timezone: str
    hostname: str
    ip_address: str
    uptime: str
    load_1m: float
    memory_percent: float
    disk_percent: float
    cpu_temp_c: Optional[float]
    gpu_temp_c: Optional[float]
    voltage_v: Optional[float]
    current_a: Optional[float]
    power_watts: Optional[float]
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    cpu_count: int = 1
    load_percent: float = 0.0
    fan_rpm: Optional[int] = None


class OLEDDisplayError(RuntimeError):
    """Raised when the OLED display cannot be initialized or updated."""


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


def _format_now(timezone: Optional[str]) -> str:
    if not timezone:
        return time.strftime("%Y-%m-%d %H:%M %Z")

    previous_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = timezone
        if hasattr(time, "tzset"):
            time.tzset()
        return time.strftime("%Y-%m-%d %H:%M %Z")
    finally:
        if previous_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous_tz
        if hasattr(time, "tzset"):
            time.tzset()


def _timezone_label(timezone: Optional[str]) -> str:
    if timezone:
        return timezone
    return time.strftime("%Z") or "local"


def _format_uptime() -> str:
    raw_uptime = _read_text("/proc/uptime")
    if raw_uptime is None:
        return "n/a"

    try:
        seconds = int(float(raw_uptime.split()[0]))
    except (IndexError, ValueError):
        return "n/a"

    days, seconds = divmod(seconds, 86_400)
    hours, seconds = divmod(seconds, 3_600)
    minutes, _ = divmod(seconds, 60)
    if days:
        return f"{days}d {hours}h"
    return f"{hours}h {minutes}m"


def _get_ip_address() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "offline"

    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "offline"
    finally:
        sock.close()


def _memory_percent() -> float:
    info: Dict[str, float] = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                key, value = line.split(":", 1)
                info[key] = float(value.strip().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0

    total = info.get("MemTotal", 0.0)
    available = info.get("MemAvailable", 0.0)
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, (1.0 - available / total) * 100.0))


def _disk_percent(path: str = "/") -> float:
    usage = shutil.disk_usage(path)
    return (usage.used / usage.total) * 100.0


def _cpu_count() -> int:
    return max(1, os.cpu_count() or 1)


def _normalized_load_percent(load_1m: float, cpu_count: int) -> float:
    return max(0.0, (load_1m / max(1, cpu_count)) * 100.0)


def _fan_rpm(fan_dir: str = PWM_FAN_DIR) -> Optional[int]:
    return _read_int(os.path.join(fan_dir, "rpm_measured"))


def _thermal_zone_temps() -> Dict[str, float]:
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


def _power_monitor_dirs() -> List[str]:
    patterns = (
        "/sys/bus/i2c/devices/*/iio_device",
        "/sys/bus/i2c/devices/*/iio:device*",
    )

    dirs = set()
    for pattern in patterns:
        dirs.update(path for path in glob(pattern) if os.path.isdir(path))
    return sorted(dirs)


def _power_metrics() -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Return board input voltage, current, and power when INA data is readable."""

    fallback: Tuple[Optional[float], Optional[float], Optional[float]] = (None, None, None)

    for directory in _power_monitor_dirs():
        for index in range(8):
            rail_name = _read_text(os.path.join(directory, f"rail_name_{index}")) or ""
            voltage = _read_float(os.path.join(directory, f"in_voltage{index}_input"))
            current = _read_float(os.path.join(directory, f"in_current{index}_input"))
            power = _read_float(os.path.join(directory, f"in_power{index}_input"))

            if voltage is None and current is None and power is None:
                continue

            metrics = (
                None if voltage is None else voltage / 1000.0,
                None if current is None else current / 1000.0,
                None if power is None else power / 1000.0,
            )
            if "5v_in" in rail_name.lower() or "vdd_in" in rail_name.lower():
                return metrics
            if fallback == (None, None, None):
                fallback = metrics

    return fallback


def collect_device_health(timezone: Optional[str] = None) -> DeviceHealth:
    """Collect a lightweight Jetson status snapshot."""

    temps = _thermal_zone_temps()
    cpu_temp = _pick_temp(temps, ("cpu", "thermal", "aotag"))
    gpu_temp = _pick_temp(temps, ("gpu",))
    load_1m = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
    cpu_count = _cpu_count()
    load_percent = _normalized_load_percent(load_1m, cpu_count)
    mem_pct = _memory_percent()
    disk_pct = _disk_percent("/")
    voltage, current, power = _power_metrics()
    fan_rpm = _fan_rpm()

    warnings: List[str] = []
    if cpu_temp is not None and cpu_temp >= 75.0:
        warnings.append("CPU hot")
    if gpu_temp is not None and gpu_temp >= 75.0:
        warnings.append("GPU hot")
    if mem_pct >= 90.0:
        warnings.append("RAM high")
    if disk_pct >= 90.0:
        warnings.append("Disk high")
    if voltage is not None and voltage < 4.75:
        warnings.append("Volt low")
    if power is not None and power >= 10.0:
        warnings.append("Power high")

    return DeviceHealth(
        timestamp=_format_now(timezone),
        timezone=_timezone_label(timezone),
        hostname=socket.gethostname(),
        ip_address=_get_ip_address(),
        uptime=_format_uptime(),
        load_1m=load_1m,
        memory_percent=mem_pct,
        disk_percent=disk_pct,
        cpu_temp_c=cpu_temp,
        gpu_temp_c=gpu_temp,
        voltage_v=voltage,
        current_a=current,
        power_watts=power,
        warnings=tuple(warnings),
        cpu_count=cpu_count,
        load_percent=load_percent,
        fan_rpm=fan_rpm,
    )


class MiniOLED:
    """Status renderer for a 0.96 inch 128x64 I2C OLED display."""

    def __init__(self, config: Optional[OLEDConfig] = None) -> None:
        self.config = config or OLEDConfig()
        self._device: Optional[Any] = None
        self._canvas: Optional[Any] = None

    def open(self) -> None:
        """Open the OLED device lazily."""

        if self._device is not None:
            return

        try:
            from luma.core.interface.serial import i2c
            from luma.core.render import canvas
            from luma.oled.device import ssd1306
        except ImportError as exc:
            raise OLEDDisplayError(
                "OLED support requires luma.oled. Install with: "
                "python3 -m pip install --user luma.oled"
            ) from exc

        cfg = self.config
        try:
            serial = i2c(port=cfg.i2c_port, address=cfg.i2c_address)
            self._device = ssd1306(
                serial,
                width=cfg.width,
                height=cfg.height,
                rotate=cfg.rotate,
            )
            self._canvas = canvas
        except Exception as exc:
            raise OLEDDisplayError(
                f"Unable to open OLED on /dev/i2c-{cfg.i2c_port} "
                f"at address 0x{cfg.i2c_address:02X}."
            ) from exc

    def show_status(self) -> DeviceHealth:
        """Collect current health and render it to the OLED."""

        health = collect_device_health(self.config.timezone)
        self.display_lines(self._status_lines(health))
        return health

    def display_lines(self, lines: Iterable[str]) -> None:
        """Render up to eight short text lines on the OLED."""

        self.open()
        assert self._device is not None
        assert self._canvas is not None

        with self._canvas(self._device) as draw:
            for index, line in enumerate(lines):
                if index >= self.config.height // 8:
                    break
                draw.text((0, index * 8), self._fit(line), fill=255)

    def clear(self) -> None:
        self.display_lines(())

    def run_forever(self) -> None:
        """Refresh the status display until interrupted."""

        while True:
            self.show_status()
            time.sleep(self.config.refresh_s)

    def close(self) -> None:
        self._device = None
        self._canvas = None

    def _fit(self, text: str) -> str:
        return text[: self.config.max_chars]

    def _table_row(self, left: str, right: str) -> str:
        separator = " "
        if self.config.max_chars <= len(separator):
            return self._fit(f"{left}{right}")

        left_width = (self.config.max_chars - len(separator)) // 2
        right_width = self.config.max_chars - len(separator) - left_width
        return (
            left[:left_width].ljust(left_width)
            + separator
            + right[:right_width].ljust(right_width)
        )

    def _status_lines(self, health: DeviceHealth) -> List[str]:
        cpu = "--" if health.cpu_temp_c is None else f"{health.cpu_temp_c:.0f}C"
        gpu = "--" if health.gpu_temp_c is None else f"{health.gpu_temp_c:.0f}C"
        load_percent = health.load_percent
        if load_percent == 0.0 and health.load_1m > 0.0:
            load_percent = _normalized_load_percent(health.load_1m, health.cpu_count)
        load = f"{load_percent:.0f}%"
        rpm = "--" if health.fan_rpm is None else str(health.fan_rpm)
        voltage = "--" if health.voltage_v is None else f"{health.voltage_v:.2f}V"
        current = "--" if health.current_a is None else f"{health.current_a:.2f}A"
        power = "--" if health.power_watts is None else f"{health.power_watts:.1f}W"
        status = "OK" if not health.warnings else ",".join(health.warnings)

        return [
            health.timestamp,
            f"IP: {health.ip_address}",
            self._table_row(f"CPU:{cpu}", f"GPU:{gpu}"),
            self._table_row(f"Load:{load}", f"RPM:{rpm}"),
            self._table_row(f"RAM:{health.memory_percent:.0f}%", f"Disk:{health.disk_percent:.0f}%"),
            self._table_row(f"VIN:{voltage}", f"I:{current}"),
            self._table_row(f"Pwr:{power}", f"Up:{health.uptime}"),
            f"Health:{status}",
        ]


if __name__ == "__main__":
    print(GPIO_CONNECTION_INFO)
    display = MiniOLED()
    try:
        display.run_forever()
    except KeyboardInterrupt:
        display.close()
    except OLEDDisplayError as exc:
        print(f"OLED error: {exc}")
