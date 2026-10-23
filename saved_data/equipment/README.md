# Station equipment and private records

The source of truth on each Pi is `saved_data/private/equipment/WH-stationN.json`.
It contains the full equipment details, persistent random equipment_id,
display_name (HPWH-N), date_added, capacity_gallons, and temperature_setpoint_f.
The GUI reads this full private record so the operator can identify the heater.
Calibration records and their backups are PUBLIC in `saved_data/calibration/`.
They retain all sensor measurements and sensor/reference-instrument details.
The heater manufacturer/model is replaced with equipment_id (also in the power
section). Calibration tools and readers default to this public directory.
Preflight compares the power calibration's equipment_id against the private
heater's ID, falling back to public equipment when no private record exists.
The entire private directory is ignored by Git; public calibration is tracked.

The files in `saved_data/equipment/` are generated public records. They contain
only equipment_id, display_name, date_added, capacity_gallons, and
temperature_setpoint_f. Never edit these copies directly: edit the private record.
The GUI refreshes the matching public record when loading equipment, and the
runner refreshes it before writing the same anonymous record to a new run.
To refresh all public records manually, from the repository directory run:

```sh
python -m software.station.equipment_metadata
```

Keep equipment_id unchanged across runs. Replacing the physical heater requires
a new random UUID-based ID; do not derive it from manufacturer/model/serial number.
The original date_added is the registration date and capacity_gallons is nominal
capacity. Result folders remain WH-N; plot/report equipment labels use HPWH-N.

Run station_calibration.json snapshots contain only approved calibration fields
and the run's anonymous ID/name. Measurement values, dates, and reference-device
details remain available. Update software/station/calibration_metadata.py when
introducing new calibration fields that should be archived.

## Updating existing Pis

Preserve each Pi's own records BEFORE pulling this update: Git will replace the
old full equipment records with anonymous copies. Preserve each Pi's latest
calibration separately as well; tracked calibration changes can conflict on pull. Stop running tests/calibration tools during this migration.
From the existing conformance_testing_team checkout on each Pi, run:

```sh
mkdir -p saved_data/private/equipment saved_data/private/calibration-backup
cp -an saved_data/equipment/WH-station*.json saved_data/private/equipment/
cp -an saved_data/calibration/WH-station* saved_data/private/calibration-backup/
```

These commands preserve existing private copies rather than overwrite them.
Check the private copies contain the current Pi's full equipment record and its
latest calibration, and keep a separate backup before updating. Public calibration
files must retain that Pi's measurement values: remove heater identity from the
root/power section and replace it with the matching equipment_id. Preserve
manufacturer/model fields describing sensors in the temperature/flow sections. Do not commit
or stage that directory using the old checkout: its ignore rule arrives with
this update. After updating, regenerate public records with the command above.
If an older private equipment record lacks equipment_id or display_name, copy
those two fields from its matching updated public record, preserving the shared
ID. Retain the Pi's own setpoint, calibration, and descriptive equipment data.

A fresh clone contains no private records. Provision them from a trusted local
backup before using the GUI. Public calibration remains available in the clone,
but verify its equipment_id and coefficients belong to the installed setup;
anonymous public equipment records cannot reconstruct the heater's private details.

This change does not rewrite Git history or sanitize previously saved runs/plots.

## CTA device-information output

Rebuild the CTA controller when deploying this change. The public
cta_device_information.csv contains equipment_id plus protocol response,
CTA version, device type, and capability fields. Vendor, device revision,
model/serial fields (including support flags), and all firmware fields are omitted.
The Excel Device Information sheet applies the same allowlist to older CSVs too.

The runner passes CTA_EQUIPMENT_ID from the archived equipment record and sets
CTA_PRIVATE_DEVICE_INFO_LOG_PATH under saved_data/private/cta_information/.
That ignored file retains the previous diagnostic columns (serial remains redacted).
A standalone controller launch leaves equipment_id blank unless CTA_EQUIPMENT_ID
is supplied, and writes no private diagnostic CSV unless its path is supplied.

This filtering covers device-information CSVs and their report sheet. Raw CTA
message logs require a separate review before claiming all run artifacts are anonymous.
