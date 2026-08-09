#!/usr/bin/env python3
"""Serve a small local browser editor for canonical schedule CSV files."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

try:
    from .schedule_parser import SCHEDULE_COLUMNS, ScheduleValidationError, load_schedule
except ImportError:
    from schedule_parser import SCHEDULE_COLUMNS, ScheduleValidationError, load_schedule


SOFTWARE_DIRECTORY = Path(__file__).resolve().parent
DEFAULT_SCHEDULE_DIRECTORY = SOFTWARE_DIRECTORY / "gui_schedules"
EDITOR_PATH = SOFTWARE_DIRECTORY / "templates" / "schedule_gui.html"
SAFE_SCHEDULE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
MAX_REQUEST_BYTES = 1_000_000


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
        unexpected = sorted(set(source).difference(SCHEDULE_COLUMNS))
        if unexpected:
            raise ValueError(f"row {index} contains unknown fields: {unexpected}")
        rows.append(
            {
                column: "" if source.get(column) is None else str(source.get(column, ""))
                for column in SCHEDULE_COLUMNS
            }
        )
    return rows


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCHEDULE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def validate_rows(value: Any) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Validate browser rows through the existing authoritative CSV parser."""
    rows = _canonical_rows(value)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", suffix=".csv", delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            writer = csv.DictWriter(
                handle, fieldnames=SCHEDULE_COLUMNS, lineterminator="\n"
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


class ScheduleGuiHandler(BaseHTTPRequestHandler):
    schedule_directory = DEFAULT_SCHEDULE_DIRECTORY
    editor_path = EDITOR_PATH

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

    def do_GET(self) -> None:
        if self.path == "/":
            body = self.editor_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/schedules":
            names = []
            if self.schedule_directory.is_dir():
                names = sorted(path.name for path in self.schedule_directory.glob("*.csv"))
            self._json(HTTPStatus.OK, {"schedules": names})
            return
        prefix = "/api/schedules/"
        if self.path.startswith(prefix):
            try:
                filename = normalize_schedule_name(unquote(self.path[len(prefix) :]))
                path = self.schedule_directory / filename
                self._json(
                    HTTPStatus.OK,
                    {"name": filename, "rows": load_schedule_rows(path)},
                )
            except FileNotFoundError:
                self._json(HTTPStatus.NOT_FOUND, {"error": "schedule not found"})
            except (OSError, ValueError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            request = self._request_json()
            if self.path == "/api/validate":
                _, summary = validate_rows(request.get("rows"))
                self._json(HTTPStatus.OK, {"valid": True, "summary": summary})
                return
            if self.path == "/api/save":
                destination, summary = save_schedule(
                    self.schedule_directory,
                    str(request.get("name", "")),
                    request.get("rows"),
                )
                self._json(
                    HTTPStatus.OK,
                    {"saved": destination.name, "summary": summary},
                )
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except ScheduleValidationError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"errors": list(exc.errors)})
        except (OSError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"SCHEDULE_GUI {self.address_string()} {format % args}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument(
        "--schedule-directory", type=Path, default=DEFAULT_SCHEDULE_DIRECTORY
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    handler = type(
        "ConfiguredScheduleGuiHandler",
        (ScheduleGuiHandler,),
        {"schedule_directory": args.schedule_directory},
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"SCHEDULE_GUI_READY http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSCHEDULE_GUI_STOPPED")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
