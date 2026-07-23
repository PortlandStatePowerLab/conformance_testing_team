"""Operations required from a valve used by station workflows."""

from typing import Protocol


class Valve(Protocol):
    """Define the valve operations required by controlled workflows."""

    def open(self) -> None:
        """Command the valve open."""

    def close(self) -> None:
        """Command the valve closed."""
