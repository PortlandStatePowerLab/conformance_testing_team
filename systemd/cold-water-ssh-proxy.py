#!/usr/bin/python3
"""Restricted SSH proxy for the local cold-water Unix socket."""

import socket
import sys


SOCKET_PATH = "/run/cold-water/cold-water.sock"


def main() -> int:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(SOCKET_PATH)
        while True:
            payload = connection.recv(65536)
            if not payload:
                return 0
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()


if __name__ == "__main__":
    raise SystemExit(main())
