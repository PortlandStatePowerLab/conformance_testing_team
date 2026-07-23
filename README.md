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

The runner monitors child processes and stops the test if a required process
exits unexpectedly or a water draw fails. During shutdown it closes any active
water draw, sends `z` to return the water heater to normal operation, and stops
the power monitor last.
