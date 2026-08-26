import argparse
import io
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from software.conformance_test_runner import (
    DEFAULT_MASTER_SCHEDULE,
    ProgressReporter,
    _create_run_directory,
    _archive_station_equipment,
    _launch_water_draw,
    build_parser,
    clock_text,
    generate_final_outputs,
    publish_run_results,
    progress_text,
    prepare_master_schedule,
    safe_identifier,
    schedule_summary,
    stop_water_draw_at_test_end,
)
from software.schedule_parser import load_schedule
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MASTER_SCHEDULE = REPOSITORY_ROOT / "software" / "conformance_test_schedule.csv"


class ConformanceTestRunnerTests(unittest.TestCase):
    def test_archives_station_equipment_for_future_plot_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "run"
            equipment = root / "equipment"
            run.mkdir()
            equipment.mkdir()
            source = equipment / "WH-station3.json"
            source.write_text('{"manufacturer":"Example","model_number":"M3"}', encoding="utf-8")
            archived = _archive_station_equipment(
                run, hostname="WH-station3", equipment_directory=equipment
            )
            self.assertEqual(archived, run / "equipment.json")
            self.assertEqual((run / "equipment.json").read_text(encoding="utf-8"), source.read_text(encoding="utf-8"))

    def test_test_end_stops_active_water_draw_as_hard_boundary(self):
        active_draw = SimpleNamespace(event_id="water_draw_1")
        logger = Mock()

        with patch("software.conformance_test_runner.stop_process") as stop_process:
            stop_water_draw_at_test_end(
                active_draw,
                timeout_seconds=30.0,
                logger=logger,
            )

        stop_process.assert_called_once_with(
            active_draw,
            timeout_seconds=30.0,
            logger=logger,
        )
        logger.record.assert_called_once_with(
            "water_draw_test_end_cutoff",
            "stopped",
            event_id="water_draw_1",
            details={"reason": "test_end_reached"},
        )

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

    def test_result_publishing_defaults_enabled_with_opt_out(self):
        self.assertFalse(build_parser().parse_args([]).no_publish_results)
        self.assertTrue(
            build_parser().parse_args(["--no-publish-results"]).no_publish_results
        )

    @patch("software.station.station_identity.socket.gethostname", return_value="WH-station4")
    @patch("software.conformance_test_runner._run_git")
    def test_publish_commits_only_station_run_then_rebases_and_pushes(
        self, run_git, _hostname
    ):
        run_git.return_value = SimpleNamespace(
            returncode=0, stdout="/repository", stderr=""
        )
        repository = Path("/repository")
        run_directory = repository / "WH-4/test_123"

        published = publish_run_results(
            run_directory,
            "ALU-Shed-Recovery",
            repository=repository,
        )

        self.assertTrue(published)
        pathspec = "WH-4/test_123"
        self.assertEqual(
            [call.args[1] for call in run_git.call_args_list],
            [
                ["rev-parse", "--show-toplevel"],
                ["add", "--", pathspec],
                [
                    "commit", "--only", "-m",
                    "ALU-Shed-Recovery run WH-4", "--", pathspec,
                ],
                ["pull", "--rebase", "--autostash", "origin", "main"],
                ["push", "origin", "main"],
            ],
        )

    @patch("software.station.station_identity.socket.gethostname", return_value="WH-station2")
    @patch("software.conformance_test_runner._run_git")
    def test_publish_retries_push_after_refreshing_remote(self, run_git, _hostname):
        success = SimpleNamespace(returncode=0, stdout="/repository", stderr="")
        rejected = SimpleNamespace(returncode=1, stdout="", stderr="rejected")
        run_git.side_effect = [
            success, success, success, success, rejected, success, success
        ]

        published = publish_run_results(
            Path("/repository/WH-2/test_123"),
            "test",
            repository=Path("/repository"),
        )

        self.assertTrue(published)
        self.assertEqual(
            [call.args[1][0] for call in run_git.call_args_list],
            ["rev-parse", "add", "commit", "pull", "push", "pull", "push"],
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

    def test_default_run_directory_uses_schedule_name_and_timestamp(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "software.conformance_test_runner.pacific_filename_timestamp",
            return_value="2026_08_16_120000_PDT",
        ):
            run_directory = _create_run_directory(
                Path(directory),
                None,
                Path("software/gui_schedules/professor_demo.csv"),
            )

        self.assertEqual(
            run_directory.name,
            "professor_demo_2026_08_16_120000_PDT",
        )

    def test_explicit_run_identifier_still_overrides_schedule_name(self):
        with tempfile.TemporaryDirectory() as directory:
            run_directory = _create_run_directory(
                Path(directory),
                "requested_name",
                Path("software/gui_schedules/professor_demo.csv"),
            )

        self.assertEqual(run_directory.name, "requested_name")

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

    def test_final_outputs_attempt_every_artifact_independently(self):
        output = io.StringIO()
        errors = io.StringIO()
        run_directory = Path("run")
        with (
            patch(
                "software.conformance_test_runner.generate_conformance_report",
                return_value=run_directory / "conformance_test_report.xlsx",
            ) as report,
            patch(
                "software.conformance_test_runner._generate_energy_take_plot",
                return_value=run_directory / "energy_take_power.png",
            ) as energy_plot,
            patch(
                "software.conformance_test_runner._generate_state_verification_plot",
                side_effect=ValueError("no states"),
            ) as state_plot,
            patch(
                "software.conformance_test_runner._generate_phase_summary",
                return_value=run_directory / "phase_summary.png",
            ) as phase_summary,
            patch(
                "software.conformance_test_runner._generate_event_timeline",
                return_value=run_directory / "event_timeline.png",
            ) as event_timeline,
        ):
            generate_final_outputs(
                run_directory,
                output_stream=output,
                error_stream=errors,
            )

        report.assert_called_once_with(run_directory)
        energy_plot.assert_called_once()
        state_plot.assert_called_once()
        phase_summary.assert_called_once()
        event_timeline.assert_called_once()
        self.assertIn("CONFORMANCE_REPORT run", output.getvalue())
        self.assertIn("ENERGY_TAKE_PLOT run", output.getvalue())
        self.assertIn("PHASE_SUMMARY run", output.getvalue())
        self.assertIn("STATE_VERIFICATION_PLOT_ERROR ValueError: no states", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
