"""FLIR Lepton 2.5 thermal capture helpers for NVIDIA Jetson."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from glob import glob
from typing import Any, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np


RawThermalFrame = np.ndarray
ColorThermalFrame = np.ndarray
SpiCandidate = Tuple[int, int]
DEFAULT_SPI_CANDIDATES: Tuple[SpiCandidate, ...] = ((0, 0), (0, 1), (1, 0), (1, 1))


@dataclass(frozen=True)
class LeptonConfig:
    """Configuration for FLIR Lepton 2.5 VoSPI capture."""

    spi_bus: int = 0
    spi_device: int = 1
    spi_speed_hz: int = 18_000_000
    spi_mode: int = 0b11
    bits_per_word: int = 8
    width: int = 80
    height: int = 60
    packet_size: int = 164
    max_frame_attempts: int = 2
    max_sync_packets: int = 10_000
    resync_delay_s: float = 0.2


@dataclass(frozen=True)
class SpiProbeResult:
    """One low-speed SPI probe result for finding the active Lepton device."""

    bus: int
    device: int
    prefix_hex: str
    unique_values: Tuple[int, ...]
    error: Optional[str] = None

    @property
    def active_score(self) -> int:
        if self.error:
            return -1
        if not self.unique_values:
            return 0
        if len(self.unique_values) == 1 and self.unique_values[0] in (0, 255):
            return 0

        first_byte = int(self.prefix_hex[:2], 16) if len(self.prefix_hex) >= 2 else 0
        score = 1
        if any(value not in (0, 255) for value in self.unique_values):
            score += 2
        if len(self.unique_values) > 2:
            score += 1
        if (first_byte & 0x0F) == 0x0F:
            score += 1
        return score

    @property
    def is_active(self) -> bool:
        return self.active_score > 0


class ThermalError(RuntimeError):
    """Raised when the thermal camera cannot be opened or read."""


def _spidev_hint() -> str:
    nodes = sorted(glob("/dev/spidev*"))
    if nodes:
        return f" Available SPI devices: {', '.join(nodes)}."

    return " No /dev/spidev* devices are present; enable SPI on the Jetson header and reboot."


def parse_spi_candidates(value: str) -> Tuple[SpiCandidate, ...]:
    """Parse ``bus.device`` entries such as ``0.0,0.1,1.0,1.1``."""

    candidates: List[SpiCandidate] = []
    for item in value.split(","):
        bus, device = item.strip().split(".", 1)
        candidates.append((int(bus), int(device)))
    return tuple(candidates)


def probe_spidev(
    bus: int,
    device: int,
    speed_hz: int = 2_000_000,
    packet_size: int = LeptonConfig.packet_size,
    spi_mode: int = LeptonConfig.spi_mode,
) -> SpiProbeResult:
    """Read one packet-sized transfer and score whether it looks like Lepton traffic."""

    try:
        import spidev
    except ImportError as exc:
        return SpiProbeResult(bus, device, "", (), f"missing spidev: {exc}")

    spi = spidev.SpiDev()
    try:
        spi.open(bus, device)
        spi.mode = spi_mode
        spi.max_speed_hz = speed_hz
        data = bytes(spi.xfer2([0] * packet_size))
        return SpiProbeResult(
            bus=bus,
            device=device,
            prefix_hex=data[:16].hex(),
            unique_values=tuple(sorted(set(data))[:8]),
        )
    except Exception as exc:
        return SpiProbeResult(bus, device, "", (), str(exc))
    finally:
        try:
            spi.close()
        except Exception:
            pass


def scan_spidev(
    candidates: Sequence[SpiCandidate] = DEFAULT_SPI_CANDIDATES,
    speed_hz: int = 2_000_000,
    packet_size: int = LeptonConfig.packet_size,
    spi_mode: int = LeptonConfig.spi_mode,
) -> List[SpiProbeResult]:
    """Probe candidate SPI devices for non-flat Lepton-like traffic."""

    return [
        probe_spidev(
            bus,
            device,
            speed_hz=speed_hz,
            packet_size=packet_size,
            spi_mode=spi_mode,
        )
        for bus, device in candidates
    ]


def select_active_spidev(probes: Iterable[SpiProbeResult]) -> Optional[SpiProbeResult]:
    """Return the most likely active Lepton SPI device from probe results."""

    active = [probe for probe in probes if probe.is_active]
    if not active:
        return None
    return max(active, key=lambda probe: probe.active_score)


def find_active_spidev(
    candidates: Sequence[SpiCandidate] = DEFAULT_SPI_CANDIDATES,
    speed_hz: int = 2_000_000,
    packet_size: int = LeptonConfig.packet_size,
    spi_mode: int = LeptonConfig.spi_mode,
) -> Optional[SpiProbeResult]:
    """Probe candidate SPI devices and return the most likely active Lepton path."""

    return select_active_spidev(
        scan_spidev(
            candidates=candidates,
            speed_hz=speed_hz,
            packet_size=packet_size,
            spi_mode=spi_mode,
        )
    )


def config_with_detected_spidev(
    config: Optional[LeptonConfig] = None,
    candidates: Sequence[SpiCandidate] = DEFAULT_SPI_CANDIDATES,
    probe_speed_hz: int = 2_000_000,
) -> LeptonConfig:
    """Return a Lepton config updated with the detected active SPI bus/device."""

    base = config or LeptonConfig()
    probe = find_active_spidev(
        candidates=candidates,
        speed_hz=probe_speed_hz,
        packet_size=base.packet_size,
        spi_mode=base.spi_mode,
    )
    if probe is None:
        raise ThermalError("No active FLIR-like SPI device found.")

    return replace(base, spi_bus=probe.bus, spi_device=probe.device)


def normalize_14bit_to_8bit(
    raw_frame: RawThermalFrame,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
    mask_14bit: bool = False,
) -> np.ndarray:
    """Normalize a Lepton frame into an 8-bit grayscale image."""

    raw = np.asarray(raw_frame, dtype=np.uint16)
    if mask_14bit:
        raw = raw & 0x3FFF

    if raw.size == 0:
        raise ValueError("raw_frame cannot be empty")

    low = int(raw.min()) if min_value is None else int(min_value)
    high = int(raw.max()) if max_value is None else int(max_value)
    if high <= low:
        return np.zeros(raw.shape, dtype=np.uint8)

    clipped = np.clip(raw, low, high)
    normalized = ((clipped.astype(np.float32) - low) * 255.0) / (high - low)
    return normalized.astype(np.uint8)


def apply_jet_colormap(
    raw_frame: RawThermalFrame,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
    mask_14bit: bool = False,
) -> ColorThermalFrame:
    """Normalize 14-bit raw data and apply OpenCV's JET colormap."""

    normalized = normalize_14bit_to_8bit(
        raw_frame,
        min_value=min_value,
        max_value=max_value,
        mask_14bit=mask_14bit,
    )
    return cv2.applyColorMap(normalized, cv2.COLORMAP_JET)


