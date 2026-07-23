#!/usr/bin/env python3
"""Orchestrate CTA control, power monitoring, and scheduled water draws."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO, Any

try:
    from .schedule_compiler import compile_cta_schedule
    from .schedule_parser import ScheduleEvent, load_schedule
    from .xlsx_schedule_importer import import_xlsx_schedule
except ImportError:
    from schedule_compiler import compile_cta_schedule
    from schedule_parser import ScheduleEvent, load_schedule
    from xlsx_schedule_importer import import_xlsx_schedule


SOFTWARE_DIRECTORY = Path(__file__).resolve().parent
CONFORMANCE_REPOSITORY = SOFTWARE_DIRECTORY.parent
ROOT_DIRECTORY = CONFORMANCE_REPOSITORY.parent
DEFAULT_MASTER_SCHEDULE = SOFTWARE_DIRECTORY / "conformance_test_schedule_main.xlsx"
DEFAULT_CANONICAL_SCHEDULE = SOFTWARE_DIRECTORY / "conformance_test_schedule.csv"
DEFAULT_RESULTS_ROOT = CONFORMANCE_REPOSITORY / "saved_data" / "conformance_runs"
DEFAULT_CTA_DIRECTORY = ROOT_DIRECTORY / "cta_2045_controller" / "dcs" / "controller"
DEFAULT_CTA_BINARY = (
    ROOT_DIRECTORY
    / "cta_2045_controller"
    / "dcs"
    / "build"
    / "debug"
    / "cta2045_controller"
)
DEFAULT_CTA_SCHEDULE = DEFAULT_CTA_DIRECTORY / "schedule.csv"
DEFAULT_PRESTART_SECONDS = 15.0

RUN_EVENT_COLUMNS = (
    "timestamp_utc",
    "test_elapsed_seconds",
    "event_id",
    "event",
    "status",
    "details",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def finite_positive(value: str) -> float:
    parsed = float(value)
    if not parsed > 0 or parsed == float("inf"):
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return parsed


def safe_identifier(value: str) -> str:
    sanitized = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in value
    ).strip("_")
    if not sanitized:
        raise argparse.ArgumentTypeError("must contain a letter or number")
    return sanitized


def schedule_summary(events: list[ScheduleEvent]) -> dict[str, Any]:
    test_end = next(
        event
        for event in events
        if event.event_type == "test" and event.action == "end"
    )
    return {
        "enabled_events": len(events),
        "cta_events": sum(event.event_type == "cta" for event in events),
        "water_draws": sum(event.event_type == "water_draw" for event in events),
        "duration_seconds": test_end.offset_seconds,
    }


class RunEventLogger:
    def __init__(self, path: Path, start_monotonic: float) -> None:
        self._start_monotonic = start_monotonic
        self._handle = path.open("x", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(self._handle, fieldnames=RUN_EVENT_COLUMNS)
        self._writer.writeheader()
        self._handle.flush()

    def record(
        self,
        event: str,
        status: str,
        *,
        event_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self._writer.writerow(
            {
                "timestamp_utc": utc_text(),
                "test_elapsed_seconds": f"{time.monotonic() - self._start_monotonic:.3f}",
                "event_id": event_id,
                "event": event,
                "status": status,
                "details": json.dumps(details or {}, separators=(",", ":")),
            }
        )
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen[str]
    log_handle: IO[str]
    event_id: str = ""

    def close_log(self) -> None:
        self.log_handle.close()


def start_process(
    name: str,
    command: list[str],
    *,
    log_path: Path,
    cwd: Path,
    environment: dict[str, str] | None = None,
    stdin_pipe: bool = False,
    event_id: str = "",
) -> ManagedProcess:
    log_handle = log_path.open("x", encoding="utf-8", buffering=1)
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdin=subprocess.PIPE if stdin_pipe else subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
    except BaseException:
        log_handle.close()
        raise
    return ManagedProcess(name, process, log_handle, event_id)


def wait_for_power_ready(
    process: ManagedProcess,
    output_csv: Path,
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        return_code = process.process.poll()
        if return_code is not None:
            raise RuntimeError(
                f"power monitor exited before ready with code {return_code}"
            )
        if output_csv.exists() and output_csv.stat().st_size > 0:
            return
        time.sleep(0.1)
    raise TimeoutError("power monitor did not create its CSV before startup timeout")


def stop_process(
    managed: ManagedProcess,
    *,
    timeout_seconds: float,
    logger: RunEventLogger,
) -> None:
    if managed.process.poll() is None:
        managed.process.terminate()
        try:
            managed.process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            logger.record(
                "process_kill",
                "forced",
                event_id=managed.event_id,
                details={"process": managed.name},
            )
            managed.process.kill()
            managed.process.wait(timeout=5)
    managed.close_log()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--master-schedule", type=Path, default=DEFAULT_MASTER_SCHEDULE
    )
    parser.add_argument(
        "--canonical-schedule-output",
        type=Path,
        default=DEFAULT_CANONICAL_SCHEDULE,
        help="CSV generated when --master-schedule is an XLSX workbook",
    )
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--run-id", type=safe_identifier)
    parser.add_argument("--cta-controller-dir", type=Path, default=DEFAULT_CTA_DIRECTORY)
    parser.add_argument("--cta-binary", type=Path, default=DEFAULT_CTA_BINARY)
    parser.add_argument("--cta-schedule", type=Path, default=DEFAULT_CTA_SCHEDULE)
    parser.add_argument(
        "--prestart-seconds",
        type=finite_positive,
        default=DEFAULT_PRESTART_SECONDS,
        help="time from process startup to official test time zero",
    )
    parser.add_argument(
        "--startup-timeout-seconds", type=finite_positive, default=15.0
    )
    parser.add_argument(
        "--shutdown-timeout-seconds", type=finite_positive, default=30.0
    )
    parser.add_argument(
        "--run-hardware",
        action="store_true",
        help="launch the controller and hardware processes; otherwise validate only",
    )
    parser.add_argument(
        "--enable-water-output",
        action="store_true",
        help="pass --enable-output to scheduled water draws",
    )
    return parser


def _create_run_directory(results_root: Path, requested_id: str | None) -> Path:
    run_id = requested_id or utc_now().strftime("run_%Y_%m_%d_%H%M%SZ")
    run_directory = (results_root / run_id).resolve()
    run_directory.mkdir(parents=True, exist_ok=False)
    return run_directory


def _launch_water_draw(
    event: ScheduleEvent,
    run_directory: Path,
    *,
    enable_output: bool,
) -> ManagedProcess:
    output_csv = run_directory / f"{event.event_id}.csv"
    command = [
        sys.executable,
        str(SOFTWARE_DIRECTORY / "water_draw_monitor.py"),
        "--event-id",
        event.event_id,
        "--target-gal",
        str(event.target_volume_gal),
        "--output-csv",
        str(output_csv),
        "--sample-interval-seconds",
        "0.5",
    ]
    if enable_output:
        command.append("--enable-output")
    return start_process(
        "water_draw",
        command,
        log_path=run_directory / f"{event.event_id}.log",
        cwd=CONFORMANCE_REPOSITORY,
        event_id=event.event_id,
    )


def prepare_master_schedule(
    source: Path,
    canonical_output: Path,
) -> Path:
    """Return a validated canonical CSV, importing XLSX when necessary."""
    suffix = source.suffix.lower()
    if suffix == ".xlsx":
        return import_xlsx_schedule(source, canonical_output)
    if suffix == ".csv":
        load_schedule(source)
        return source
    raise ValueError("master schedule must be a .xlsx or .csv file")


def run_hardware_test(
    args: argparse.Namespace,
    events: list[ScheduleEvent],
    canonical_schedule: Path,
) -> Path:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("--run-hardware is supported only on the Linux test station")
    if not args.cta_binary.is_file():
        raise FileNotFoundError(f"CTA controller binary not found: {args.cta_binary}")
    if args.prestart_seconds < 15.0:
        raise ValueError("prestart-seconds must be at least the 15-second CTA lead")

    run_directory = _create_run_directory(args.results_root, args.run_id)
    if args.master_schedule.suffix.lower() == ".xlsx":
        shutil.copy2(args.master_schedule, run_directory / "master_schedule.xlsx")
    shutil.copy2(canonical_schedule, run_directory / "master_schedule.csv")
    start_monotonic = time.monotonic()
    logger = RunEventLogger(run_directory / "orchestrator_events.csv", start_monotonic)
    power: ManagedProcess | None = None
    controller: ManagedProcess | None = None
    active_draw: ManagedProcess | None = None
    outcome = "failed"

    try:
        logger.record(
            "run_created",
            "ok",
            details={
                "run_directory": str(run_directory),
                "water_output_enabled": args.enable_water_output,
            },
        )

        power_csv = run_directory / "power.csv"
        power = start_process(
            "power_monitor",
            [
                sys.executable,
                str(SOFTWARE_DIRECTORY / "wh_power_monitor.py"),
                "--output-csv",
                str(power_csv),
                "--heartbeat-seconds",
                "60",
            ],
            log_path=run_directory / "power_monitor.log",
            cwd=CONFORMANCE_REPOSITORY,
        )
        wait_for_power_ready(
            power, power_csv, timeout_seconds=args.startup_timeout_seconds
        )
        logger.record("power_monitor", "ready", details={"pid": power.process.pid})

        proposed_start = utc_now() + timedelta(seconds=args.prestart_seconds)
        test_start_utc = datetime.fromtimestamp(
            math.ceil(proposed_start.timestamp()), tz=timezone.utc
        )
        if args.cta_schedule.exists():
            shutil.copy2(args.cta_schedule, run_directory / "cta_schedule_before_run.csv")
        compile_cta_schedule(
            canonical_schedule,
            test_start=test_start_utc,
            controller_output=args.cta_schedule,
            preview_output=run_directory / "cta_schedule_preview.csv",
        )
        shutil.copy2(args.cta_schedule, run_directory / "cta_schedule_generated.csv")

        controller_environment = os.environ.copy()
        controller_environment.update(
            {
                "CTA_EVENT_LOG_PATH": str(run_directory / "cta_events.csv"),
                "CTA_COMMODITY_LOG_PATH": str(run_directory / "cta_commodity.csv"),
            }
        )
        controller = start_process(
            "cta_controller",
            [str(args.cta_binary)],
            log_path=run_directory / "cta_controller.log",
            cwd=args.cta_controller_dir,
            environment=controller_environment,
            stdin_pipe=True,
        )
        time.sleep(1.0)
        if controller.process.poll() is not None:
            raise RuntimeError(
                f"CTA controller exited during startup with code {controller.process.returncode}"
            )
        logger.record(
            "cta_controller",
            "started",
            details={"pid": controller.process.pid},
        )

        seconds_until_start = (test_start_utc - utc_now()).total_seconds()
        test_start_monotonic = time.monotonic() + max(seconds_until_start, 0.0)
        logger._start_monotonic = test_start_monotonic
        logger.record(
            "test_start_scheduled",
            "pending",
            details={"test_start_utc": utc_text(test_start_utc)},
        )

        draws = [event for event in events if event.event_type == "water_draw"]
        test_end = next(event for event in events if event.event_type == "test")
        next_draw_index = 0
        test_started_logged = False

        while True:
            elapsed = time.monotonic() - test_start_monotonic
            if not test_started_logged and elapsed >= 0:
                logger.record("test_started", "ok")
                test_started_logged = True

            if power.process.poll() is not None:
                raise RuntimeError(
                    f"power monitor exited unexpectedly with code {power.process.returncode}"
                )
            if controller.process.poll() is not None:
                raise RuntimeError(
                    f"CTA controller exited unexpectedly with code {controller.process.returncode}"
                )

            if active_draw is not None and active_draw.process.poll() is not None:
                return_code = active_draw.process.returncode
                logger.record(
                    "water_draw_completed",
                    "ok" if return_code == 0 else "failed",
                    event_id=active_draw.event_id,
                    details={"return_code": return_code},
                )
                active_draw.close_log()
                active_draw = None
                if return_code != 0:
                    raise RuntimeError(f"water draw failed with code {return_code}")

            while (
                next_draw_index < len(draws)
                and elapsed >= draws[next_draw_index].offset_seconds
            ):
                event = draws[next_draw_index]
                next_draw_index += 1
                if active_draw is not None:
                    logger.record(
                        "water_draw_missed",
                        "failed",
                        event_id=event.event_id,
                        details={"reason": "previous_draw_still_active"},
                    )
                    raise RuntimeError("scheduled water draws overlapped at runtime")
                active_draw = _launch_water_draw(
                    event,
                    run_directory,
                    enable_output=args.enable_water_output,
                )
                logger.record(
                    "water_draw_started",
                    "started",
                    event_id=event.event_id,
                    details={
                        "pid": active_draw.process.pid,
                        "target_volume_gal": event.target_volume_gal,
                    },
                )

            if elapsed >= test_end.offset_seconds and active_draw is None:
                outcome = "completed"
                break
            time.sleep(0.2)

    except KeyboardInterrupt:
        outcome = "interrupted"
        logger.record("run_interrupted", "requested")
    except Exception as exc:
        outcome = "failed"
        logger.record(
            "run_error",
            "failed",
            details={"error_type": type(exc).__name__, "message": str(exc)},
        )
        raise
    finally:
        if active_draw is not None:
            stop_process(
                active_draw,
                timeout_seconds=args.shutdown_timeout_seconds,
                logger=logger,
            )
            logger.record(
                "water_draw_shutdown", "stopped", event_id=active_draw.event_id
            )

        if controller is not None:
            if controller.process.poll() is None and controller.process.stdin is not None:
                try:
                    logger.record("cta_return_to_normal", "requested")
                    controller.process.stdin.write("z\n")
                    controller.process.stdin.flush()
                    controller.process.wait(timeout=args.shutdown_timeout_seconds)
                    logger.record(
                        "cta_return_to_normal",
                        "completed",
                        details={"return_code": controller.process.returncode},
                    )
                except (BrokenPipeError, subprocess.TimeoutExpired) as exc:
                    logger.record(
                        "cta_return_to_normal",
                        "failed",
                        details={"message": str(exc)},
                    )
            stop_process(
                controller,
                timeout_seconds=args.shutdown_timeout_seconds,
                logger=logger,
            )

        if power is not None:
            stop_process(
                power,
                timeout_seconds=args.shutdown_timeout_seconds,
                logger=logger,
            )
            logger.record("power_monitor_shutdown", "stopped")

        logger.record("run_finished", outcome)
        logger.close()
    return run_directory


def main() -> int:
    args = build_parser().parse_args()
    try:
        canonical_schedule = prepare_master_schedule(
            args.master_schedule,
            args.canonical_schedule_output,
        )
        events = load_schedule(canonical_schedule)
        summary = schedule_summary(events)
        print("SCHEDULE_VALID " + json.dumps(summary, sort_keys=True))
        if args.master_schedule.suffix.lower() == ".xlsx":
            print(f"CANONICAL_SCHEDULE {canonical_schedule}")
        if not args.run_hardware:
            print("Validation only. Pass --run-hardware on the Pi to launch processes.")
            return 0
        run_directory = run_hardware_test(args, events, canonical_schedule)
        print(f"CONFORMANCE_TEST_RESULTS {run_directory}")
        return 0
    except Exception as exc:
        print(f"CONFORMANCE_TEST_ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
