#!/usr/bin/env python3
"""Orchestrate CTA control, power monitoring, and scheduled water draws."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO, Any

# Preserve the documented direct-script launch while allowing package imports.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from .conformance_report import generate_conformance_report
    from .schedule_compiler import compile_cta_schedule
    from .schedule_parser import ScheduleEvent, load_schedule
    from .sensors.sensor_configuration_loader import (
        load_sensor_configuration,
    )
    from .xlsx_schedule_importer import import_xlsx_schedule
except ImportError:
    from conformance_report import generate_conformance_report
    from schedule_compiler import compile_cta_schedule
    from schedule_parser import ScheduleEvent, load_schedule
    from sensors.sensor_configuration_loader import load_sensor_configuration
    from xlsx_schedule_importer import import_xlsx_schedule

from software.pacific_time import pacific_filename_timestamp, pacific_timestamp
from software.station.station_identity import station_results_directory


SOFTWARE_DIRECTORY = Path(__file__).resolve().parent
CONFORMANCE_REPOSITORY = SOFTWARE_DIRECTORY.parent
ROOT_DIRECTORY = CONFORMANCE_REPOSITORY.parent
DEFAULT_MASTER_SCHEDULE = SOFTWARE_DIRECTORY / "conformance_test_schedule_main.xlsx"
DEFAULT_CANONICAL_SCHEDULE = SOFTWARE_DIRECTORY / "conformance_test_schedule.csv"
DEFAULT_RESULTS_ROOT = CONFORMANCE_REPOSITORY / "saved_data" / "conformance_runs"
DEFAULT_EQUIPMENT_DIRECTORY = CONFORMANCE_REPOSITORY / "saved_data" / "equipment"
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
DEFAULT_GIT_PUSH_RETRIES = 5
DEFAULT_GIT_TIMEOUT_SECONDS = 60.0
GUI_STAGE_PATH_ENV = "CONFORMANCE_GUI_STAGE_PATH"


def _archive_station_equipment(
    run_directory: Path,
    *,
    hostname: str | None = None,
    equipment_directory: Path = DEFAULT_EQUIPMENT_DIRECTORY,
) -> Path | None:
    """Copy the active station equipment identity into a new run."""
    active_hostname = hostname or socket.gethostname()
    try:
        from software.station.station_identity import station_number

        number = station_number(active_hostname)
    except ValueError:
        return None
    source = equipment_directory / f"WH-station{number}.json"
    if not source.is_file():
        return None
    destination = run_directory / "equipment.json"
    shutil.copy2(source, destination)
    return destination


def _write_gui_stage(state: str, message: str) -> None:
    """Publish an optional GUI lifecycle marker without coupling to the GUI."""
    configured = os.environ.get(GUI_STAGE_PATH_ENV)
    if not configured:
        return
    path = Path(configured)
    temporary = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps({"state": state, "message": message}) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError as exc:
        print(f"GUI_STAGE_WARNING {exc}", file=sys.stderr)
        temporary.unlink(missing_ok=True)


def _run_git(
    repository: Path,
    arguments: list[str],
    *,
    timeout_seconds: float = DEFAULT_GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run Git without allowing an unattended test station to prompt."""
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def publish_run_results(
    run_directory: Path,
    test_name: str,
    *,
    repository: Path = DEFAULT_RESULTS_ROOT,
    remote: str = "origin",
    branch: str = "main",
    push_retries: int = DEFAULT_GIT_PUSH_RETRIES,
) -> bool:
    """Commit one run and publish it, retrying concurrent station pushes."""
    from software.station.station_identity import station_number

    repository = repository.resolve()
    run_directory = run_directory.resolve()
    try:
        run_path = run_directory.relative_to(repository)
        number = station_number()
    except ValueError as exc:
        print(f"GIT_PUBLISH_ERROR {exc}", file=sys.stderr)
        return False

    pathspec = run_path.as_posix()
    try:
        top_level = _run_git(repository, ["rev-parse", "--show-toplevel"])
        if top_level.returncode != 0:
            raise RuntimeError(top_level.stderr.strip() or top_level.stdout.strip())
        resolved_top_level = Path(top_level.stdout.strip()).resolve()
        if resolved_top_level != repository:
            raise RuntimeError(
                f"{repository} is not the root of the conformance-runs Git repository"
            )

        added = _run_git(repository, ["add", "--", pathspec])
        if added.returncode != 0:
            raise RuntimeError(added.stderr.strip() or added.stdout.strip())

        committed = _run_git(
            repository,
            [
                "commit",
                "--only",
                "-m",
                f"{test_name} run WH-{number}",
                "--",
                pathspec,
            ],
        )
        if committed.returncode != 0:
            output = f"{committed.stdout}\n{committed.stderr}".lower()
            if "nothing to commit" in output:
                print(f"GIT_PUBLISH_SKIPPED no changes in {pathspec}")
                return True
            raise RuntimeError(committed.stderr.strip() or committed.stdout.strip())

        for attempt in range(1, push_retries + 1):
            pulled = _run_git(
                repository,
                ["pull", "--rebase", "--autostash", remote, branch],
            )
            if pulled.returncode != 0:
                raise RuntimeError(pulled.stderr.strip() or pulled.stdout.strip())

            pushed = _run_git(repository, ["push", remote, branch])
            if pushed.returncode == 0:
                print(f"GIT_PUBLISH_COMPLETE {pathspec}")
                return True
            if attempt < push_retries:
                print(
                    f"GIT_PUSH_RETRY attempt {attempt + 1} of {push_retries}",
                    file=sys.stderr,
                )

        raise RuntimeError(pushed.stderr.strip() or pushed.stdout.strip())
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        print(
            f"GIT_PUBLISH_ERROR results remain saved locally: {exc}",
            file=sys.stderr,
        )
        return False


