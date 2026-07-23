import argparse
import unittest

from software.conformance_test_runner import safe_identifier, schedule_summary
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


if __name__ == "__main__":
    unittest.main()
