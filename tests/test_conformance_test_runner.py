import argparse
import io
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from software.conformance_test_runner import (
    DEFAULT_MASTER_SCHEDULE,
    ProgressReporter,
    _launch_water_draw,
    build_parser,
    clock_text,
    progress_text,
    prepare_master_schedule,
    safe_identifier,
    schedule_summary,
)
from software.schedule_parser import load_schedule
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MASTER_SCHEDULE = REPOSITORY_ROOT / "software" / "conformance_test_schedule.csv"


class ConformanceTestRunnerTests(unittest.TestCase):
    def test_default_master_schedule_remains_xlsx(self):
        self.assertEqual(
            build_parser().parse_args([]).master_schedule,
            DEFAULT_MASTER_SCHEDULE,
        )

    def test_csv_master_schedule_is_validated_and_used_directly(self):
        with patch(
            "software.conformance_test_runner.load_schedule"
        ) as validate_schedule:
            selected = prepare_master_schedule(
                MASTER_SCHEDULE,
                Path("unused-canonical-output.csv"),
            )

        self.assertEqual(selected, MASTER_SCHEDULE)
        validate_schedule.assert_called_once_with(MASTER_SCHEDULE)

    def test_outside_communication_heartbeat_defaults_enabled(self):
        self.assertFalse(
            build_parser().parse_args([]).disable_outside_communication_heartbeat
        )
        self.assertTrue(
            build_parser()
            .parse_args(["--disable-outside-communication-heartbeat"])
            .disable_outside_communication_heartbeat
        )

    def test_schedule_summary(self):
        events = load_schedule(MASTER_SCHEDULE)
        summary = schedule_summary(events)
        self.assertEqual(summary["enabled_events"], len(events))
        self.assertEqual(
            summary["cta_events"], sum(event.event_type == "cta" for event in events)
        )
        self.assertEqual(
            summary["water_draws"],
            sum(event.event_type == "water_draw" for event in events),
        )
        self.assertEqual(summary["duration_seconds"], events[-1].offset_seconds)

    def test_run_identifier_is_sanitized(self):
        self.assertEqual(safe_identifier("test run 1"), "test_run_1")
        with self.assertRaises(argparse.ArgumentTypeError):
            safe_identifier("***")

    def test_progress_text_reports_time_percentage_phase_and_next_event(self):
        events = load_schedule(MASTER_SCHEDULE)
        test_end = next(
            event
            for event in events
            if event.event_type == "test" and event.action == "end"
        )
        duration = test_end.offset_seconds
        elapsed = duration / 2
        text = progress_text(events, elapsed)
        self.assertIn("50.0%", text)
        self.assertIn(f"elapsed {clock_text(elapsed)}", text)
        self.assertIn(f"remaining {clock_text(duration - elapsed)}", text)
        next_event = next(event for event in events if event.offset_seconds > elapsed)
        self.assertIn(
            f"next {next_event.event_id} in "
            f"{clock_text(next_event.offset_seconds - elapsed)}",
            text,
        )

    def test_progress_text_reports_prestart_and_completion(self):
        events = load_schedule(MASTER_SCHEDULE)
        self.assertIn("starts in 00:00:15", progress_text(events, -15))
        completed = progress_text(
            events, events[-1].offset_seconds, status="completed"
        )
        self.assertIn("100.0%", completed)
        self.assertIn("remaining 00:00:00", completed)
        self.assertIn("next none", completed)
        self.assertIn("status completed", completed)

    def test_redirected_progress_is_throttled_but_finish_is_printed(self):
        events = load_schedule(MASTER_SCHEDULE)
        output = io.StringIO()
        reporter = ProgressReporter(events, stream=output)
        reporter.update(0)
        reporter.update(1)
        reporter.finish(2, "interrupted")
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("status running", lines[0])
        self.assertIn("status interrupted", lines[1])

    def test_interactive_progress_redraws_one_terminal_line(self):
        class InteractiveStream(io.StringIO):
            def isatty(self):
                return True

        events = load_schedule(MASTER_SCHEDULE)
        output = InteractiveStream()
        reporter = ProgressReporter(events, stream=output)
        reporter.update(0)
        reporter.update(1, force=True)
        live_output = output.getvalue()
        self.assertNotIn("\n", live_output)
        self.assertEqual(live_output.count("\r\x1b[2K"), 2)
        self.assertEqual(live_output.count("\x1b[32m"), 2)
        self.assertEqual(live_output.count("\x1b[0m"), 2)

        reporter.finish(2, "completed")
        self.assertTrue(output.getvalue().endswith("\n"))

    def test_clock_text_supports_tests_longer_than_one_day(self):
        self.assertEqual(clock_text(25 * 3600), "25:00:00")

    def test_water_draw_receives_archived_sensor_configuration(self):
        event = SimpleNamespace(event_id="water_draw_1", target_volume_gal=5.0)
        with tempfile.TemporaryDirectory() as directory:
            run_directory = Path(directory)
            configuration = run_directory / "sensor_configuration.json"
            configuration.write_text("{}", encoding="utf-8")
            with patch(
                "software.conformance_test_runner.start_process"
            ) as start_process:
                _launch_water_draw(
                    event,
                    run_directory,
                    enable_output=True,
                    sensor_configuration=configuration,
                )

        command = start_process.call_args.args[1]
        configuration_index = command.index("--sensor-configuration")
        self.assertEqual(command[configuration_index + 1], str(configuration))
        self.assertIn("--enable-output", command)


if __name__ == "__main__":
    unittest.main()
