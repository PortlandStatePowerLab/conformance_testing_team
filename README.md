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
1 through 2150, or `unknown`. The compiler rounds a numeric duration up to the
next CTA-2045 duration-byte value so the encoded event does not expire early.

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

Each hardware run creates a unique directory under
`saved_data/conformance_runs/`. It contains the archived master and generated
CTA schedules, controller event and commodity CSVs, power data, water-draw CSVs,
orchestrator events, and process logs.
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
