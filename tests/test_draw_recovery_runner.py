"""Exercise the orchestrator with virtual time and no connected hardware."""

import json
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from software import conformance_test_runner as runner
from software.scheduling.schedule_parser import load_schedule


class RecoveryRunnerTests(unittest.TestCase):
    def simulate(self, heats):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            source = root / "schedule.csv"
            source.write_text("test fixture")
            equipment = root / "WH-station1.json"
            equipment.write_text(json.dumps(dict(equipment_id="fixture", temperature_setpoint_f=125)))
            fixture = Path(__file__).resolve().parents[1] / "software/gui/gui_schedules/FHR-Normal.csv"
            original = load_schedule(fixture)
            first = replace(original[-2], offset_seconds=0, source_row=3)
            second = replace(first, event_id="second", draw_type="volume", dependent_end=True,
                             target_volume_gal=1, expected_flow_gpm=3, max_draw_minutes=None,
                             temp_drop_f=None, offset_seconds=50000, source_row=4)
            end = replace(original[-1], offset_seconds=100000, source_row=5)
            events = [replace(original[0], source_row=2), first, second, end]
            args = runner.build_parser().parse_args([])
            args.master_schedule = source
            args.cta_binary = source
            args.cta_schedule = root / "generated.csv"
            args.cta_controller_dir = root
            args.sensor_configuration = None
            args.no_publish_results = True
            clock = [0.0]
            launched = []

            def sleep(seconds):
                clock[0] += 60 if seconds == 0.2 else seconds
                if clock[0] > 10000:
                    raise AssertionError("Runner did not finish")

            def updates():
                state = 1 if heats and 180 <= clock[0] < 300 else 0
                return [runner.CtaLogUpdate("operational_state", "", "", "ok", state)]

            def launch(event, *unused, **kwargs):
                launched.append((event.event_id, clock[0]))
                managed = Mock(event_id=event.event_id)
                managed.process.poll.return_value = 0
                managed.process.returncode = 0
                return managed

            def compile_schedule(*unused, **kwargs):
                args.cta_schedule.write_text("fixture")

            def mock(name, **kwargs):
                return stack.enter_context(patch("software.conformance_test_runner." + name, **kwargs))

            mock("sys.platform", new="linux")
            mock("time.monotonic", side_effect=lambda: clock[0])
            mock("time.sleep", side_effect=sleep)
            mock("utc_now", side_effect=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=clock[0]))
            mock("socket.gethostname", return_value="WH-station1")
            mock("DEFAULT_EQUIPMENT_DIRECTORY", new=root)
            mock("_create_run_directory", return_value=root)
            mock("_archive_station_equipment", return_value=equipment)
            mock("_archive_station_calibration", return_value=None)
            mock("compile_cta_schedule", side_effect=compile_schedule)
            mock("wait_for_power_ready")
            monitor = Mock()
            monitor.process.poll.return_value = None
            mock("start_process", return_value=monitor)
            mock("_launch_water_draw", side_effect=launch)
            mock("CtaEventReader").return_value.read_new.side_effect = updates
            mock("ProgressReporter")
            mock("_write_gui_stage")
            mock("stop_process")
            mock("generate_final_outputs")
            logger = mock("RunEventLogger").return_value
            runner.run_hardware_test(args, events, canonical_schedule=source)
            return launched, clock[0], logger.record.call_args_list

    def test_no_heating_skips_next_volume_and_ends_after_observation(self):
        launched, finished, calls = self.simulate(False)
        self.assertEqual(len(launched), 1)
        self.assertGreaterEqual(finished - launched[0][1], 1800)
        self.assertTrue(any(call.args[:2] == ("water_draw_skipped", "skipped") for call in calls))

    def test_recovery_releases_volume_without_rest_then_observes_final_draw(self):
        launched, finished, calls = self.simulate(True)
        self.assertEqual([item[0] for item in launched], ["water_draw_1", "second"])
        self.assertGreaterEqual(launched[1][1], 300)
        self.assertLess(launched[1][1], 360)
        self.assertGreaterEqual(finished - launched[1][1], 1800)
        self.assertTrue(any(call.args[:2] == ("run_finished", "completed") for call in calls))

