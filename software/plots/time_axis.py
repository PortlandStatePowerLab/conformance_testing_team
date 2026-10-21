"""Shared duration-aware clock ticks for run plots."""

from __future__ import annotations

from datetime import datetime

import matplotlib.dates as mdates
from matplotlib.ticker import FixedLocator


TICK_INTERVALS_MINUTES = (5, 10, 15, 20, 30, 60, 120, 180, 240, 360, 720, 1440)


def time_tick_interval_minutes(
    start: datetime,
    end: datetime,
    *,
    maximum_labels: int = 9,
) -> int:
    """Choose a natural interval that yields roughly seven to nine labels."""
    if maximum_labels < 2:
        raise ValueError("maximum_labels must be at least 2")
    duration_minutes = max((end - start).total_seconds() / 60.0, 0.0)
    minimum_interval = duration_minutes / (maximum_labels - 1)
    for interval in TICK_INTERVALS_MINUTES:
        if interval >= minimum_interval:
            return interval
    days = max(1, int(minimum_interval // 1440) + 1)
    return days * 1440


def apply_clock_ticks(axis, start: datetime, end: datetime) -> int:
    """Apply naturally aligned Pacific clock ticks and return their interval."""
    interval = time_tick_interval_minutes(start, end)
    if interval < 60:
        locator = mdates.MinuteLocator(interval=interval)
    elif interval % 60 == 0 and interval < 1440:
        locator = mdates.HourLocator(interval=interval // 60)
    else:
        locator = mdates.DayLocator(interval=max(1, interval // 1440))
    axis.xaxis.set_major_locator(locator)
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%I:%M %p"))
    return interval


def apply_even_clock_ticks(axis, start: datetime, end: datetime, *, count: int = 6) -> None:
    """Apply an exact number of evenly distributed clock labels."""
    if count < 2:
        raise ValueError("count must be at least 2")
    start_number = mdates.date2num(start)
    end_number = mdates.date2num(end)
    step = (end_number - start_number) / (count - 1)
    axis.xaxis.set_major_locator(
        FixedLocator([start_number + index * step for index in range(count)])
    )
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%I:%M %p"))
