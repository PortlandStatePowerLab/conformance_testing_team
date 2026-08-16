# GUI schedules

Schedules saved by the browser GUI are written here as canonical CSV files.
They are valid inputs to `make validate`, `make preflight`, `make run`, and
their water-enabled variants.

This directory is intentionally tracked so useful test schedules can be
reviewed and shared through Git. Saving a schedule does not automatically
commit or push it; use the normal Git review, commit, and push workflow.

The GUI automatically stores schedules as `<test_name>_WH_<number>.csv` and
shows only the schedules matching the station on which it is running. The
station suffix is hidden from the browser's friendly schedule name.
