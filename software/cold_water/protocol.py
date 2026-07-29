"""Versioned NDJSON protocol for shared Pi 1 sensor snapshots."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import datetime
from typing import Any

from software.pacific_time import pacific_timestamp
from software.sensors.sensor_reader import SensorSnapshot


PROTOCOL_VERSION = 1
SOURCE_STATION = "WH-station1"


def hello_message(sample_period_seconds: float) -> dict[str, Any]:
    return {
        "message_type": "hello",
        "protocol_version": PROTOCOL_VERSION,
        "source_station": SOURCE_STATION,
        "sample_period_seconds": sample_period_seconds,
        "timestamp_pacific": pacific_timestamp(),
        "status": "ready",
    }


def reading_message(
    snapshot: SensorSnapshot,
    *,
    sequence: int,
) -> dict[str, Any]:
    return {
        "message_type": "reading",
        "protocol_version": PROTOCOL_VERSION,
        "source_station": SOURCE_STATION,
        "sequence": sequence,
        "timestamp_pacific": pacific_timestamp(),
        "status": "ok",
        **asdict(snapshot),
    }


def error_message(*, sequence: int, error: BaseException) -> dict[str, Any]:
    return {
        "message_type": "health",
        "protocol_version": PROTOCOL_VERSION,
        "source_station": SOURCE_STATION,
        "sequence": sequence,
        "timestamp_pacific": pacific_timestamp(),
        "status": "sensor_error",
        "error_type": type(error).__name__,
        "message": str(error),
    }


def encode_message(message: dict[str, Any]) -> bytes:
    return (
        json.dumps(message, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def decode_message(line: bytes | str) -> dict[str, Any]:
    text = line.decode("utf-8") if isinstance(line, bytes) else line
    message = json.loads(text)
    if not isinstance(message, dict):
        raise ValueError("cold-water protocol message must be a JSON object")
    if message.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("unsupported cold-water protocol version")
    if message.get("source_station") != SOURCE_STATION:
        raise ValueError("cold-water message has an unexpected source station")
    return message


def message_age_seconds(
    message: dict[str, Any],
    *,
    now: datetime,
) -> float:
    timestamp = datetime.fromisoformat(str(message["timestamp_pacific"]))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("cold-water timestamp must include a UTC offset")
    return (now - timestamp).total_seconds()


def snapshot_from_reading(message: dict[str, Any]) -> SensorSnapshot:
    if message.get("message_type") != "reading" or message.get("status") != "ok":
        raise RuntimeError(
            f"cold-water service is not healthy: {message.get('status')}"
        )
    integer_fields = (
        "hot_raw_counts",
        "cold_raw_counts",
        "flow_raw_counts",
        "ambient_raw_counts",
    )
    float_fields = (
        "hot_temp_c",
        "hot_temp_f",
        "cold_temp_c",
        "cold_temp_f",
        "ambient_temp_c",
        "ambient_temp_f",
        "flow_gpm",
    )
    values: dict[str, int | float] = {}
    for field in integer_fields:
        values[field] = int(message[field])
    for field in float_fields:
        value = float(message[field])
        if not math.isfinite(value):
            raise ValueError(f"cold-water field {field} must be finite")
        values[field] = value
    return SensorSnapshot(
        **values,
        cold_source_station=str(message["source_station"]),
        cold_source_timestamp_pacific=str(message["timestamp_pacific"]),
    )
