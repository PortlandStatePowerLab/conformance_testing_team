# Water-Heater Conformance Test Runner

The human-editable test definition is
`software/conformance_test_schedule_main.xlsx`. Running the test runner imports
it into the canonical `software/conformance_test_schedule.csv` before
validation. The importer uses only the Python standard library, so no Excel
package is required on the Raspberry Pi.

Select the action and enter the user-controlled schedule values in the main
worksheet. Python derives `event_id`, `event_type`, and expected operational
states from the action instead of relying on Excel to calculate formulas.
`phase` is optional descriptive information.

For Basic DR commands, `event_duration_minutes` accepts a whole number from
1 through 2150, or `max`. The compiler rounds a numeric duration up to the
next CTA-2045 duration-byte value so the encoded event does not expire early.
For Advanced Load Up, numeric durations are direct minutes and `max` compiles
to the unsigned 16-bit maximum of 65535 minutes. The GUI also offers an optional suggested efficiency:
blank omits the optional payload byte, while values 0 through 10 include it.
Zero means off, 1 is least efficient, 9 is most efficient, and 10 requests
vacation mode (which an SGD is not required to support). Existing XLSX and CSV
schedules without this optional column retain the original 7-byte request.
Beginning with the first CTA command prerequisite, the compiler automatically
refreshes outside communication every 13 minutes 30 seconds for the entire
test, including run-normal periods. The heartbeat stops at test end. These
generated refreshes do not repeat or extend user commands; all user-entered CTA
commands and their 15-second outside-communication prerequisites retain their
scheduled times.

The heartbeat is enabled by default. Disable only the recurring refreshes for
a controlled comparison while retaining every command prerequisite:

```bash
make run-water HEARTBEAT=false
```

`make run` and `make run-water` without the variable use `HEARTBEAT=true`.

All Make commands continue to use the XLSX schedule by default. To validate,
preflight, or run an existing canonical CSV instead, pass the same optional
`SCHEDULE` variable:

```bash
make validate SCHEDULE=software/gui_schedules/my_test.csv
make preflight-water SCHEDULE=software/gui_schedules/my_test.csv
make run-water SCHEDULE=software/gui_schedules/my_test.csv
```

For run targets, the selected CSV is passed to both preflight and the test
runner so the schedule checked is the schedule executed.

Start the local browser schedule editor with:

```bash
make schedule-gui
```

It listens on `127.0.0.1:5000` by default and saves validated canonical CSV
files under `software/gui_schedules`. From another computer, use an SSH tunnel
to the test station and open `http://127.0.0.1:5000` locally. The editor does
not read or modify the XLSX workbook and does not launch hardware tests. After
validating and saving a schedule, the GUI can run the existing hardware
preflight checks. It automatically selects water preflight when the saved
schedule contains an enabled water draw.

The GUI exits after 48 hours without a GET or POST request. Decimal-hour
overrides are supported for shorter sessions or testing; for example,
`python3 -m software.schedule_gui --idle-timeout-hours 0.2` uses a 12-minute
idle timeout.

After a saved schedule passes hardware preflight, the GUI offers a Start Test
review dialog with a cancelable 10-second countdown. The schedule is copied to
a private immutable launch directory before a detached worker starts the test.
Refreshing or closing the browser does not stop that worker; reopening the GUI
restores the current run status. Only one active GUI-launched test is permitted
per station, and preflight approval expires after five minutes.

Validate the schedule without accessing hardware:

```bash
python3 software/conformance_test_runner.py
```

On the Raspberry Pi, check station prerequisites before launching processes:

```bash
make preflight
```

Before enabling scheduled valve output, run the water preflight. It verifies
that the schedule contains a water draw and initializes GPIO17 LOW before
releasing the pin:

```bash
make preflight-water
```

WH-station1 owns the shared cold-water sensor. Its socket-activated service
supports simultaneous tests on all four stations without allowing multiple
processes to own the Pi 1 MAX1238. See
`software/cold_water/README.md` for Pi 1 systemd and restricted-SSH setup.

The repository Makefile provides shorter equivalents:

```bash
make help
make test
make validate
make run
make run-water
```

Use `make run` for hardware tests without water draws. `make run-water`
explicitly enables scheduled valve output.

To import the workbook without invoking the runner:

```bash
python3 software/xlsx_schedule_importer.py \
  software/conformance_test_schedule_main.xlsx \
  software/conformance_test_schedule.csv
```

On the Raspberry Pi, run an integration test while leaving valve output disabled:

```bash
python3 software/conformance_test_runner.py --run-hardware
```

After station safety checks are complete, explicitly enable scheduled valve output:

```bash
python3 software/conformance_test_runner.py \
  --run-hardware \
  --enable-water-output
```

Each hardware run detects `WH-station1` through `WH-station4` from the Pi
hostname and creates a unique directory under
`saved_data/conformance_runs/WH-n/`, where `n` is the station number. It
contains the archived master and generated
CTA schedules, controller event and commodity CSVs, power data, water-draw CSVs,
orchestrator events, process logs, and a human-readable
`conformance_test_report.xlsx` workbook. The workbook is generated when the run
closes and contains Event Timeline, Device Information, Master Schedule, and
Commodity Summary sheets. The detailed source CSV files remain unchanged.
The timeline retains each approximately one-minute operational-state reading.

The `saved_data/conformance_runs/` directory is its own Git repository. After
final reports and plots are generated, a hardware run commits only its
`WH-n/<run-directory>` inside that repository and publishes it to that
repository's `origin/main`. The publisher verifies the nested repository root,
pulls with rebase before each push, and retries concurrent station pushes up to
five times. Git authentication is noninteractive; if a pull, rebase,
authentication, or push fails, the test result remains saved and committed
locally for a later synchronization. Pass `--no-publish-results` to keep a run
local intentionally.

Regenerate the workbook for an existing run with:

```bash
make report RUN_DIRECTORY=saved_data/conformance_runs/WH-1/SCHEDULE_NAME_YYYY_MM_DD_HHMMSS_PDT
```
If the hostname does not identify a configured station, the run falls back to
`saved_data/conformance_runs/`.
Automatic run-directory names and all human-readable recorded timestamps use
Pacific civil time. ISO-8601 fields include `-07:00` during PDT or `-08:00`
during PST; directory and automatic file names include the `PDT` or `PST`
designation.

During a hardware run, the terminal shows a live one-line progress display with
percentage complete, elapsed and remaining time, current phase, next scheduled
event, and final outcome. When standard output is redirected, progress is
written once per minute instead of once per second.

Calculated power-monitor values are written with three digits after the decimal
point. Raw register values are reserved for the diagnostic power-monitor tools
and are not included in conformance-run `power.csv` files. This keeps shared
results concise and within spreadsheet precision limits.
The `timestamp_pacific` field uses the `America/Los_Angeles` timezone and
includes `-07:00` during PDT or `-08:00` during PST; it does not use a trailing
UTC `Z`.

The runner monitors child processes and stops the test if a required process
exits unexpectedly or a water draw fails. During shutdown it closes any active
water draw, sends `z` to return the water heater to normal operation, and stops
the power monitor last.
