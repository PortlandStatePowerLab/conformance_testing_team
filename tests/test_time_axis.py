import unittest
from datetime import datetime, timedelta

from software.time_axis import apply_even_clock_ticks, time_tick_interval_minutes


class TimeAxisTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 9, 1, 13, 9)

    def interval_for(self, minutes):
        return time_tick_interval_minutes(
            self.start, self.start + timedelta(minutes=minutes)
        )

    def test_short_demo_uses_ten_minute_ticks(self):
        self.assertEqual(self.interval_for(70), 10)

    def test_three_hour_run_uses_thirty_minute_ticks(self):
        self.assertEqual(self.interval_for(180), 30)

    def test_seven_hour_run_keeps_hourly_ticks(self):
        self.assertEqual(self.interval_for(420), 60)

    def test_rejects_impossible_label_limit(self):
        with self.assertRaises(ValueError):
            time_tick_interval_minutes(self.start, self.start, maximum_labels=1)

    def test_even_ticks_use_requested_count(self):
        class Axis:
            class XAxis:
                def set_major_locator(self, locator):
                    self.locator = locator

                def set_major_formatter(self, formatter):
                    self.formatter = formatter

            xaxis = XAxis()

        axis = Axis()
        apply_even_clock_ticks(axis, self.start, self.start + timedelta(hours=3))
        self.assertEqual(len(axis.xaxis.locator.locs), 6)


if __name__ == "__main__":
    unittest.main()
