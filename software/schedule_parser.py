#!/usr/bin/env python3
"""Parse and validate a human-editable conformance test schedule.

This module is hardware-independent. It does not start processes, access GPIO
or I2C, or write a CTA-2045 controller schedule.
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCHEDULE_COLUMNS = (
    "enabled",
    "event_id",
    "time_after_start",
    "phase",
    "event_type",
    "action",
    "event_duration",
    "advanced_duration_minutes",
    "advanced_value",
    "advanced_units",
    "expected_operational_states",
    "target_volume_gal",
    "expected_flow_gpm",
    "notes",
)

CTA_ACTION_CODES = {
    "advanced_load_up": "a",
    "load_up": "l",
    "run_normal": "e",
    "shed": "s",
    "critical_peak": "c",
    "grid_emergency": "g",
}
ADVANCED_UNIT_CODES = {
    "1_wh": 0x00,
    "10_wh": 0x01,
    "100_wh": 0x02,
    "1000_wh": 0x03,
}
EVENT_TYPES = {"cta", "water_draw", "test"}
TRUE_VALUES = {"true", "yes", "1"}
FALSE_VALUES = {"false", "no", "0"}
UNKNOWN_DURATION = "unknown"
LONG_DURATION = "longer_than_representable"
OUTSIDE_COMMUNICATION_LEAD_SECONDS = 15
MAX_FINITE_DURATION_BYTE = 0xFE
MAX_FINITE_DURATION_SECONDS = 2 * MAX_FINITE_DURATION_BYTE**2


class ScheduleValidationError(ValueError):
    """Raised when a master schedule cannot be used safely."""

    def __init__(self, errors: Iterable[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("Invalid conformance test schedule:\n- " + "\n- ".join(self.errors))


@dataclass(frozen=True)
class EncodedDuration:
    source: str
    byte_value: int
    requested_seconds: int | None
    represented_seconds: int | None


@dataclass(frozen=True)
class ScheduleEvent:
    enabled: bool
    event_id: str
    offset_seconds: int
    phase: str
    event_type: str
    action: str
    event_duration: EncodedDuration | None
    advanced_duration_minutes: int | None
    advanced_value: int | None
    advanced_units: int | None
    expected_operational_states: tuple[int, ...]
    target_volume_gal: float | None
    expected_flow_gpm: float | None
    notes: str
    source_row: int

    @property
    def expected_draw_seconds(self) -> float | None:
        if self.event_type != "water_draw":
            return None
        if self.target_volume_gal is None or self.expected_flow_gpm is None:
            return None
        return (self.target_volume_gal / self.expected_flow_gpm) * 60.0


@dataclass(frozen=True)
class GeneratedCtaEvent:
    event_id: str
    offset_seconds: int
    action: str
    command_code: str
    duration_byte: int | None
    advanced_duration_minutes: int | None
    advanced_value: int | None
    advanced_units: int | None
    expected_operational_states: tuple[int, ...]
    requested_duration_seconds: int | None
    represented_duration_seconds: int | None
    generated: bool
    prerequisite_for: str | None = None


def parse_elapsed_time(value: str) -> int:
    """Convert HH:MM:SS elapsed time to seconds; hours may exceed 23."""
    parts = value.strip().split(":")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError("must use HH:MM:SS with nonnegative whole numbers")
    hours, minutes, seconds = (int(part) for part in parts)
    if minutes >= 60 or seconds >= 60:
        raise ValueError("minutes and seconds must each be between 00 and 59")
    return hours * 3600 + minutes * 60 + seconds


def encode_event_duration(value: str) -> EncodedDuration:
    """Encode a human-readable CTA Basic DR duration into one byte."""
    normalized = value.strip().lower()
    if normalized == UNKNOWN_DURATION:
        return EncodedDuration(normalized, 0x00, None, None)
    if normalized == LONG_DURATION:
        return EncodedDuration(normalized, 0xFF, None, None)

    requested_seconds = parse_elapsed_time(normalized)
    if requested_seconds <= 0:
        raise ValueError("finite event duration must be greater than zero")
    if requested_seconds > MAX_FINITE_DURATION_SECONDS:
        raise ValueError(
            f"finite duration exceeds {MAX_FINITE_DURATION_SECONDS} seconds; "
            f"use '{LONG_DURATION}' if appropriate"
        )

    byte_value = math.ceil(math.sqrt(requested_seconds / 2.0))
    if not 1 <= byte_value <= MAX_FINITE_DURATION_BYTE:
        raise ValueError("finite event duration cannot be represented")
    represented_seconds = 2 * byte_value**2
    return EncodedDuration(
        normalized,
        byte_value,
        requested_seconds,
        represented_seconds,
    )


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError("must be true/false, yes/no, or 1/0")


def _parse_positive_float(value: str, field_name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{field_name} must be a finite number greater than zero")
    return parsed


def _parse_bounded_integer(value: str, field_name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a base-10 whole number") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return parsed


def _parse_expected_states(value: str) -> tuple[int, ...]:
    if not value.strip():
        return ()
    states = tuple(
        _parse_bounded_integer(part.strip(), "operational state", 0, 255)
        for part in value.split("|")
    )
    if len(set(states)) != len(states):
        raise ValueError("expected_operational_states cannot contain duplicates")
    return states


def _parse_row(row: dict[str, str], row_number: int) -> ScheduleEvent:
    event_type = row["event_type"].strip().lower()
    action = row["action"].strip().lower()
    duration_text = row["event_duration"].strip()
    advanced_duration_text = row["advanced_duration_minutes"].strip()
    advanced_value_text = row["advanced_value"].strip()
    advanced_units_text = row["advanced_units"].strip().lower()
    expected_states_text = row["expected_operational_states"].strip()
    volume_text = row["target_volume_gal"].strip()
    flow_text = row["expected_flow_gpm"].strip()

    if event_type not in EVENT_TYPES:
        raise ValueError(f"event_type must be one of {sorted(EVENT_TYPES)}")

    duration = None
    advanced_duration = None
    advanced_value = None
    advanced_units = None
    expected_states: tuple[int, ...] = ()
    volume = None
    flow = None

    if event_type == "cta":
        if action not in CTA_ACTION_CODES:
            raise ValueError(f"unsupported CTA action '{action}'")
        expected_states = _parse_expected_states(expected_states_text)
        if action == "advanced_load_up":
            if duration_text:
                raise ValueError("advanced_load_up uses advanced_duration_minutes, not event_duration")
            if not advanced_duration_text or not advanced_value_text or not advanced_units_text:
                raise ValueError(
                    "advanced_load_up requires advanced_duration_minutes, advanced_value, and advanced_units"
                )
            advanced_duration = _parse_bounded_integer(
                advanced_duration_text, "advanced_duration_minutes", 1, 0xFFFF
            )
            advanced_value = _parse_bounded_integer(
                advanced_value_text, "advanced_value", 1, 0xFFFE
            )
            if advanced_units_text not in ADVANCED_UNIT_CODES:
                raise ValueError(
                    "advanced_units must be one of " + ", ".join(ADVANCED_UNIT_CODES)
                )
            advanced_units = ADVANCED_UNIT_CODES[advanced_units_text]
        else:
            if not duration_text:
                raise ValueError("Basic DR CTA events require event_duration")
            if advanced_duration_text or advanced_value_text or advanced_units_text:
                raise ValueError("Basic DR CTA events cannot contain advanced load-up values")
            duration = encode_event_duration(duration_text)
        if volume_text or flow_text:
            raise ValueError("CTA events cannot contain water-draw values")
    elif event_type == "water_draw":
        if action != "draw":
            raise ValueError("water_draw action must be 'draw'")
        if duration_text or advanced_duration_text or advanced_value_text or advanced_units_text or expected_states_text:
            raise ValueError("water draws cannot contain CTA argument or expectation values")
        if not volume_text or not flow_text:
            raise ValueError("water draws require target_volume_gal and expected_flow_gpm")
        volume = _parse_positive_float(volume_text, "target_volume_gal")
        flow = _parse_positive_float(flow_text, "expected_flow_gpm")
    else:
        if action != "end":
            raise ValueError("test action must be 'end'")
        if duration_text or advanced_duration_text or advanced_value_text or advanced_units_text or expected_states_text or volume_text or flow_text:
            raise ValueError("test end cannot contain CTA or water-draw values")

    event_id = row["event_id"].strip()
    if not event_id:
        raise ValueError("event_id is required")

    return ScheduleEvent(
        enabled=_parse_bool(row["enabled"]),
        event_id=event_id,
        offset_seconds=parse_elapsed_time(row["time_after_start"]),
        phase=row["phase"].strip(),
        event_type=event_type,
        action=action,
        event_duration=duration,
        advanced_duration_minutes=advanced_duration,
        advanced_value=advanced_value,
        advanced_units=advanced_units,
        expected_operational_states=expected_states,
        target_volume_gal=volume,
        expected_flow_gpm=flow,
        notes=row["notes"].strip(),
        source_row=row_number,
    )


def load_schedule(path: Path | str) -> list[ScheduleEvent]:
    """Load and fully validate a master schedule CSV."""
    schedule_path = Path(path)
    errors: list[str] = []
    events: list[ScheduleEvent] = []

    with schedule_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        actual_columns = tuple(reader.fieldnames or ())
        if actual_columns != SCHEDULE_COLUMNS:
            raise ScheduleValidationError(
                [
                    "CSV columns must exactly match: " + ",".join(SCHEDULE_COLUMNS),
                    "found: " + ",".join(actual_columns),
                ]
            )
        for row_number, row in enumerate(reader, start=2):
            try:
                events.append(_parse_row(row, row_number))
            except (TypeError, ValueError) as exc:
                errors.append(f"row {row_number}: {exc}")

    seen_ids: dict[str, int] = {}
    for event in events:
        if event.event_id in seen_ids:
            errors.append(
                f"row {event.source_row}: duplicate event_id '{event.event_id}' "
                f"(first used on row {seen_ids[event.event_id]})"
            )
        else:
            seen_ids[event.event_id] = event.source_row

    enabled_events = sorted(
        (event for event in events if event.enabled),
        key=lambda event: (event.offset_seconds, event.source_row),
    )
    end_events = [
        event
        for event in enabled_events
        if event.event_type == "test" and event.action == "end"
    ]
    if len(end_events) != 1:
        errors.append("schedule must contain exactly one enabled test end event")
    elif any(event.offset_seconds > end_events[0].offset_seconds for event in enabled_events):
        errors.append("enabled events cannot occur after the test end event")

    draws = [event for event in enabled_events if event.event_type == "water_draw"]
    for current, following in zip(draws, draws[1:]):
        expected_end = current.offset_seconds + (current.expected_draw_seconds or 0.0)
        if expected_end > following.offset_seconds:
            errors.append(
                f"water draws '{current.event_id}' and '{following.event_id}' overlap "
                "at their expected flow rates"
            )

    if errors:
        raise ScheduleValidationError(errors)
    return enabled_events


def generate_cta_events(
    events: Iterable[ScheduleEvent],
    *,
    outside_communication_lead_seconds: int = OUTSIDE_COMMUNICATION_LEAD_SECONDS,
) -> list[GeneratedCtaEvent]:
    """Create an in-memory CTA schedule with automatic communication notices."""
    if outside_communication_lead_seconds < 0:
        raise ValueError("outside communication lead must not be negative")

    generated: list[GeneratedCtaEvent] = []
    for event in events:
        if event.event_type != "cta":
            continue
        generated.append(
            GeneratedCtaEvent(
                event_id=f"auto_outside_comm_for_{event.event_id}",
                offset_seconds=event.offset_seconds - outside_communication_lead_seconds,
                action="outside_communication",
                command_code="o",
                duration_byte=None,
                advanced_duration_minutes=None,
                advanced_value=None,
                advanced_units=None,
                expected_operational_states=(),
                requested_duration_seconds=None,
                represented_duration_seconds=None,
                generated=True,
                prerequisite_for=event.event_id,
            )
        )
        generated.append(
            GeneratedCtaEvent(
                event_id=event.event_id,
                offset_seconds=event.offset_seconds,
                action=event.action,
                command_code=CTA_ACTION_CODES[event.action],
                duration_byte=(
                    event.event_duration.byte_value if event.event_duration else None
                ),
                advanced_duration_minutes=event.advanced_duration_minutes,
                advanced_value=event.advanced_value,
                advanced_units=event.advanced_units,
                expected_operational_states=event.expected_operational_states,
                requested_duration_seconds=(
                    event.event_duration.requested_seconds
                    if event.event_duration
                    else None
                ),
                represented_duration_seconds=(
                    event.event_duration.represented_seconds
                    if event.event_duration
                    else None
                ),
                generated=False,
            )
        )
    return sorted(generated, key=lambda event: (event.offset_seconds, event.generated))


def main() -> int:
    default_schedule = Path(__file__).with_name("conformance_test_schedule.csv")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schedule", nargs="?", type=Path, default=default_schedule)
    args = parser.parse_args()

    try:
        events = load_schedule(args.schedule)
    except (OSError, ScheduleValidationError) as exc:
        parser.exit(1, f"{exc}\n")

    cta_events = generate_cta_events(events)
    print(f"Schedule valid: {args.schedule}")
    print(f"Enabled events: {len(events)}")
    print(f"Generated CTA events (including prerequisites): {len(cta_events)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
