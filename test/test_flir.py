from pathlib import Path
import argparse
import os
import sys
from typing import Iterable, Optional, Tuple

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.thermal import (
    FLIRLepton25,
    LeptonConfig,
    SpiProbeResult,
    apply_jet_colormap,
    parse_spi_candidates,
    scan_spidev,
    select_active_spidev,
    tlinear_to_celsius,
)


def env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def env_optional_int(name: str) -> Optional[int]:
    value = os.getenv(name)
    return None if value is None else int(value)


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def print_probe_results(probes: Iterable[SpiProbeResult]) -> None:
    for probe in probes:
        name = f"spidev{probe.bus}.{probe.device}"
        if probe.error:
            print(f"{name} error={probe.error}")
            continue

        state = "active-candidate" if probe.is_active else "flat"
        print(
            f"{name} {probe.prefix_hex} "
            f"unique: {list(probe.unique_values)} "
            f"score={probe.active_score} {state}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture and diagnose FLIR Lepton SPI frames")
    parser.add_argument("--scan-only", action="store_true", help="Only probe candidate SPI devices")
    parser.add_argument("--no-scan", action="store_true", help="Skip probing and use env/arg bus/device")
    parser.add_argument("--bus", type=int, default=None, help="SPI bus override")
    parser.add_argument("--device", type=int, default=None, help="SPI device override")
    parser.add_argument("--speed-hz", type=int, default=env_int("FLIR_SPI_SPEED_HZ", 18_000_000))
    parser.add_argument("--probe-speed-hz", type=int, default=env_int("FLIR_PROBE_SPEED_HZ", 2_000_000))
    parser.add_argument("--packet-size", type=int, default=LeptonConfig.packet_size)
    parser.add_argument(
        "--candidates",
        default=os.getenv("FLIR_SPI_CANDIDATES", "0.0,0.1,1.0,1.1"),
        help="Comma-separated bus.device list used for probing",
    )
    parser.add_argument("--output-scale", type=int, default=env_int("FLIR_OUTPUT_SCALE", 8))
    parser.add_argument("--tlinear-scale", type=float, default=env_float("FLIR_TLINEAR_SCALE", 100.0))
    parser.add_argument("--flip-code", default=os.getenv("FLIR_FLIP_CODE", "-1"))
    parser.add_argument("--max-frame-attempts", type=int, default=env_int("FLIR_MAX_FRAME_ATTEMPTS", 8))
    parser.add_argument("--max-sync-packets", type=int, default=env_int("FLIR_MAX_SYNC_PACKETS", 20_000))
    parser.add_argument("--resync-delay-s", type=float, default=env_float("FLIR_RESYNC_DELAY_S", 0.2))
    parser.add_argument(
        "--reset-before-capture",
        action="store_true",
        default=env_bool("FLIR_RESET_BEFORE_CAPTURE", False),
        help="Reset FLIR capture before reading a frame",
    )
    parser.add_argument(
        "--reset-only",
        action="store_true",
        help="Reset FLIR capture and exit without saving an image",
    )
    parser.add_argument(
        "--reset-board-pin",
        type=int,
        default=env_optional_int("FLIR_RESET_BOARD_PIN"),
        help="Optional Jetson J41 physical pin wired to FLIR reset/enable",
    )
    parser.add_argument(
        "--reset-active-high",
        action="store_true",
        default=env_bool("FLIR_RESET_ACTIVE_HIGH", False),
        help="Use active-high reset pulse instead of the default active-low pulse",
    )
    parser.add_argument("--reset-pulse-s", type=float, default=env_float("FLIR_RESET_PULSE_S", 0.2))
    parser.add_argument("--reset-settle-s", type=float, default=env_float("FLIR_RESET_SETTLE_S", 0.75))
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[1] / "results" / "test_flir.jpg"),
    )
    return parser


def resolve_spi_target(args: argparse.Namespace) -> Tuple[int, int]:
    arg_target = args.bus is not None or args.device is not None
    env_target = "FLIR_SPI_BUS" in os.environ or "FLIR_SPI_DEVICE" in os.environ
    if args.no_scan or arg_target or env_target:
        return (
            args.bus if args.bus is not None else env_int("FLIR_SPI_BUS", LeptonConfig.spi_bus),
            args.device
            if args.device is not None
            else env_int("FLIR_SPI_DEVICE", LeptonConfig.spi_device),
        )

    probes = scan_spidev(
        parse_spi_candidates(args.candidates),
        speed_hz=args.probe_speed_hz,
        packet_size=args.packet_size,
    )
    print_probe_results(probes)
    active = select_active_spidev(probes)
    if active is None:
        raise RuntimeError("No active FLIR-like SPI device found. Try --bus/--device to force one.")

    print(f"Selected spidev{active.bus}.{active.device}")
    return active.bus, active.device


def draw_temperature_overlay(frame, min_temp, max_temp, min_loc, max_loc, scale):
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


def main() -> int:
    args = build_parser().parse_args()
    candidates = parse_spi_candidates(args.candidates)
    if args.scan_only:
        print_probe_results(
            scan_spidev(
                candidates,
                speed_hz=args.probe_speed_hz,
                packet_size=args.packet_size,
            )
        )
        return 0

    bus, device = resolve_spi_target(args)
    base_config = LeptonConfig(
        spi_bus=bus,
        spi_device=device,
        spi_speed_hz=args.speed_hz,
        packet_size=args.packet_size,
        max_frame_attempts=args.max_frame_attempts,
        max_sync_packets=args.max_sync_packets,
        resync_delay_s=args.resync_delay_s,
        reset_board_pin=args.reset_board_pin,
        reset_active_low=not args.reset_active_high,
        reset_pulse_s=args.reset_pulse_s,
        reset_settle_s=args.reset_settle_s,
    )
    flir = FLIRLepton25(base_config)
    output_path = Path(args.output)
    output_path.parent.mkdir(exist_ok=True)

    try:
        if args.reset_only:
            flir.reset(reopen=False)
            print(
                f"Reset FLIR capture for spidev{base_config.spi_bus}.{base_config.spi_device}"
            )
            return 0

        if args.reset_before_capture:
            flir.reset(reopen=False)

        raw = flir.get_raw_frame()
        flip_code = str(args.flip_code).strip().lower()
        if flip_code not in ("", "none"):
            raw = cv2.flip(raw, int(flip_code))

        temps_c = tlinear_to_celsius(raw, scale=args.tlinear_scale)
        min_temp, max_temp, min_loc, max_loc = cv2.minMaxLoc(temps_c)
        frame = apply_jet_colormap(raw)
        if args.output_scale > 1:
            frame = cv2.resize(
                frame,
                None,
                fx=args.output_scale,
                fy=args.output_scale,
                interpolation=cv2.INTER_NEAREST,
            )

        draw_temperature_overlay(
            frame,
            min_temp=min_temp,
            max_temp=max_temp,
            min_loc=min_loc,
            max_loc=max_loc,
            scale=args.output_scale,
        )

        if not cv2.imwrite(str(output_path), frame):
            raise RuntimeError(f"Unable to write {output_path}")
        print(f"Wrote {output_path} from spidev{base_config.spi_bus}.{base_config.spi_device}")
        return 0
    finally:
        flir.release()


if __name__ == "__main__":
    raise SystemExit(main())