def _generate_energy_take_plot(run_directory: Path) -> Path | None:
    from software.run_plot import plot_run

    return plot_run(
        run_directory,
        output_path=run_directory / "energy_take_power.png",
    )[1]


def _generate_state_verification_plot(run_directory: Path) -> Path | None:
    from software.state_verification_plot import plot_state_verification

    return plot_state_verification(
        run_directory,
        output_path=run_directory / "operational_state_verification.png",
    )[1]


def _generate_phase_summary(run_directory: Path) -> Path | None:
    from software.phase_summary_plot import plot_phase_summary

    return plot_phase_summary(
        run_directory,
        output_path=run_directory / "phase_summary.png",
    )[1]


def _generate_event_timeline(run_directory: Path) -> Path | None:
    from software.event_timeline import plot_event_timeline

    return plot_event_timeline(
        run_directory,
        output_path=run_directory / "event_timeline.png",
        csv_output_path=run_directory / "event_timeline.csv",
    )[1]


def generate_final_outputs(
    run_directory: Path,
    *,
    output_stream: IO[str] | None = None,
    error_stream: IO[str] | None = None,
) -> None:
    """Generate independent report artifacts after all run files are closed."""
    output_stream = output_stream or sys.stdout
    error_stream = error_stream or sys.stderr
    tasks = (
        ("CONFORMANCE_REPORT", lambda: generate_conformance_report(run_directory)),
        (
            "ENERGY_TAKE_PLOT",
            lambda: _generate_energy_take_plot(run_directory),
        ),
        (
            "STATE_VERIFICATION_PLOT",
            lambda: _generate_state_verification_plot(run_directory),
        ),
        (
            "PHASE_SUMMARY",
            lambda: _generate_phase_summary(run_directory),
        ),
        (
            "EVENT_TIMELINE",
            lambda: _generate_event_timeline(run_directory),
        ),
    )
    for label, generate in tasks:
        try:
            path = generate()
            print(f"{label} {path}", file=output_stream, flush=True)
        except Exception as artifact_error:
            print(
                f"{label}_ERROR {type(artifact_error).__name__}: {artifact_error}",
                file=error_stream,
                flush=True,
            )

