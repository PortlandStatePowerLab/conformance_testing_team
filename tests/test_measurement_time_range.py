import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from software.plots.measurement_time_range import measurement_end_timestamp


class MeasurementTimeRangeTests(unittest.TestCase):
    def test_each_stream_can_determine_end_including_multiple_draws(self):
        streams = ["cta_commodity.csv", "power.csv", "water_draw_1.csv", "water_draw_2.csv"]
        for latest in streams:
            with self.subTest(latest=latest), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                for name in streams:
                    with (directory / name).open("w", newline="") as handle:
                        writer = csv.writer(handle)
                        writer.writerow(["timestamp_pacific"])
                        writer.writerow(["2026-08-26T17:16:23.647-07:00" if name == latest else "2026-08-26 17:16:01"])
                        # Do not assume file order or require a measured value.
                        writer.writerow(["2026-08-26 17:15:00"])
                        writer.writerow(["invalid"])
                self.assertEqual(measurement_end_timestamp(directory), datetime(2026, 8, 26, 17, 16, 23, 647000))

    def test_missing_streams_and_shutdown_events_do_not_extend_end(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "water_draw_1.csv").write_text("timestamp_pacific\n2026-08-26 17:16:23\n")
            (directory / "cta_events.csv").write_text("timestamp_pacific\n2026-08-26 17:16:30\n")
            self.assertEqual(measurement_end_timestamp(directory), datetime(2026, 8, 26, 17, 16, 23))

    def test_fallback_when_no_measurement_files_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            timestamp = datetime(2026, 8, 26, 17, 16)
            self.assertEqual(measurement_end_timestamp(temp, timestamp), timestamp)
