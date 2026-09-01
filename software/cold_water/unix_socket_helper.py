"""Provide platform-checked Unix-domain socket support for cold-water transport."""

import socket


def _unix_socket_family() -> int:
    """Return the Unix-domain socket family on supported platforms."""
    family = getattr(socket, "AF_UNIX", None)
    if family is None:
        raise RuntimeError(
            "Unix-domain sockets require Linux or another Unix platform"
        )
    return family