RUN_EVENT_COLUMNS = (
    "timestamp_pacific",
    "test_elapsed_seconds",
    "event_id",
    "event",
    "status",
    "details",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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


def clock_text(seconds: float) -> str:
    """Format a nonnegative duration as HH:MM:SS."""
    total_seconds = max(0, int(math.ceil(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"


def progress_text(
    events: list[ScheduleEvent],
    elapsed_seconds: float,
    *,
    status: str = "running",
    bar_width: int = 20,
) -> str:
    """Build one human-readable progress line for a validated schedule."""
    test_end = next(
        event
        for event in events
        if event.event_type == "test" and event.action == "end"
    )
    duration = test_end.offset_seconds
    effective_elapsed = min(max(elapsed_seconds, 0.0), float(duration))
    percentage = 100.0 if duration == 0 else effective_elapsed / duration * 100.0
    completed_cells = min(
        bar_width,
        max(0, int(percentage / 100.0 * bar_width)),
    )
    bar = "#" * completed_cells + "-" * (bar_width - completed_cells)

    phase = events[0].phase or "unspecified"
    for event in events:
        if event.offset_seconds <= elapsed_seconds and event.phase:
            phase = event.phase

    next_event = next(
        (event for event in events if event.offset_seconds > elapsed_seconds),
        None,
    )
    if next_event is None:
        next_text = "none"
    else:
        countdown = next_event.offset_seconds - elapsed_seconds
        next_text = f"{next_event.event_id} in {clock_text(countdown)}"

    fields = [
        f"[{bar}] {percentage:5.1f}%",
        f"elapsed {clock_text(effective_elapsed)}",
        f"remaining {clock_text(duration - effective_elapsed)}",
        f"phase {phase}",
        f"next {next_text}",
        f"status {status}",
    ]
    if elapsed_seconds < 0:
        fields.insert(1, f"starts in {clock_text(-elapsed_seconds)}")
    return " | ".join(fields)


class ProgressReporter:
    """Render live terminal progress without flooding redirected output."""

    _GREEN = "\x1b[32m"
    _RESET_COLOR = "\x1b[0m"

    def __init__(
        self,
        events: list[ScheduleEvent],
        *,
        stream: IO[str] | None = None,
    ) -> None:
        self._events = events
        self._stream = stream or sys.stdout
        self._interactive = bool(self._stream.isatty())
        self._minimum_interval = 1.0 if self._interactive else 60.0
        self._last_update = float("-inf")
        self._finished = False

    def update(
        self,
        elapsed_seconds: float,
        *,
        status: str = "running",
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        if not force and now - self._last_update < self._minimum_interval:
            return
        line = progress_text(self._events, elapsed_seconds, status=status)
        if self._interactive:
            terminal_width = shutil.get_terminal_size(fallback=(80, 24)).columns
            # Leave the final terminal column unused so an exact-width line
            # cannot wrap when the cursor reaches the right edge.
            available_width = max(1, terminal_width - 1)
            fitted = line[:available_width]
            self._stream.write(
                "\r\x1b[2K" + self._GREEN + fitted + self._RESET_COLOR
            )
        else:
            self._stream.write(line + "\n")
        self._stream.flush()
        self._last_update = now

    def finish(self, elapsed_seconds: float, status: str) -> None:
        if self._finished:
            return
        self.update(elapsed_seconds, status=status, force=True)
        if self._interactive:
            self._stream.write("\n")
            self._stream.flush()
        self._finished = True


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
                "timestamp_pacific": pacific_timestamp(),
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


def stop_water_draw_at_test_end(
    active_draw: ManagedProcess,
    *,
    timeout_seconds: float,
    logger: RunEventLogger,
) -> None:
    """Close an active draw when the test reaches its hard end boundary."""
    event_id = active_draw.event_id
    stop_process(active_draw, timeout_seconds=timeout_seconds, logger=logger)
    logger.record(
        "water_draw_test_end_cutoff",
        "stopped",
        event_id=event_id,
        details={"reason": "test_end_reached"},
    )


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
        "--sensor-configuration",
        "--sensor-calibration",
        dest="sensor_configuration",
        type=Path,
        help=(
            "water-sensor configuration JSON containing electrical and/or "
            "sensor_ranges overrides; nominal values are used when omitted"
        ),
    )
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
    parser.add_argument(
        "--disable-outside-communication-heartbeat",
        action="store_true",
        help=(
            "disable recurring 13-minute-30-second outside-communication "
            "refreshes; per-command prerequisites remain enabled"
        ),
    )
    parser.add_argument(
        "--no-publish-results",
        action="store_true",
        help="save results locally without committing and pushing them to GitHub",
    )
    return parser


def _create_run_directory(
    results_root: Path,
    requested_id: str | None,
    master_schedule: Path,
) -> Path:
    schedule_name = safe_identifier(master_schedule.stem)
    run_id = requested_id or f"{schedule_name}_{pacific_filename_timestamp()}"
    run_directory = (results_root / run_id).resolve()
    run_directory.mkdir(parents=True, exist_ok=False)
    return run_directory


def _launch_water_draw(
    event: ScheduleEvent,
    run_directory: Path,
    *,
    enable_output: bool,
    sensor_configuration: Path | None,
    equipment_configuration: Path | None = None,
) -> ManagedProcess:
    output_csv = run_directory / f"{event.event_id}.csv"
    command = [
        sys.executable,
        "-m",
        "software.water_draw_monitor",
        "--event-id",
        event.event_id,
        "--draw-type",
        "temp_drop" if getattr(event, "draw_type", "volume") == "temp drop" else "volume",
        "--output-csv",
        str(output_csv),
        "--sample-interval-seconds",
        "0.5",
    ]
    if getattr(event, "draw_type", "volume") == "temp drop":
        if equipment_configuration is None:
            raise RuntimeError("Temp Drop draw requires archived station equipment")
        equipment = json.loads(equipment_configuration.read_text(encoding="utf-8"))
        setpoint = equipment.get("temperature_setpoint_f")
        if isinstance(setpoint, bool) or not isinstance(setpoint, (int, float)) or not math.isfinite(float(setpoint)):
            raise RuntimeError("Temp Drop draw requires finite equipment temperature_setpoint_f")
        command.extend([
            "--temp-set-f", str(setpoint),
            "--temp-drop-f", str(event.temp_drop_f),
            "--max-run-minutes", str(event.max_draw_minutes),
        ])
    else:
        command.extend(["--target-gal", str(event.target_volume_gal)])
    if sensor_configuration is not None:
        command.extend(["--sensor-configuration", str(sensor_configuration)])
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
    if args.sensor_configuration is not None:
        load_sensor_configuration(args.sensor_configuration)

    run_directory = _create_run_directory(
        station_results_directory(args.results_root),
        args.run_id,
        args.master_schedule,
    )
    archived_equipment = _archive_station_equipment(run_directory)
    if archived_equipment is None:
        print("EQUIPMENT_SNAPSHOT_WARNING station equipment not available", file=sys.stderr)
    if any(event.draw_type == "temp drop" for event in events):
        if archived_equipment is None:
            raise RuntimeError("Temp Drop schedule requires station equipment configuration")
        equipment = json.loads(archived_equipment.read_text(encoding="utf-8"))
        setpoint = equipment.get("temperature_setpoint_f")
        if isinstance(setpoint, bool) or not isinstance(setpoint, (int, float)) or not math.isfinite(float(setpoint)):
            raise RuntimeError("Temp Drop schedule requires finite temperature_setpoint_f")
    if args.master_schedule.suffix.lower() == ".xlsx":
        shutil.copy2(args.master_schedule, run_directory / "master_schedule.xlsx")
    shutil.copy2(canonical_schedule, run_directory / "master_schedule.csv")
    archived_sensor_configuration: Path | None = None
    if args.sensor_configuration is not None:
        archived_sensor_configuration = (
            run_directory / "sensor_configuration.json"
        )
        shutil.copy2(args.sensor_configuration, archived_sensor_configuration)
    start_monotonic = time.monotonic()
    logger = RunEventLogger(run_directory / "orchestrator_events.csv", start_monotonic)
    power: ManagedProcess | None = None
    controller: ManagedProcess | None = None
    active_draw: ManagedProcess | None = None
    progress: ProgressReporter | None = None
    last_elapsed = -args.prestart_seconds
    outcome = "failed"

    try:
        logger.record(
            "run_created",
            "ok",
            details={
                "run_directory": str(run_directory),
                "water_output_enabled": args.enable_water_output,
                "outside_communication_heartbeat_enabled": (
                    not args.disable_outside_communication_heartbeat
                ),
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
        compile_cta_schedule(
            canonical_schedule,
            test_start=test_start_utc,
            controller_output=args.cta_schedule,
            preview_output=run_directory / "cta_schedule_preview.csv",
            outside_communication_heartbeat_enabled=(
                not args.disable_outside_communication_heartbeat
            ),
        )
        shutil.copy2(args.cta_schedule, run_directory / "cta_schedule_generated.csv")

        controller_environment = os.environ.copy()
        controller_environment.update(
            {
                "TZ": "America/Los_Angeles",
                "CTA_EVENT_LOG_PATH": str(run_directory / "cta_events.csv"),
                "CTA_RAW_MESSAGE_LOG_PATH": str(
                    run_directory / "cta_raw_messages.csv"
                ),
                "CTA_COMMODITY_LOG_PATH": str(run_directory / "cta_commodity.csv"),
                "CTA_DEVICE_INFO_LOG_PATH": str(
                    run_directory / "cta_device_information.csv"
                ),
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
            details={
                "test_start_pacific": pacific_timestamp(test_start_utc)
            },
        )

        draws = [event for event in events if event.event_type == "water_draw"]
        test_end = next(event for event in events if event.event_type == "test")
        dependent_draw_id = (
            max((event for event in draws if event.source_row < test_end.source_row), key=lambda event: event.source_row).event_id
            if test_end.dependent_end else None
        )
        progress = ProgressReporter(events)
        next_draw_index = 0
        test_started_logged = False

        while True:
            elapsed = time.monotonic() - test_start_monotonic
            last_elapsed = elapsed
            progress.update(elapsed)
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
                completed_draw_id = active_draw.event_id
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
                if completed_draw_id == dependent_draw_id:
                    logger.record("dependent_test_end", "triggered", event_id=completed_draw_id)
                    outcome = "completed"
                    break

            if not test_end.dependent_end and elapsed >= test_end.offset_seconds:
                if active_draw is not None:
                    stop_water_draw_at_test_end(
                        active_draw,
                        timeout_seconds=args.shutdown_timeout_seconds,
                        logger=logger,
                    )
                    active_draw = None
                outcome = "completed"
                break

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
                    sensor_configuration=archived_sensor_configuration,
                    equipment_configuration=archived_equipment,
                )
                logger.record(
                    "water_draw_started",
                    "started",
                    event_id=event.event_id,
                    details={
                        "pid": active_draw.process.pid,
                        "draw_type": event.draw_type,
                        "target_volume_gal": event.target_volume_gal,
                        "temp_drop_f": event.temp_drop_f,
                    },
                )

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
        _write_gui_stage(
            "finalizing",
            "Scheduled test complete; returning hardware to normal and closing logs.",
        )
        if progress is not None:
            progress.finish(
                test_end.offset_seconds if outcome == "completed" else last_elapsed,
                outcome,
            )

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
        _write_gui_stage(
            "generating_outputs",
            "Hardware shutdown complete; generating the report and PNG files.",
        )
        generate_final_outputs(run_directory)
        if not args.no_publish_results:
            _write_gui_stage(
                "publishing_results",
                "Reports generated; publishing this run to GitHub.",
            )
            publish_run_results(
                run_directory,
                safe_identifier(args.master_schedule.stem),
            )
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
        print(
            "OUTSIDE_COMMUNICATION_HEARTBEAT "
            + (
                "disabled (15-second command prerequisites remain enabled)"
                if args.disable_outside_communication_heartbeat
                else "enabled (refresh interval 13 minutes 30 seconds)"
            )
        )
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
