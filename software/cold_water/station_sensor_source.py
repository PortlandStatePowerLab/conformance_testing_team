"""Build station-aware sensor readers with one Pi 1 MAX1238 owner."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from software.station.station_adc_builder import build_station_adc
from software.cold_water.client import (
    DEFAULT_REMOTE_HOST,
    DEFAULT_REMOTE_USER,
    DEFAULT_SOCKET_PATH,
    LocalSnapshotClient,
    SnapshotClient,
    SshSnapshotClient,
)
from software.exception_notes import add_exception_note
from software.sensors.sensor_reader import SensorReader, SensorSnapshot
from software.station.station_identity import station_number


class SensorSnapshotReader(Protocol):
    def get_sensor_snapshot(self) -> SensorSnapshot: ...

class CloseableResource(Protocol):
    """Define the cleanup operation required or an owned resource."""

    def close(self) -> None:
        """Release the owned resource."""
        ...

class CompositeSensorReader:
    """Combine local station sensors with Pi 1's shared cold measurement."""

    def __init__(
        self,
        local_reader: SensorSnapshotReader,
        pi1_reader: SnapshotClient,
    ) -> None:
        self._local_reader = local_reader
        self._pi1_reader = pi1_reader

    def get_sensor_snapshot(self) -> SensorSnapshot:
        local = self._local_reader.get_sensor_snapshot()
        pi1 = self._pi1_reader.get_sensor_snapshot()
        return replace(
            local,
            cold_raw_counts=pi1.cold_raw_counts,
            cold_temp_c=pi1.cold_temp_c,
            cold_temp_f=pi1.cold_temp_f,
            cold_source_station=pi1.cold_source_station,
            cold_source_timestamp_pacific=(
                pi1.cold_source_timestamp_pacific
            ),
        )


@dataclass
class StationSensorSession:
    """Own a constructed station reader and all resources behind it."""

    reader: SensorSnapshotReader
    remote_client: SnapshotClient
    adc: CloseableResource | None = None

    def close(self) -> None:
        first_error: BaseException | None = None
        try:
            self.remote_client.close()
        except BaseException as error:
            first_error = error
        if self.adc is not None:
            try:
                self.adc.close()
            except BaseException as error:
                if first_error is None:
                    first_error = error
                else:
                    add_exception_note(
                        first_error, f"ADC close also failed: {error!r}"
                    )
        if first_error is not None:
            raise first_error


def build_station_sensor_session(
    *,
    configuration_path: Path | None = None,
    active_station_number: int | None = None,
    socket_path: Path = DEFAULT_SOCKET_PATH,
    remote_host: str | None = None,
    remote_user: str | None = None,
    identity_file: Path | None = None,
) -> StationSensorSession:
    """Build the correct local/remote sensor composition for station 1-4."""
    number = active_station_number or station_number()
    if number == 1:
        client = LocalSnapshotClient(socket_path)
        return StationSensorSession(reader=client, remote_client=client)
    if number not in (2, 3, 4):
        raise ValueError(f"unsupported station number: {number}")

    client = SshSnapshotClient(
        host=remote_host
        or os.environ.get("COLD_WATER_PI1_HOST", DEFAULT_REMOTE_HOST),
        user=remote_user
        or os.environ.get("COLD_WATER_SSH_USER", DEFAULT_REMOTE_USER),
        identity_file=identity_file
        or (
            Path(os.environ["COLD_WATER_SSH_IDENTITY_FILE"])
            if os.environ.get("COLD_WATER_SSH_IDENTITY_FILE")
            else None
        ),
    )
    adc = None
    try:
        adc = build_station_adc()
        local_reader = SensorReader(adc, configuration_path=configuration_path)
        reader = CompositeSensorReader(local_reader, client)
        return StationSensorSession(
            reader=reader,
            remote_client=client,
            adc=adc,
        )
    except BaseException:
        client.close()
        if adc is not None:
            adc.close()
        raise
