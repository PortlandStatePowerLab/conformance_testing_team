#!/usr/bin/env python3
"""Serve a small local browser editor for canonical schedule CSV files."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import socket
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import unquote

try:
    from .cta_operational_states import EXPECTED_STATES_BY_ACTION
    from .schedule_parser import (
        ADVANCED_UNIT_CODES,
        CTA_ACTION_CODES,
        DRAW_EXTENDED_SCHEDULE_COLUMNS,
        MAX_DURATION,
        ScheduleValidationError,
        load_schedule,
    )
    from .hardware_preflight import (
        PreflightCheck,
        build_parser as build_preflight_parser,
        run_preflight,
    )
    from .wh_information import read_wh_information
except ImportError:
    from cta_operational_states import EXPECTED_STATES_BY_ACTION
    from schedule_parser import (
        ADVANCED_UNIT_CODES,
        CTA_ACTION_CODES,
        DRAW_EXTENDED_SCHEDULE_COLUMNS,
        MAX_DURATION,
        ScheduleValidationError,
        load_schedule,
    )
    from hardware_preflight import (
        PreflightCheck,
        build_parser as build_preflight_parser,
        run_preflight,
    )
    from wh_information import read_wh_information


SOFTWARE_DIRECTORY = Path(__file__).resolve().parent
DEFAULT_SCHEDULE_DIRECTORY = SOFTWARE_DIRECTORY / "gui_schedules"
EDITOR_PATH = SOFTWARE_DIRECTORY / "templates" / "schedule_gui.html"
SAFE_SCHEDULE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
STATION_HOSTNAME = re.compile(r"WH[-_]?station[-_]?(\d+)\Z", re.IGNORECASE)
STATION_SUFFIX = re.compile(r"_WH_(\d+)\Z", re.IGNORECASE)
MAX_REQUEST_BYTES = 1_000_000
DEFAULT_IDLE_TIMEOUT_HOURS = 48.0
DEFAULT_RUN_DIRECTORY = SOFTWARE_DIRECTORY.parent / "runtime_logs" / "gui_runs"
DEFAULT_EQUIPMENT_DIRECTORY = SOFTWARE_DIRECTORY.parent / "saved_data" / "equipment"
PACIFIC = ZoneInfo("America/Los_Angeles")
PREFLIGHT_MAX_AGE_SECONDS = 300
EQUIPMENT_FIELDS = {
    "manufacturer": str, "model_number": str, "year": int, "voltage": str,
    "capacity_gallons": int, "station_id": str, "date_added": str,
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_station_equipment(
    hostname: str, directory: Path = DEFAULT_EQUIPMENT_DIRECTORY
) -> dict[str, Any]:
    """Load descriptive equipment data selected by the actual Pi hostname."""
    station_suffix_from_hostname(hostname)
    try:
        value = _read_json(directory / f"{hostname}.json")
    except FileNotFoundError as exc:
        raise ValueError(f"equipment information not configured for {hostname}") from exc
    if not isinstance(value, dict):
        raise ValueError("equipment information must be a JSON object")
    missing = sorted(set(EQUIPMENT_FIELDS).difference(value))
    extra = sorted(set(value).difference(set(EQUIPMENT_FIELDS) | {"temperature_setpoint_f"}))
    if missing or extra:
        raise ValueError(
            f"equipment fields invalid; missing={missing}, unexpected={extra}"
        )
    for field, expected_type in EQUIPMENT_FIELDS.items():
        if not isinstance(value[field], expected_type) or isinstance(value[field], bool):
            expected_name = "number" if isinstance(expected_type, tuple) else expected_type.__name__
            raise ValueError(f"equipment field {field} must be {expected_name}")
    if value["station_id"] != hostname:
        raise ValueError(
            f"equipment station_id {value['station_id']!r} does not match "
            f"Pi hostname {hostname!r}"
        )
    if value["year"] < 1900 or value["capacity_gallons"] <= 0:
        raise ValueError("equipment year and capacity must be positive")
    if "temperature_setpoint_f" in value and (
        isinstance(value["temperature_setpoint_f"], bool)
        or not isinstance(value["temperature_setpoint_f"], (int, float))
        or not math.isfinite(float(value["temperature_setpoint_f"]))
    ):
        raise ValueError("equipment temperature_setpoint_f must be finite")
    return value


def current_run(run_directory: Path) -> dict[str, Any] | None:
    pointer = run_directory / "current.json"
    if not pointer.is_file():
        return None
    try:
        current = _read_json(pointer)
        if current.get("dismissed") is True:
            return None
        run_id = str(current["run_id"])
        status = _read_json(run_directory / run_id / "status.json")
        heartbeat = status.get("last_heartbeat_at")
        if heartbeat and status.get("state") in {
            "launching", "initializing", "running", "finalizing", "generating_outputs"
        }:
            age = (datetime.now(PACIFIC) - datetime.fromisoformat(heartbeat)).total_seconds()
            status["status_age_seconds"] = max(0, int(age))
            status["stale"] = age > 90
        return status
    except (KeyError, OSError, ValueError, json.JSONDecodeError):
        return {"state": "unknown", "error": "run status could not be read"}


def dismiss_current_run(run_directory: Path) -> None:
    """Hide a terminal run from the operator dashboard without deleting it."""
    pointer = run_directory / "current.json"
    if not pointer.is_file():
        return
    current = _read_json(pointer)
    run_id = str(current["run_id"])
    status = _read_json(run_directory / run_id / "status.json")
    if status.get("state") not in {"completed", "failed"}:
        raise RuntimeError("an active test cannot be dismissed")
    _atomic_json(pointer, {"run_id": run_id, "dismissed": True})


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".run.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def launch_run(run_directory: Path, schedule: Path, *, water: bool) -> dict[str, Any]:
    active = current_run(run_directory)
    if active and active.get("state") in {
        "launching", "initializing", "running", "finalizing",
        "generating_outputs", "stopping",
    }:
        raise RuntimeError("a conformance test is already active on this station")
    now = datetime.now(PACIFIC)
    run_id = f"gui_{now.strftime('%Y_%m_%d_%H%M%S_%f_%Z')}"
    directory = run_directory / run_id
    directory.mkdir(parents=True, exist_ok=False)
    snapshot = directory / "schedule.csv"
    shutil.copy2(schedule, snapshot)
    result_name = STATION_SUFFIX.sub("", schedule.stem)
    events = load_schedule(snapshot)
    duration = next(event.offset_seconds for event in events if event.event_type == "test")
    status = {
        "run_id": run_id, "state": "launching", "schedule": schedule.name,
        "result_name": result_name,
        "schedule_snapshot": str(snapshot), "water_output_enabled": water,
        "requested_at": now.isoformat(), "duration_seconds": duration,
        "last_heartbeat_at": now.isoformat(),
    }
    _atomic_json(directory / "status.json", status)
    _atomic_json(run_directory / "current.json", {"run_id": run_id})
    command = [sys.executable, "-m", "software.gui_run_worker",
               "--run-directory", str(directory), "--schedule", str(snapshot),
               "--repository-root", str(SOFTWARE_DIRECTORY.parent),
               "--result-name", result_name]
    if water:
        command.append("--water")
    worker_log = (directory / "worker.log").open("a", encoding="utf-8")
    try:
        subprocess.Popen(command, cwd=SOFTWARE_DIRECTORY.parent, stdin=subprocess.DEVNULL,
                         stdout=worker_log, stderr=subprocess.STDOUT,
                         start_new_session=True, close_fds=True)
    except Exception as exc:
        status.update(state="failed", error=f"worker launch failed: {exc}",
                      finished_at=datetime.now(PACIFIC).isoformat())
        _atomic_json(directory / "status.json", status)
        raise
    finally:
        worker_log.close()
    return status


def station_suffix_from_hostname(hostname: str) -> str:
    """Return the filename suffix for a recognized water-heater station."""
    match = STATION_HOSTNAME.fullmatch(hostname.strip())
    if match is None:
        raise ValueError(
            f"hostname {hostname!r} is not a recognized WH-station<number> name"
        )
    return f"WH_{int(match.group(1))}"


def station_schedule_filename(name: str, station_suffix: str) -> str:
    """Build the stored filename for a friendly schedule name and station."""
    normalized = normalize_schedule_name(name)
    stem = Path(normalized).stem
    existing_suffix = STATION_SUFFIX.search(stem)
    if existing_suffix is not None:
        existing = f"WH_{int(existing_suffix.group(1))}"
        if existing != station_suffix:
            raise ValueError(
                f"schedule name belongs to {existing.replace('_', '-')}, "
                f"not {station_suffix.replace('_', '-')}"
            )
        stem = stem[: existing_suffix.start()]
    if len(stem) + len(station_suffix) + 1 > 80:
        raise ValueError("schedule name is too long after adding the station suffix")
    return f"{stem}_{station_suffix}.csv"


def friendly_schedule_name(filename: str, station_suffix: str) -> str:
    """Return the browser-visible name of a station-owned schedule."""
    normalized = normalize_schedule_name(filename)
    expected = f"_{station_suffix}.csv"
    if not normalized.lower().endswith(expected.lower()):
        raise ValueError("schedule does not belong to this station")
    return normalized[: -len(expected)]


def station_schedule_choices(directory: Path, station_suffix: str) -> list[dict[str, str]]:
    """List only schedules owned by the current station."""
    if not directory.is_dir():
        return []
    choices = []
    for path in directory.glob(f"*_{station_suffix}.csv"):
        choices.append(
            {
                "filename": path.name,
                "name": friendly_schedule_name(path.name, station_suffix),
            }
        )
    return sorted(choices, key=lambda item: item["name"].lower())


def editor_metadata(hostname: str | None = None) -> dict[str, Any]:
    """Describe editor choices from the same definitions used by Python."""
    actions = []
    for action in CTA_ACTION_CODES:
        actions.append(
            {
                "action": action,
                "event_type": "cta",
                "expected_operational_states": list(
                    EXPECTED_STATES_BY_ACTION.get(action, ())
                ),
                "fields": (
                    [
                        "event_duration_minutes",
                        "advanced_value",
                        "advanced_units",
                        "advanced_efficiency",
                    ]
                    if action == "advanced_load_up"
                    else ["event_duration_minutes"]
                ),
            }
        )
    actions.extend(
        [
            {
                "action": "water_draw",
                "event_type": "water_draw",
                "expected_operational_states": [],
                "fields": [
                    "draw_type", "target_volume_gal", "expected_flow_gpm",
                    "temp_drop_f", "max_draw_minutes",
                ],
            },
            {
                "action": "end",
                "event_type": "test",
                "expected_operational_states": [],
                "fields": [],
            },
        ]
    )
    resolved_hostname = hostname or socket.gethostname()
    station_match = STATION_HOSTNAME.fullmatch(resolved_hostname.strip())
    equipment = None
    equipment_error = None
    if station_match:
        try:
            equipment = load_station_equipment(resolved_hostname)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            equipment_error = str(exc)
    return {
        "hostname": resolved_hostname,
        "station_suffix": (
            station_suffix_from_hostname(resolved_hostname) if station_match else ""
        ),
        "equipment": equipment,
        "equipment_error": equipment_error,
        "actions": actions,
        "advanced_units": list(ADVANCED_UNIT_CODES),
        "advanced_efficiencies": [
            {"value": 0, "label": "0 — Off"},
            {"value": 1, "label": "1 — Least energy efficient"},
            *(
                {"value": value, "label": str(value)}
                for value in range(2, 9)
            ),
            {"value": 9, "label": "9 — Most energy efficient"},
            {"value": 10, "label": "10 — Vacation mode (optional SGD support)"},
        ],
    }


def normalize_schedule_name(value: str) -> str:
    """Return a safe CSV filename without allowing directory traversal."""
    name = value.strip()
    if name.lower().endswith(".csv"):
        name = name[:-4]
    if not SAFE_SCHEDULE_NAME.fullmatch(name):
        raise ValueError(
            "schedule name must be 1-80 letters, numbers, underscores, or hyphens"
        )
    return f"{name}.csv"


def _canonical_rows(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("schedule must contain at least one row")
    rows: list[dict[str, str]] = []
    for index, source in enumerate(value, start=1):
        if not isinstance(source, dict):
            raise ValueError(f"row {index} must be an object")
        unexpected = sorted(set(source).difference(DRAW_EXTENDED_SCHEDULE_COLUMNS))
        if unexpected:
            raise ValueError(f"row {index} contains unknown fields: {unexpected}")
        rows.append(
            {
                column: "" if source.get(column) is None else str(source.get(column, ""))
                for column in DRAW_EXTENDED_SCHEDULE_COLUMNS
            }
        )
    return rows


def derive_rows(value: Any) -> list[dict[str, str]]:
    """Derive technical canonical fields from each user-selected action."""
    rows = _canonical_rows(value)
    action_counts: Counter[str] = Counter()
    metadata = {item["action"]: item for item in editor_metadata()["actions"]}
    for row in rows:
        action = row["action"].strip().lower()
        details = metadata.get(action)
        if details is None:
            continue
        action_counts[action] += 1
        row["action"] = action
        row["event_type"] = details["event_type"]
        row["event_id"] = (
            "test_end" if action == "end" else f"{action}_{action_counts[action]}"
        )
        row["expected_operational_states"] = "|".join(
            str(state) for state in details["expected_operational_states"]
        )
        if row["event_duration_minutes"].strip().lower() == MAX_DURATION:
            row["event_duration_minutes"] = MAX_DURATION
    return rows


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=DRAW_EXTENDED_SCHEDULE_COLUMNS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def validate_rows(value: Any) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Validate browser rows through the existing authoritative CSV parser."""
    rows = derive_rows(value)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", suffix=".csv", delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            writer = csv.DictWriter(
                handle, fieldnames=DRAW_EXTENDED_SCHEDULE_COLUMNS, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)
        events = load_schedule(temporary_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    summary = {
        "enabled_events": len(events),
        "cta_events": sum(event.event_type == "cta" for event in events),
        "water_draws": sum(event.event_type == "water_draw" for event in events),
        "duration_seconds": max((event.offset_seconds for event in events), default=0),
    }
    return rows, summary


def save_schedule(
    directory: Path, name: str, value: Any
) -> tuple[Path, dict[str, int]]:
    """Validate and atomically save one canonical GUI-authored schedule."""
    filename = normalize_schedule_name(name)
    rows, summary = validate_rows(value)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / filename
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=directory,
            prefix=f".{filename}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
        _write_rows(temporary_path, rows)
        load_schedule(temporary_path)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return destination, summary


def load_schedule_rows(path: Path) -> list[dict[str, str]]:
    load_schedule(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def schedule_uses_water(path: Path) -> bool:
    """Return whether an already-saved schedule requires water preflight."""
    return any(event.event_type == "water_draw" for event in load_schedule(path))


class ScheduleGuiHandler(BaseHTTPRequestHandler):
    schedule_directory = DEFAULT_SCHEDULE_DIRECTORY
    editor_path = EDITOR_PATH
    hostname = socket.gethostname()
    station_suffix = ""
    preflight_lock = threading.Lock()
    wh_information_lock = threading.Lock()
    run_lock = threading.Lock()
    run_directory = DEFAULT_RUN_DIRECTORY
    preflight_receipts: dict[str, float] = {}

    def _record_http_activity(self) -> None:
        self.server.last_http_activity = time.monotonic()

    def _json(self, status: HTTPStatus, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _request_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if not 0 < length <= MAX_REQUEST_BYTES:
            raise ValueError("request body is empty or too large")
        try:
            value = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def _stream_preflight(self, filename: str) -> None:
        friendly_schedule_name(filename, self.station_suffix)
        path = self.schedule_directory / normalize_schedule_name(filename)
        if not path.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "schedule not found"})
            return
        if not self.preflight_lock.acquire(blocking=False):
            self._json(
                HTTPStatus.CONFLICT,
                {"error": "another hardware preflight is already running"},
            )
            return
        try:
            water = schedule_uses_water(path)
            arguments = ["--schedule", str(path)]
            if water:
                arguments.insert(0, "--water")
            preflight_args = build_preflight_parser().parse_args(arguments)

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

            def send(payload: dict[str, Any]) -> None:
                self.wfile.write((json.dumps(payload) + "\n").encode("utf-8"))
                self.wfile.flush()

            try:
                send({"type": "start", "schedule": filename, "water": water})

                def report(check: PreflightCheck) -> None:
                    status = "PASS" if check.passed else "FAIL"
                    print(f"PREFLIGHT_{status} {check.name}: {check.details}")
                    send(
                        {
                            "type": "check",
                            "name": check.name,
                            "passed": check.passed,
                            "details": check.details,
                        }
                    )

                checks = run_preflight(preflight_args, on_check=report)
                failures = sum(not check.passed for check in checks)
                print(
                    f"PREFLIGHT_SUMMARY passed={len(checks) - failures} "
                    f"failed={failures} water={str(water).lower()}"
                )
                send(
                    {
                        "type": "summary",
                        "passed": len(checks) - failures,
                        "failed": failures,
                        "water": water,
                    }
                )
                if failures == 0:
                    self.preflight_receipts[filename] = time.monotonic()
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as exc:
                send({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
        finally:
            self.preflight_lock.release()

    def do_GET(self) -> None:
        self._record_http_activity()
        if self.path == "/":
            body = self.editor_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/schedules":
            self._json(
                HTTPStatus.OK,
                {
                    "schedules": station_schedule_choices(
                        self.schedule_directory, self.station_suffix
                    )
                },
            )
            return
        if self.path == "/api/metadata":
            self._json(HTTPStatus.OK, editor_metadata(self.hostname))
            return
        if self.path == "/api/runs/current":
            self._json(HTTPStatus.OK, {"run": current_run(self.run_directory)})
            return
        prefix = "/api/schedules/"
        if self.path.startswith(prefix):
            try:
                requested = unquote(self.path[len(prefix) :])
                friendly_schedule_name(requested, self.station_suffix)
                filename = normalize_schedule_name(requested)
                path = self.schedule_directory / filename
                self._json(
                    HTTPStatus.OK,
                    {
                        "name": filename,
                        "display_name": friendly_schedule_name(
                            filename, self.station_suffix
                        ),
                        "rows": load_schedule_rows(path),
                    },
                )
            except FileNotFoundError:
                self._json(HTTPStatus.NOT_FOUND, {"error": "schedule not found"})
            except (OSError, ValueError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        self._record_http_activity()
        try:
            request = self._request_json()
            if self.path == "/api/validate":
                _, summary = validate_rows(request.get("rows"))
                self._json(HTTPStatus.OK, {"valid": True, "summary": summary})
                return
            if self.path == "/api/save":
                destination, summary = save_schedule(
                    self.schedule_directory,
                    station_schedule_filename(
                        str(request.get("name", "")), self.station_suffix
                    ),
                    request.get("rows"),
                )
                self._json(
                    HTTPStatus.OK,
                    {"saved": destination.name, "summary": summary},
                )
                self.preflight_receipts.pop(destination.name, None)
                return
            if self.path == "/api/preflight":
                self._stream_preflight(str(request.get("filename", "")))
                return
            if self.path == "/api/runs":
                filename = str(request.get("filename", ""))
                friendly_schedule_name(filename, self.station_suffix)
                path = self.schedule_directory / normalize_schedule_name(filename)
                receipt = self.preflight_receipts.get(filename)
                if receipt is None or time.monotonic() - receipt > PREFLIGHT_MAX_AGE_SECONDS:
                    raise RuntimeError("preflight must pass within five minutes before starting")
                with self.run_lock:
                    result = launch_run(
                        self.run_directory, path, water=schedule_uses_water(path)
                    )
                self.preflight_receipts.pop(filename, None)
                self._json(HTTPStatus.ACCEPTED, {"run": result})
                return
            if self.path == "/api/runs/current/dismiss":
                with self.run_lock:
                    dismiss_current_run(self.run_directory)
                self._json(HTTPStatus.OK, {"dismissed": True})
                return
            if self.path == "/api/wh-information":
                if not self.wh_information_lock.acquire(blocking=False):
                    self._json(
                        HTTPStatus.CONFLICT,
                        {"error": "a water-heater information request is already running"},
                    )
                    return
                try:
                    self._json(HTTPStatus.OK, read_wh_information())
                finally:
                    self.wh_information_lock.release()
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except ScheduleValidationError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"errors": list(exc.errors)})
        except (OSError, RuntimeError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"SCHEDULE_GUI {self.address_string()} {format % args}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument(
        "--idle-timeout-hours",
        type=positive_hours,
        default=DEFAULT_IDLE_TIMEOUT_HOURS,
        help="exit after this many hours without a GET or POST request",
    )
    parser.add_argument("--run-directory", type=Path, default=DEFAULT_RUN_DIRECTORY)
    parser.add_argument(
        "--schedule-directory", type=Path, default=DEFAULT_SCHEDULE_DIRECTORY
    )
    return parser


def positive_hours(value: str) -> float:
    """Parse a positive hour count, including decimal values."""
    try:
        hours = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive number of hours") from exc
    if not hours > 0 or hours == float("inf"):
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return hours


def serve_until_idle(
    server: ThreadingHTTPServer,
    idle_timeout_seconds: float,
    *,
    monotonic=time.monotonic,
) -> bool:
    """Handle requests until inactivity expires; return True on idle timeout."""
    server.last_http_activity = monotonic()
    while True:
        remaining = idle_timeout_seconds - (
            monotonic() - server.last_http_activity
        )
        if remaining <= 0:
            return True
        server.timeout = min(1.0, remaining)
        server.handle_request()


def main() -> int:
    args = build_parser().parse_args()
    hostname = socket.gethostname()
    station_suffix = station_suffix_from_hostname(hostname)
    handler = type(
        "ConfiguredScheduleGuiHandler",
        (ScheduleGuiHandler,),
        {
            "schedule_directory": args.schedule_directory,
            "hostname": hostname,
            "station_suffix": station_suffix,
            "run_directory": args.run_directory,
        },
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"SCHEDULE_GUI_READY http://{args.host}:{args.port}")
    timed_out = False
    try:
        timed_out = serve_until_idle(
            server, args.idle_timeout_hours * 60 * 60
        )
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    if timed_out:
        print(
            "SCHEDULE_GUI_IDLE_TIMEOUT No GET or POST requests for "
            f"{args.idle_timeout_hours:g} hours"
        )
    print("SCHEDULE_GUI_STOPPED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
