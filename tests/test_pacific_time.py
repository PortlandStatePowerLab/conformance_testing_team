"""Tests for Pacific record and filename timestamp formatting."""

import unittest
from datetime import datetime, timezone

from software.pacific_time import (
    pacific_filename_timestamp,
    pacific_timestamp,
)


class PacificTimeTest(unittest.TestCase):
    def test_record_timestamps_use_pdt_and_pst_offsets(self):
        summer = datetime(2026, 7, 29, 1, 43, 27, 898000, tzinfo=timezone.utc)
        winter = datetime(2026, 12, 29, 2, 43, 27, 898000, tzinfo=timezone.utc)
        self.assertEqual(
            pacific_timestamp(summer),
            "2026-07-28T18:43:27.898-07:00",
        )
        self.assertEqual(
            pacific_timestamp(winter),
            "2026-12-28T18:43:27.898-08:00",
        )

    def test_filename_timestamps_identify_pdt_and_pst(self):
        summer = datetime(2026, 7, 29, 1, 43, 27, tzinfo=timezone.utc)
        winter = datetime(2026, 12, 29, 2, 43, 27, tzinfo=timezone.utc)
        self.assertEqual(
            pacific_filename_timestamp(summer),
            "2026_07_28_184327_PDT",
        )
        self.assertEqual(
            pacific_filename_timestamp(winter),
            "2026_12_28_184327_PST",
        )


if __name__ == "__main__":
    unittest.main()
