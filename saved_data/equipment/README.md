# Station equipment

The GUI selects the JSON file matching the Raspberry Pi hostname. The hostname
remains the operational station identity, and result folders remain WH-1, WH-2, etc.

Each physical heater has a persistent random `equipment_id` and a public
`display_name` such as HPWH-1. Keep the ID unchanged across runs; assign a new
random UUID-based ID when replacing the physical heater. Do not derive it from
manufacturer, model, or serial number.

Run equipment.json snapshots contain only `equipment_id`, `display_name`,
`date_added`, and `capacity_gallons`. Plots and reports use the display name.
The date_added field is the original registration date, and capacity_gallons
is the nominal tank capacity. Full station records retain operational settings
and identifying details for local use; temperature-drop tests read their setpoint
from the station record rather than the public snapshot.

These full station records contain identifying information. Publishing only the
run snapshot does not remove existing equipment files or Git history.

Run station_calibration.json snapshots export only known calibration fields and
include equipment_id/display_name from the run's equipment.json when available.
Heater manufacturer/model, other private fields, and unknown sections are omitted.
Local calibration files remain complete for preflight equipment checks. When
adding calibration fields, update software/station/calibration_metadata.py to
include any new measurement fields that should be archived.
