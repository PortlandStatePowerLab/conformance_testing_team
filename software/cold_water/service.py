"""Single-owner, on-demand Pi 1 MAX1238 snapshot service."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import stat
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from software.station.station_adc_builder import build_station_adc
from software.cold_water.client import DEFAULT_SOCKET_PATH
from software.cold_water.protocol import (
    encode_message,
    error_message,
    hello_message,
    reading_message,
)
from software.sensors.sensor_reader import SensorReader
from software.station.station_identity import station_number


DEFAULT_SAMPLE_PERIOD_SECONDS = 0.5
DEFAULT_IDLE_TIMEOUT_SECONDS = 5.0
SYSTEMD_LISTEN_FD = 3


def systemd_listen_socket() -> socket.socket | None:
    """Return systemd's single inherited socket, when socket-activated."""
    if int(os.environ.get("LISTEN_PID", "0")) != os.getpid():
        return None
    if int(os.environ.get("LISTEN_FDS", "0")) != 1:
        return None
    inherited = socket.fromfd(
        SYSTEMD_LISTEN_FD,
        socket.AF_UNIX,
        socket.SOCK_STREAM,
    )
    inherited.set_inheritable(False)
    return inherited


def create_listen_socket(path: Path) -> socket.socket:
    """Create a local development socket when systemd did not provide one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not stat.S_ISSOCK(path.stat().st_mode):
            raise FileExistsError(
                f"refusing to replace non-socket path: {path}"
            )
        path.unlink()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen()
    return listener


class SnapshotService:
    """Read one ADC and broadcast each complete snapshot to all clients."""

    def __init__(
        self,
        listener: socket.socket,
        sensor_reader,
        *,
        sample_period_seconds: float = DEFAULT_SAMPLE_PERIOD_SECONDS,
        idle_timeout_seconds: float = DEFAULT_IDLE_TIMEOUT_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._listener = listener
        self._sensor_reader = sensor_reader
        self._sample_period_seconds = sample_period_seconds
        self._idle_timeout_seconds = idle_timeout_seconds
        self._monotonic = monotonic
        self._clients: set[socket.socket] = set()
        self._clients_lock = threading.Lock()
        self._stop = threading.Event()
        self._ever_had_client = False
        self._idle_since: float | None = None
        self._sequence = 0

    def request_stop(self) -> None:
        self._stop.set()

    def _add_client(self, client: socket.socket) -> None:
        client.settimeout(1.0)
        client.sendall(encode_message(hello_message(self._sample_period_seconds)))
        with self._clients_lock:
            self._clients.add(client)
            self._ever_had_client = True
            self._idle_since = None

    def _remove_client(self, client: socket.socket) -> None:
        with self._clients_lock:
            self._clients.discard(client)
            if not self._clients and self._ever_had_client:
                self._idle_since = self._monotonic()
        try:
            client.close()
        except OSError:
            pass

    def _broadcast(self, payload: bytes) -> None:
        with self._clients_lock:
            clients = tuple(self._clients)
        for client in clients:
            try:
                client.sendall(payload)
            except OSError:
                self._remove_client(client)

    def _sample(self) -> None:
        while not self._stop.is_set():
            self._sequence += 1
            try:
                snapshot = self._sensor_reader.get_sensor_snapshot()
                message = reading_message(snapshot, sequence=self._sequence)
            except BaseException as error:
                message = error_message(sequence=self._sequence, error=error)
            self._broadcast(encode_message(message))
            self._stop.wait(self._sample_period_seconds)

    def _idle_expired(self) -> bool:
        with self._clients_lock:
            idle_since = self._idle_since
        return (
            idle_since is not None
            and self._monotonic() - idle_since >= self._idle_timeout_seconds
        )

    def run(self) -> None:
        self._listener.settimeout(0.2)
        sampler = threading.Thread(
            target=self._sample,
            name="pi1-sensor-acquisition",
            daemon=True,
        )
        sampler.start()
        try:
            while not self._stop.is_set() and not self._idle_expired():
                try:
                    client, _ = self._listener.accept()
                except socket.timeout:
                    continue
                self._add_client(client)
        finally:
            self._stop.set()
            sampler.join(timeout=max(2.0, self._sample_period_seconds * 2))
            with self._clients_lock:
                clients = tuple(self._clients)
                self._clients.clear()
            for client in clients:
                try:
                    client.close()
                except OSError:
                    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket-path", type=Path, default=DEFAULT_SOCKET_PATH)
    parser.add_argument(
        "--sample-period-seconds",
        type=float,
        default=DEFAULT_SAMPLE_PERIOD_SECONDS,
    )
    parser.add_argument(
        "--idle-timeout-seconds",
        type=float,
        default=DEFAULT_IDLE_TIMEOUT_SECONDS,
    )
    parser.add_argument("--sensor-configuration", type=Path)
    parser.add_argument(
        "--allow-nonstation-host",
        action="store_true",
        help="development only; skip the WH-station1 hostname requirement",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.sample_period_seconds <= 0 or args.idle_timeout_seconds <= 0:
        raise SystemExit("sample and idle durations must be greater than zero")
    if not args.allow_nonstation_host and station_number() != 1:
        raise SystemExit("cold-water snapshot service may run only on WH-station1")

    inherited = systemd_listen_socket()
    listener = inherited or create_listen_socket(args.socket_path)
    adc = build_station_adc()
    service = SnapshotService(
        listener,
        SensorReader(adc, configuration_path=args.sensor_configuration),
        sample_period_seconds=args.sample_period_seconds,
        idle_timeout_seconds=args.idle_timeout_seconds,
    )

    def stop_handler(signum: int, frame: object) -> None:
        del signum, frame
        service.request_stop()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    try:
        service.run()
    finally:
        listener.close()
        adc.close()
        if inherited is None and args.socket_path.exists():
            args.socket_path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
