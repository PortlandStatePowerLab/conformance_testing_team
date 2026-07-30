"""Laptop-safe tests for shared Pi 1 snapshot service and clients."""

from __future__ import annotations

import socket
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from software.cold_water.client import _StreamSnapshotClient
from software.cold_water.service import SnapshotService
from software.cold_water.station_sensor_source import CompositeSensorReader
from software.cold_water import station_sensor_source
from software.sensors.sensor_reader import SensorSnapshot
from software.station.station_identity import station_number, station_results_directory


def snapshot(*, cold_temp_c: float = 24.0) -> SensorSnapshot:
    return SensorSnapshot(
        hot_raw_counts=100,
        cold_raw_counts=200,
        flow_raw_counts=300,
        ambient_raw_counts=400,
        hot_temp_c=50.0,
        hot_temp_f=122.0,
        cold_temp_c=cold_temp_c,
        cold_temp_f=cold_temp_c * 1.8 + 32.0,
        ambient_temp_c=22.0,
        ambient_temp_f=71.6,
        flow_gpm=3.0,
    )


class ColdWaterServiceTest(unittest.TestCase):
    def test_station_hostname_resolution(self):
        self.assertEqual(station_number("WH-station1"), 1)
        self.assertEqual(station_number("wh-STATION4"), 4)
        with self.assertRaises(ValueError):
            station_number("raspberrypi")

    def test_station_results_directory_uses_water_heater_number(self):
        self.assertEqual(
            station_results_directory(Path("/results"), "WH-station3"),
            Path("/results/WH-3"),
        )
        self.assertEqual(
            station_results_directory(Path("/results"), "unknown-host"),
            Path("/results"),
        )

    def test_composite_replaces_only_cold_fields(self):
        local = Mock()
        remote = Mock()
        local.get_sensor_snapshot.return_value = snapshot(cold_temp_c=99.0)
        remote.get_sensor_snapshot.return_value = snapshot(cold_temp_c=24.5)

        combined = CompositeSensorReader(local, remote).get_sensor_snapshot()

        self.assertEqual(combined.cold_temp_c, 24.5)
        self.assertEqual(combined.cold_raw_counts, 200)
        self.assertEqual(combined.hot_temp_c, 50.0)
        self.assertEqual(combined.flow_gpm, 3.0)

    def test_station1_client_never_constructs_an_adc(self):
        client = Mock()
        with (
            unittest.mock.patch.object(
                station_sensor_source,
                "LocalSnapshotClient",
                return_value=client,
            ),
            unittest.mock.patch.object(
                station_sensor_source,
                "build_max1238",
            ) as build_adc,
        ):
            session = station_sensor_source.build_station_sensor_session(
                active_station_number=1
            )

        self.assertIs(session.reader, client)
        build_adc.assert_not_called()

    def test_station2_combines_one_local_adc_with_remote_cold(self):
        client = Mock()
        adc = Mock()
        local_reader = Mock()
        with (
            unittest.mock.patch.object(
                station_sensor_source,
                "SshSnapshotClient",
                return_value=client,
            ),
            unittest.mock.patch.object(
                station_sensor_source,
                "build_max1238",
                return_value=adc,
            ) as build_adc,
            unittest.mock.patch.object(
                station_sensor_source,
                "SensorReader",
                return_value=local_reader,
            ),
        ):
            session = station_sensor_source.build_station_sensor_session(
                active_station_number=2
            )

        self.assertIsInstance(session.reader, CompositeSensorReader)
        self.assertIs(session.adc, adc)
        build_adc.assert_called_once_with()

    def test_four_clients_share_service_and_last_disconnect_stops_it(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        address = listener.getsockname()
        reader = Mock()
        reader.get_sensor_snapshot.return_value = snapshot()
        service = SnapshotService(
            listener,
            reader,
            sample_period_seconds=0.02,
            idle_timeout_seconds=0.1,
        )
        thread = threading.Thread(target=service.run, daemon=True)
        thread.start()
        client_sockets = [socket.create_connection(address) for _ in range(4)]
        streams = [
            client_socket.makefile("rb")
            for client_socket in client_sockets
        ]
        clients = [
            _StreamSnapshotClient(
                stream,
                reading_timeout_seconds=1.0,
            )
            for stream in streams
        ]
        try:
            for client in clients:
                self.assertEqual(
                    client.get_sensor_snapshot().cold_temp_c,
                    24.0,
                )
            for client, client_socket in zip(clients[:3], client_sockets[:3]):
                client.close()
                client_socket.shutdown(socket.SHUT_RDWR)
                client_socket.close()
            self.assertEqual(clients[3].get_sensor_snapshot().flow_gpm, 3.0)
        finally:
            for client, stream, client_socket in zip(
                clients,
                streams,
                client_sockets,
            ):
                client.close()
                try:
                    client_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                stream.close()
                client_socket.close()

        thread.join(timeout=2.0)
        service.request_stop()
        listener.close()
        self.assertFalse(thread.is_alive())
        self.assertGreaterEqual(reader.get_sensor_snapshot.call_count, 2)


if __name__ == "__main__":
    unittest.main()
