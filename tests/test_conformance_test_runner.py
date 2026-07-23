import argparse
import unittest

from software.conformance_test_runner import safe_identifier, schedule_summary
from software.schedule_parser import load_schedule
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MASTER_SCHEDULE = REPOSITORY_ROOT / "software" / "conformance_test_schedule.csv"


class ConformanceTestRunnerTests(unittest.TestCase):
    def test_schedule_summary(self):
        summary = schedule_summary(load_schedule(MASTER_SCHEDULE))
        self.assertEqual(summary["enabled_events"], 8)
        self.assertEqual(summary["cta_events"], 4)
        self.assertEqual(summary["water_draws"], 3)
        self.assertEqual(summary["duration_seconds"], 21600)

    def test_run_identifier_is_sanitized(self):
        self.assertEqual(safe_identifier("test run 1"), "test_run_1")
        with self.assertRaises(argparse.ArgumentTypeError):
            safe_identifier("***")


if __name__ == "__main__":
    unittest.main()
