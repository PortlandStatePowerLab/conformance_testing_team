import argparse
import io
import unittest

from software.conformance_test_runner import (
    ProgressReporter,
    clock_text,
    progress_text,
    safe_identifier,
    schedule_summary,
)
from software.schedule_parser import load_schedule
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MASTER_SCHEDULE = REPOSITORY_ROOT / "software" / "conformance_test_schedule.csv"


class ConformanceTestRunnerTests(unittest.TestCase):
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
        text = progress_text(events, 26 * 60)
        self.assertIn("50.0%", text)
        self.assertIn("elapsed 00:26:00", text)
        self.assertIn("remaining 00:26:00", text)
        self.assertIn("phase event", text)
        self.assertIn("next run_normal_3 in 00:09:00", text)

    def test_progress_text_reports_prestart_and_completion(self):
        events = load_schedule(MASTER_SCHEDULE)
        self.assertIn("starts in 00:00:15", progress_text(events, -15))
        completed = progress_text(events, 52 * 60, status="completed")
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

    def test_clock_text_supports_tests_longer_than_one_day(self):
        self.assertEqual(clock_text(25 * 3600), "25:00:00")


if __name__ == "__main__":
    unittest.main()
