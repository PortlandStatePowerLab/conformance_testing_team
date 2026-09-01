# GUI schedules

Schedules saved by the browser GUI are written here as canonical CSV files.
They are valid inputs to `make validate`, `make preflight`, `make run`, and
their water-enabled variants.

This directory is intentionally tracked so useful test schedules can be
reviewed and shared through Git. Saving a schedule does not automatically
commit or push it; use the normal Git review, commit, and push workflow.

The GUI stores schedules as `<test_name>.csv`. Every water-heater station can
see and run the same schedules after normal Git synchronization. A schedule
describes the test procedure; station-specific equipment, logs, and results
remain separate.

Saving an existing name updates the shared definition for every station. When
two procedures differ logically, preserve both with descriptive variant names
instead of adding a water-heater station suffix.
