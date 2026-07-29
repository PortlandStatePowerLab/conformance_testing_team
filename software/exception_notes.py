"""Compatibility support for exception notes on Python 3.9 and newer."""


def add_exception_note(error: BaseException, note: str) -> None:
    """Attach a diagnostic note, including on Python versions before 3.11."""
    add_note = getattr(error, "add_note", None)
    if add_note is not None:
        add_note(note)
        return

    notes = getattr(error, "__notes__", None)
    if notes is None:
        notes = []
        error.__notes__ = notes
    notes.append(note)
