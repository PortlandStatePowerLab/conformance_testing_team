import argparse
import csv
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from unittest.mock import patch

from software.hardware_preflight import PreflightCheck
from software.schedule_gui import (
    derive_rows,
    editor_metadata,
    friendly_schedule_name,
    load_schedule_rows,
    normalize_schedule_name,
    positive_hours,
    save_schedule,
    schedule_uses_water,
    ScheduleGuiHandler,
    serve_until_idle,
    station_schedule_choices,
    station_schedule_filename,
    station_suffix_from_hostname,
    validate_rows,
)
from software.schedule_parser import ScheduleValidationError, load_schedule


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MASTER_SCHEDULE = REPOSITORY_ROOT / "software" / "conformance_test_schedule.csv"


def master_rows():
    with MASTER_SCHEDULE.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class ScheduleGuiTests(unittest.TestCase):
    def test_idle_timeout_accepts_decimal_hours(self):
        self.assertEqual(positive_hours("0.2"), 0.2)
        for invalid in ("0", "-1", "inf", "not-a-number"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(argparse.ArgumentTypeError):
                    positive_hours(invalid)

    def test_idle_server_loop_exits_and_honors_activity_reset(self):
        class Clock:
            value = 0.0

            def __call__(self):
                return self.value

        class Server:
            def __init__(self, clock):
                self.clock = clock
                self.calls = 0
                self.timeout = None

            def handle_request(self):
                self.calls += 1
                self.clock.value += 4.0
                if self.calls == 1:
                    self.last_http_activity = self.clock()

        clock = Clock()
        server = Server(clock)

        self.assertTrue(
            serve_until_idle(server, 10.0, monotonic=clock)
        )
        self.assertEqual(server.calls, 4)
        self.assertLessEqual(server.timeout, 1.0)

    def test_metadata_comes_from_existing_python_definitions(self):
        metadata = editor_metadata("WH-station3")
        actions = {item["action"]: item for item in metadata["actions"]}

        self.assertEqual(actions["load_up"]["event_type"], "cta")
        self.assertEqual(actions["load_up"]["expected_operational_states"], [3, 6])
        self.assertEqual(
            actions["water_draw"]["fields"],
            ["target_volume_gal", "expected_flow_gpm"],
        )
        self.assertIn("100_wh", metadata["advanced_units"])
        self.assertTrue(metadata["hostname"])
        self.assertEqual(metadata["station_suffix"], "WH_3")
        self.assertEqual(
            [item["value"] for item in metadata["advanced_efficiencies"]],
            list(range(11)),
        )

    def test_technical_fields_are_derived_from_action(self):
        source = master_rows()
        for row in source:
            row["event_id"] = "browser value is ignored"
            row["event_type"] = "browser value is ignored"
            row["expected_operational_states"] = "255"

        derived = derive_rows(source)

        self.assertEqual(derived[0]["event_id"], "load_up_1")
        self.assertEqual(derived[0]["event_type"], "cta")
        self.assertEqual(derived[0]["expected_operational_states"], "3|6")
        self.assertEqual(derived[-1]["event_id"], "test_end")
        self.assertEqual(derived[-1]["event_type"], "test")

    def test_existing_canonical_rows_validate_without_gui_rules(self):
        rows, summary = validate_rows(master_rows())

        self.assertEqual(len(rows), summary["enabled_events"])
        self.assertGreater(summary["cta_events"], 0)
        self.assertGreater(summary["water_draws"], 0)

    def test_save_is_canonical_and_loadable_by_existing_parser(self):
        with tempfile.TemporaryDirectory() as directory:
            destination, summary = save_schedule(
                Path(directory), "gui_test", master_rows()
            )

            events = load_schedule(destination)
            loaded_rows = load_schedule_rows(destination)

        self.assertEqual(destination.name, "gui_test.csv")
        self.assertEqual(len(events), summary["enabled_events"])
        self.assertEqual(
            [
                {key: row[key] for key in master_rows()[0]}
                for row in loaded_rows
            ],
            master_rows(),
        )
        self.assertTrue(
            all(row["advanced_efficiency"] == "" for row in loaded_rows)
        )

    def test_invalid_update_does_not_overwrite_valid_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            schedule_directory = Path(directory)
            destination, _ = save_schedule(
                schedule_directory, "protected", master_rows()
            )
            original = destination.read_bytes()
            invalid_rows = master_rows()
            invalid_rows[-1]["enabled"] = "FALSE"

            with self.assertRaises(ScheduleValidationError):
                save_schedule(schedule_directory, "protected", invalid_rows)

            self.assertEqual(destination.read_bytes(), original)

    def test_schedule_name_cannot_escape_schedule_directory(self):
        for invalid in ("../outside", "nested/name", "", ".hidden", "name.csv.exe"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    normalize_schedule_name(invalid)

        self.assertEqual(normalize_schedule_name("test-one.csv"), "test-one.csv")

    def test_station_schedule_names_are_automatic_and_reversible(self):
        self.assertEqual(station_suffix_from_hostname("WH-station1"), "WH_1")
        self.assertEqual(
            station_schedule_filename("alu_efficiency_test", "WH_1"),
            "alu_efficiency_test_WH_1.csv",
        )
        self.assertEqual(
            station_schedule_filename("alu_efficiency_test_WH_1.csv", "WH_1"),
            "alu_efficiency_test_WH_1.csv",
        )
        self.assertEqual(
            friendly_schedule_name("alu_efficiency_test_WH_1.csv", "WH_1"),
            "alu_efficiency_test",
        )
        with self.assertRaisesRegex(ValueError, "belongs to WH-2"):
            station_schedule_filename("alu_efficiency_test_WH_2", "WH_1")

    def test_schedule_list_contains_only_current_station(self):
        with tempfile.TemporaryDirectory() as directory:
            schedule_directory = Path(directory)
            for filename in (
                "alpha_WH_1.csv",
                "beta_WH_1.csv",
                "alpha_WH_2.csv",
                "legacy.csv",
            ):
                (schedule_directory / filename).touch()

            choices = station_schedule_choices(schedule_directory, "WH_1")

        self.assertEqual(
            choices,
            [
                {"filename": "alpha_WH_1.csv", "name": "alpha"},
                {"filename": "beta_WH_1.csv", "name": "beta"},
            ],
        )

    def test_preflight_mode_is_derived_from_saved_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            schedule_directory = Path(directory)
            water_path, _ = save_schedule(
                schedule_directory, "water", master_rows()
            )
            no_water_rows = [
                row for row in master_rows() if row["event_type"] != "water_draw"
            ]
            dry_path, _ = save_schedule(
                schedule_directory, "dry", no_water_rows
            )

            self.assertTrue(schedule_uses_water(water_path))
            self.assertFalse(schedule_uses_water(dry_path))

    def test_preflight_endpoint_streams_checks_and_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            schedule_directory = Path(directory)
            schedule_path, _ = save_schedule(
                schedule_directory, "stream_test_WH_1", master_rows()
            )
            handler = type(
                "TestScheduleGuiHandler",
                (ScheduleGuiHandler,),
                {
                    "schedule_directory": schedule_directory,
                    "hostname": "WH-station1",
                    "station_suffix": "WH_1",
                    "log_message": lambda *args: None,
                },
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def fake_preflight(args, on_check=None):
                checks = [
                    PreflightCheck("platform", True, "linux"),
                    PreflightCheck("ACS37800", False, "not found"),
                ]
                for check in checks:
                    on_check(check)
                return checks

            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/api/preflight",
                    data=json.dumps({"filename": schedule_path.name}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch(
                    "software.schedule_gui.run_preflight",
                    side_effect=fake_preflight,
                ):
                    with urlopen(request, timeout=5) as response:
                        events = [json.loads(line) for line in response]
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(events[0]["type"], "start")
        self.assertTrue(events[0]["water"])
        self.assertEqual([event["type"] for event in events[1:3]], ["check", "check"])
        self.assertEqual(events[-1]["type"], "summary")
        self.assertEqual(events[-1]["failed"], 1)

    def test_wh_information_endpoint_returns_decoded_result(self):
        handler = type(
            "TestScheduleGuiHandler",
            (ScheduleGuiHandler,),
            {
                "hostname": "WH-station1",
                "station_suffix": "WH_1",
                "log_message": lambda *args: None,
            },
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        expected = {
            "timestamp_pacific": "2026-08-17T12:34:56.000-07:00",
            "bitmap": "0x00000141",
            "raw_bitmap": "0x00000141",
            "capabilities": [
                {"bit": 0, "name": "Cycling"},
                {"bit": 6, "name": "Advanced Load Up"},
                {"bit": 8, "name": "SGD Efficiency Level"},
            ],
        }
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_port}/api/wh-information",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with patch("software.schedule_gui.read_wh_information", return_value=expected):
                with urlopen(request, timeout=5) as response:
                    result = json.load(response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(result, expected)

    def test_unknown_browser_fields_are_rejected(self):
        rows = master_rows()
        rows[0]["unexpected"] = "value"

        with self.assertRaisesRegex(ValueError, "unknown fields"):
            validate_rows(rows)

    def test_efficiency_zero_survives_gui_save_and_reload(self):
        rows = [
            {
                "enabled": "TRUE",
                "event_id": "ignored",
                "time_after_start": "00:00:00",
                "phase": "event",
                "event_type": "cta",
                "action": "advanced_load_up",
                "event_duration_minutes": "60",
                "advanced_value": "5",
                "advanced_units": "100_wh",
                "expected_operational_states": "",
                "target_volume_gal": "",
                "expected_flow_gpm": "",
                "notes": "",
                "advanced_efficiency": "0",
            },
            {
                "enabled": "TRUE",
                "event_id": "ignored",
                "time_after_start": "01:00:00",
                "phase": "",
                "event_type": "test",
                "action": "end",
                "event_duration_minutes": "",
                "advanced_value": "",
                "advanced_units": "",
                "expected_operational_states": "",
                "target_volume_gal": "",
                "expected_flow_gpm": "",
                "notes": "",
                "advanced_efficiency": "",
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            destination, _ = save_schedule(Path(directory), "efficiency_zero", rows)
            loaded = load_schedule_rows(destination)
            event = load_schedule(destination)[0]

        self.assertEqual(loaded[0]["advanced_efficiency"], "0")
        self.assertEqual(event.advanced_efficiency, 0)


if __name__ == "__main__":
    unittest.main()
