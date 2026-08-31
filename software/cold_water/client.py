"""Local and restricted-SSH clients for the Pi 1 snapshot service."""

from __future__ import annotations

import argparse
import os
import queue
import socket
import subprocess
import sys
import threading
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Protocol, cast

from software.cold_water.protocol import (
    decode_message,
    message_age_seconds,
    snapshot_from_reading,
)
from software.sensors import SensorSnapshot
from software.helpers import _unix_socket_family


DEFAULT_SOCKET_PATH = Path("/run/cold-water/cold-water.sock")
DEFAULT_REMOTE_HOST = "WH-station1"
DEFAULT_REMOTE_USER = "coldwater"
DEFAULT_READING_TIMEOUT_SECONDS = 2.0
DEFAULT_MAX_READING_AGE_SECONDS = 2.0


class SnapshotClient(Protocol):
    def get_sensor_snapshot(self) -> SensorSnapshot: ...

    def close(self) -> None: ...


class _StreamSnapshotClient:
    """Validate snapshots received from one persistent NDJSON stream."""

    def __init__(
        self,
        stream: BinaryIO,
        *,
        reading_timeout_seconds: float = DEFAULT_READING_TIMEOUT_SECONDS,
        max_reading_age_seconds: float = DEFAULT_MAX_READING_AGE_SECONDS,
    ) -> None:
        self._stream = stream
        self._reading_timeout_seconds = reading_timeout_seconds
        self._max_reading_age_seconds = max_reading_age_seconds
        self._messages: queue.Queue[dict | BaseException | None] = queue.Queue()
        self._last_sequence = -1
        self._closed = False
        self._reader = threading.Thread(
            target=self._read_messages,
            name="cold-water-stream-reader",
            daemon=True,
        )
        self._reader.start()

    def _read_messages(self) -> None:
        try:
            for line in self._stream:
                if line.strip():
                    self._messages.put(decode_message(line))
        except BaseException as error:
            self._messages.put(error)
        finally:
            self._messages.put(None)

    def get_sensor_snapshot(self) -> SensorSnapshot:
        if self._closed:
            raise RuntimeError("cold-water snapshot client is closed")
        while True:
            try:
                item = self._messages.get(timeout=self._reading_timeout_seconds)
            except queue.Empty as error:
                raise TimeoutError("cold-water reading timed out") from error
            batch = [item]
            while True:
                try:
                    batch.append(self._messages.get_nowait())
                except queue.Empty:
                    break

            newest_reading: dict | None = None
            for queued_item in batch:
                if queued_item is None:
                    raise ConnectionError("cold-water stream closed")
                if isinstance(queued_item, BaseException):
                    raise ConnectionError("cold-water stream failed") from queued_item
                if queued_item.get("message_type") == "hello":
                    continue
                if queued_item.get("message_type") != "reading":
                    raise RuntimeError(
                        f"cold-water service status: {queued_item.get('status')}"
                    )
                newest_reading = queued_item
            if newest_reading is None:
                continue

            sequence = int(newest_reading["sequence"])
            if sequence <= self._last_sequence:
                raise RuntimeError("cold-water sequence did not advance")
            age = message_age_seconds(
                newest_reading,
                now=datetime.now(timezone.utc),
            )
            if age < -1.0 or age > self._max_reading_age_seconds:
                raise RuntimeError(
                    f"cold-water reading is stale or clock-skewed: age={age:.3f}s"
                )
            self._last_sequence = sequence
            return snapshot_from_reading(newest_reading)

    def close(self) -> None:
        self._closed = True

    def _close_stream(self) -> None:
        try:
            self._stream.close()
        except BaseException:
            pass
        self._reader.join(timeout=1.0)


class LocalSnapshotClient(_StreamSnapshotClient):
    """Consume complete Pi 1 snapshots through its local Unix socket."""

    def __init__(
        self,
        socket_path: Path = DEFAULT_SOCKET_PATH,
        **kwargs,
    ) -> None:
        self._socket = socket.socket(_unix_socket_family(), socket.SOCK_STREAM)
        try:
            self._socket.connect(str(socket_path))
            stream = cast(BinaryIO, self._socket.makefile("rb"))
            super().__init__(stream, **kwargs)
        except BaseException:
            self._socket.close()
            raise

    def close(self) -> None:
        super().close()
        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._close_stream()
        self._socket.close()


class SshSnapshotClient(_StreamSnapshotClient):
    """Consume Pi 1 snapshots through a restricted encrypted SSH command."""

    def __init__(
        self,
        *,
        host: str = DEFAULT_REMOTE_HOST,
        user: str = DEFAULT_REMOTE_USER,
        identity_file: Path | None = None,
        **kwargs,
    ) -> None:
        command = [
            "ssh",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ServerAliveInterval=2",
            "-o",
            "ServerAliveCountMax=3",
        ]
        if identity_file is not None:
            command.extend(["-i", str(identity_file)])
        command.extend([f"{user}@{host}", "stream"])
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=None,
        )
        if self._process.stdout is None:
            self._process.terminate()
            raise RuntimeError("SSH did not provide a snapshot stream")
        super().__init__(cast(BinaryIO, self._process.stdout, **kwargs))

    def close(self) -> None:
        super().close()
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=3.0)
        self._close_stream()


def proxy_local_stream(
    socket_path: Path = DEFAULT_SOCKET_PATH,
    *,
    output: BinaryIO | None = None,
) -> int:
    """Forward the local Unix stream to stdout for a forced SSH command."""
    destination = output or sys.stdout.buffer
    with socket.socket(_unix_socket_family(), socket.SOCK_STREAM) as connection:
        connection.connect(str(socket_path))
        while True:
            data = connection.recv(65536)
            if not data:
                return 0
            destination.write(data)
            destination.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket-path", type=Path, default=DEFAULT_SOCKET_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    original_command = os.environ.get("SSH_ORIGINAL_COMMAND", "stream").strip()
    if original_command not in ("", "stream"):
        print("Only the cold-water stream command is permitted.", file=sys.stderr)
        return 2
    return proxy_local_stream(args.socket_path)


if __name__ == "__main__":
    raise SystemExit(main())