def tlinear_to_celsius(raw_frame: RawThermalFrame, scale: float = 100.0) -> np.ndarray:
    """Convert Lepton TLinear values from Kelvin-scaled units to Celsius."""

    return np.asarray(raw_frame, dtype=np.float32) / scale - 273.15


class FLIRLepton25:
    """Capture raw and colorized frames from a FLIR Lepton 2.5 over SPI."""

    def __init__(self, config: Optional[LeptonConfig] = None) -> None:
        self.config = config or LeptonConfig()
        self._spi: Optional[Any] = None

    def open(self) -> None:
        """Open the SPI device if it is not already open."""

        if self.is_opened:
            return

        try:
            import spidev
        except ImportError as exc:
            raise ThermalError(
                "spidev is required for FLIR Lepton capture. Install python3-spidev "
                "or add the spidev package to the project environment."
            ) from exc

        cfg = self.config
        spi = spidev.SpiDev()
        try:
            spi.open(cfg.spi_bus, cfg.spi_device)
            spi.mode = cfg.spi_mode
            spi.max_speed_hz = cfg.spi_speed_hz
            spi.bits_per_word = cfg.bits_per_word
        except Exception as exc:
            try:
                spi.close()
            except Exception:
                pass
            device_path = f"/dev/spidev{cfg.spi_bus}.{cfg.spi_device}"
            raise ThermalError(
                f"Unable to open FLIR Lepton SPI device {device_path}.{_spidev_hint()}"
            ) from exc

        self._spi = spi

    @property
    def is_opened(self) -> bool:
        return self._spi is not None

    def get_raw_frame(self) -> RawThermalFrame:
        """Return one 80x60 raw 14-bit thermal frame as ``uint16``."""

        self.open()
        assert self._spi is not None

        cfg = self.config

        for _ in range(cfg.max_frame_attempts):
            self._resync()
            rows = []

            for _ in range(cfg.max_sync_packets):
                packet = self._read_packet()
                if self._is_discard_packet(packet):
                    continue

                packet_number = packet[1]
                if packet_number == 0:
                    rows = []

                if packet_number >= cfg.height:
                    continue

                if len(rows) == packet_number:
                    rows.append(self._packet_payload_to_row(packet))

                    if len(rows) == cfg.height:
                        return np.array(rows, dtype=np.uint16)

        device_path = f"/dev/spidev{cfg.spi_bus}.{cfg.spi_device}"
        raise ThermalError(
            f"Unable to capture a complete FLIR Lepton 2.5 frame from {device_path} "
            f"after scanning {cfg.max_sync_packets * cfg.max_frame_attempts} packets."
        )

    def get_frame(
        self,
        colorize: bool = True,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None,
    ) -> np.ndarray:
        """Return a thermal frame, colorized with JET by default."""

        raw_frame = self.get_raw_frame()
        if not colorize:
            return raw_frame

        return apply_jet_colormap(raw_frame, min_value=min_value, max_value=max_value)

    def release(self) -> None:
        """Close the SPI device."""

        if self._spi is not None:
            self._spi.close()
            self._spi = None

    def _read_packet(self) -> bytes:
        assert self._spi is not None

        try:
            packet = bytes(self._spi.readbytes(self.config.packet_size))
        except Exception as exc:
            raise ThermalError("Unable to read VoSPI packet from FLIR Lepton.") from exc

        if len(packet) != self.config.packet_size:
            raise ThermalError(
                f"Expected {self.config.packet_size} VoSPI bytes, received {len(packet)}."
            )

        return packet

    @staticmethod
    def _is_discard_packet(packet: bytes) -> bool:
        return (packet[0] & 0x0F) == 0x0F

    def _packet_payload_to_row(self, packet: bytes) -> np.ndarray:
        payload = packet[4:]
        row = np.frombuffer(payload, dtype=">u2").astype(np.uint16)
        if row.size != self.config.width:
            raise ThermalError(f"Expected {self.config.width} thermal pixels, received {row.size}.")

        return row

    def _resync(self) -> None:
        time.sleep(self.config.resync_delay_s)

    def __enter__(self) -> "FLIRLepton25":
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()
