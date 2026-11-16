import unittest

from software.runtime.draw_recovery import DrawRecovery, RECOVERY_TIMEOUT_SECONDS


class DrawRecoveryTests(unittest.TestCase):
    def test_idle_final_draw_ends_after_thirty_minutes(self):
        tracker = DrawRecovery(0, final=True)
        tracker.observe(0, 1799)
        self.assertIsNone(tracker.action(1799))
        self.assertEqual(tracker.action(1800), "end_test")

    def test_active_heating_at_draw_stop_waits_for_recovery(self):
        for running, idle in ((1, 0), (2, 4), (3, 6), (7, 8), (12, 11), (13, 14)):
            with self.subTest(running=running):
                tracker = DrawRecovery(0, final=True)
                tracker.observe(running, 0)
                tracker.observe(running, 2000)
                self.assertIsNone(tracker.action(2000))
                tracker.observe(idle, 2100)
                tracker.observe(idle, 3899)
                self.assertEqual(tracker.action(3900), "end_test")

    def test_first_late_heating_extends_final_window_only_once(self):
        tracker = DrawRecovery(0, final=True)
        tracker.observe(0, 0)
        tracker.observe(1, 1700)
        tracker.observe(0, 2200)
        tracker.observe(1, 2400)
        tracker.observe(0, 2600)
        tracker.observe(1, 3999)
        self.assertEqual(tracker.action(4000), "end_test")

    def test_intermediate_draw_starts_next_immediately_after_recovery(self):
        tracker = DrawRecovery(0, final=False)
        tracker.observe(4, 0)
        tracker.observe(2, 1700)
        self.assertIsNone(tracker.action(1700))
        tracker.observe(4, 2200)
        self.assertEqual(tracker.action(2200), "next_draw")

    def test_intermediate_idle_draw_ends_test_without_next_draw(self):
        tracker = DrawRecovery(0, final=False)
        tracker.observe(6, 1799)
        self.assertEqual(tracker.action(1800), "end_test")

    def test_heating_after_window_does_not_restart_sequence(self):
        tracker = DrawRecovery(0, final=False)
        tracker.observe(1, 1801)
        self.assertEqual(tracker.action(1801), "end_test")

    def test_twelve_hour_recovery_timeout(self):
        tracker = DrawRecovery(0, final=False)
        tracker.observe(1, 100)
        with self.assertRaises(TimeoutError):
            tracker.action(100 + RECOVERY_TIMEOUT_SECONDS)
        with self.assertRaises(TimeoutError):
            tracker.observe(0, 100 + RECOVERY_TIMEOUT_SECONDS)

    def test_missing_stale_and_error_states_cannot_release_draw(self):
        tracker = DrawRecovery(0, final=False)
        self.assertIsNone(tracker.action(1800))
        tracker.observe(0, 0)
        self.assertIsNone(tracker.action(1800))
        tracker.observe(0, 1800)
        tracker.observe(5, 1801)
        self.assertIsNone(tracker.action(1801))
        with self.assertRaises(TimeoutError):
            tracker.action(1800 + RECOVERY_TIMEOUT_SECONDS)


if __name__ == "__main__":
    unittest.main()
