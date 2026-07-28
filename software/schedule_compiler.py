#!/usr/bin/env python3
"""Compile the human conformance schedule into CTA controller CSV files."""

from __future__ import annotations

import argparse
import csv
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    from .schedule_parser import GeneratedCtaEvent, generate_cta_events, load_schedule
except ImportError:
    from schedule_parser import GeneratedCtaEvent, generate_cta_events, load_schedule


MACHINE_COLUMNS = ("time", "command", "argument", "event_id", "value", "units")
PREVIEW_COLUMNS = (
    "event_id",
    "scheduled_utc",
    "offset_seconds",
    "action",
    "command_code",
    "duration_byte",
    "requested_duration_seconds",
    "represented_duration_seconds",
    "advanced_duration_minutes",
    "advanced_value",
    "advanced_units",
    "expected_operational_states",
    "generated",
    "prerequisite_for",
)


def parse_test_start(value: str) -> datetime:
    """Parse an ISO-8601 test start and require an explicit UTC offset."""
    normalized = value.strip()
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("test start must be an ISO-8601 date and time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("test start must include a UTC offset or Z")
    if parsed.microsecond:
        raise ValueError("test start must use whole-second precision")
    return parsed


def _atomic_write_csv(
    destination: Path,
    columns: tuple[str, ...],
    rows: Iterable[dict[str, object]],
    *,
    comment_header: bool = False,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            if comment_header:
                handle.write("# " + ",".join(columns) + "\n")
                writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="raise")
            else:
                writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="raise")
                writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _scheduled_time(test_start: datetime, event: GeneratedCtaEvent) -> datetime:
    return datetime.fromtimestamp(
        test_start.timestamp() + event.offset_seconds,
        tz=timezone.utc,
    )


def compile_cta_schedule(
    master_schedule: Path | str,
    *,
    test_start: datetime,
    controller_output: Path | str,
    preview_output: Path | str,
    outside_communication_lead_seconds: int = 15,
) -> list[GeneratedCtaEvent]:
    """Validate and compile one master schedule without starting hardware."""
    if test_start.tzinfo is None or test_start.utcoffset() is None:
        raise ValueError("test_start must be timezone-aware")
    if test_start.microsecond:
        raise ValueError("test_start must use whole-second precision")

    events = load_schedule(master_schedule)
    cta_events = generate_cta_events(
        events,
        outside_communication_lead_seconds=outside_communication_lead_seconds,
    )

    machine_rows: list[dict[str, object]] = []
    preview_rows: list[dict[str, object]] = []
    for event in cta_events:
        scheduled = _scheduled_time(test_start, event)
        machine_rows.append(
            {
                "time": int(scheduled.timestamp()),
                "command": event.command_code,
                "argument": (
                    event.advanced_duration_minutes
                    if event.advanced_duration_minutes is not None
                    else ("" if event.duration_byte is None else event.duration_byte)
                ),
                "event_id": event.event_id,
                "value": "" if event.advanced_value is None else event.advanced_value,
                "units": "" if event.advanced_units is None else event.advanced_units,
            }
        )
        preview_rows.append(
            {
                "event_id": event.event_id,
                "scheduled_utc": scheduled.isoformat(timespec="seconds").replace(
                    "+00:00", "Z"
                ),
                "offset_seconds": event.offset_seconds,
                "action": event.action,
                "command_code": event.command_code,
                "duration_byte": (
                    "" if event.duration_byte is None else event.duration_byte
                ),
                "requested_duration_seconds": (
                    ""
                    if event.requested_duration_seconds is None
                    else event.requested_duration_seconds
                ),
                "represented_duration_seconds": (
                    ""
                    if event.represented_duration_seconds is None
                    else event.represented_duration_seconds
                ),
                "advanced_duration_minutes": (
                    ""
                    if event.advanced_duration_minutes is None
                    else event.advanced_duration_minutes
                ),
                "advanced_value": (
                    "" if event.advanced_value is None else event.advanced_value
                ),
                "advanced_units": (
                    "" if event.advanced_units is None else event.advanced_units
                ),
                "expected_operational_states": "|".join(
                    str(state) for state in event.expected_operational_states
                ),
                "generated": str(event.generated).lower(),
                "prerequisite_for": event.prerequisite_for or "",
            }
        )

    _atomic_write_csv(
        Path(controller_output),
        MACHINE_COLUMNS,
        machine_rows,
        comment_header=True,
    )
    _atomic_write_csv(Path(preview_output), PREVIEW_COLUMNS, preview_rows)
    return cta_events


def main() -> int:
    software_directory = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "master_schedule",
        nargs="?",
        type=Path,
        default=software_directory / "conformance_test_schedule.csv",
    )
    parser.add_argument("--test-start", required=True, type=parse_test_start)
    parser.add_argument("--controller-output", required=True, type=Path)
    parser.add_argument("--preview-output", required=True, type=Path)
    parser.add_argument("--outside-communication-lead-seconds", type=int, default=15)
    args = parser.parse_args()

    try:
        events = compile_cta_schedule(
            args.master_schedule,
            test_start=args.test_start,
            controller_output=args.controller_output,
            preview_output=args.preview_output,
            outside_communication_lead_seconds=args.outside_communication_lead_seconds,
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")

    print(f"CTA controller schedule: {args.controller_output}")
    print(f"CTA schedule preview: {args.preview_output}")
    print(f"CTA events written: {len(events)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
