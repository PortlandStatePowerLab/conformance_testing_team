import csv
import json
import tempfile
import unittest
from pathlib import Path

from software.plots.water_draw_temperature import build_figure, generate, load_draws


class WaterDrawTemperaturePlotTests(unittest.TestCase):
    def write_draw(self, root, number, flow=3):
        event_id = f"water_draw_{number}"
        with (root / f"{event_id}.csv").open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["event_id", "timestamp_pacific", "hot_temp_f", "flow_gpm", "valve_state", "stop_reason"])
            writer.writerow([event_id, f"2026-11-16T{number:02d}:00:00-08:00", 125, flow, "open", ""])
            writer.writerow([event_id, f"2026-11-16T{number:02d}:01:00-08:00", 105, flow, "open", ""])
            writer.writerow([event_id, f"2026-11-16T{number:02d}:01:01-08:00", 105, flow, "closed", "temperature_threshold_reached"])
        (root / f"{event_id}.log").write_text("WATER_DRAW_READY " + json.dumps(
            dict(draw_type="temp_drop", stop_temp_f=105)) + "\n")

    def test_stacked_panels_have_shared_y_scales_and_correct_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_draw(root, 2)
            self.write_draw(root, 1)
            draws = load_draws(root)
            self.assertEqual([draw.event_id for draw in draws], ["water_draw_1", "water_draw_2"])
            self.assertEqual(len(draws[0].samples), 2)
            figure = build_figure(root)
            try:
                self.assertEqual(len(figure.axes), 8)
                axes = [axis for axis in figure.axes if axis.get_ylabel().startswith("Hot Water")]
                self.assertEqual(axes[0].get_ylim(), axes[1].get_ylim())
                self.assertIn("temperature threshold reached", figure.axes[0].get_title(loc="left"))
                self.assertEqual(axes[0].get_xlim()[0], 0)
                self.assertAlmostEqual(axes[0].get_xlim()[1], 1 + 1 / 60)
                self.assertTrue(any(axis.get_ylabel() == "Operational\nState" for axis in figure.axes))
                self.assertFalse(any("Power" in axis.get_ylabel() for axis in figure.axes))
                self.assertEqual(len(axes[0].patches), 0)  # No invented background when command data is absent.
                threshold = next(line for line in axes[0].lines if line.get_label().startswith("Stop threshold"))
                self.assertEqual(list(threshold.get_ydata()), [105, 105])
            finally:
                figure.clear()
            output = generate(root)
            self.assertEqual(output.name, "water_draw_temperature.png")
            self.assertGreater(output.stat().st_size, 1000)

    def test_zero_flow_is_skipped_and_no_threshold_is_invented(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_draw(root, 1, flow=0)
            self.assertEqual(load_draws(root), [])
            with self.assertRaisesRegex(ValueError, "no water draws"):
                build_figure(root)
            self.write_draw(root, 2)
            (root / "water_draw_2.log").unlink()
            self.assertIsNone(load_draws(root)[0].threshold)

    def test_horizontal_preview_uses_individual_stop_times_and_separate_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_draw(root, 1)
            self.write_draw(root, 2)
            second = root / "water_draw_2.csv"
            second.write_text(second.read_text().replace("02:01:01", "02:04:01"))
            figure = build_figure(root, side_by_side=True)
            try:
                axes = [axis for axis in figure.axes if axis.get_ylabel().startswith("Hot Water")]
                self.assertAlmostEqual(axes[0].get_xlim()[1], 1 + 1 / 60)
                self.assertAlmostEqual(axes[1].get_xlim()[1], 4 + 1 / 60)
                self.assertEqual(axes[0].get_ylim(), axes[1].get_ylim())
                self.assertAlmostEqual(axes[0].get_position().y0, axes[1].get_position().y0)
                self.assertLess(axes[0].get_position().x1, axes[1].get_position().x0)
            finally:
                figure.clear()
            output = generate(root, side_by_side=True)
            self.assertEqual(output.name, "water_draw_temperature_side_by_side.png")
            self.assertFalse((root / "water_draw_temperature.png").exists())

    def test_command_and_state_bands_carry_into_zoom_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_draw(root, 1)
            with (root / "master_schedule.csv").open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["enabled", "action", "expected_operational_states"])
                writer.writerow(["TRUE", "shed", "2|4"])
            with (root / "cta_events.csv").open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["timestamp_pacific", "event", "command", "result", "operational_state", "operational_state_name"])
                writer.writerow(["2026-11-16T00:50:00-08:00", "application_ack", "shed", "ack", "", ""])
                writer.writerow(["2026-11-16T00:51:00-08:00", "operational_state", "", "", "4", "Idle Curtailed"])
                writer.writerow(["2026-11-16T01:00:30-08:00", "operational_state", "", "", "2", "Running Curtailed"])
            figure = build_figure(root)
            try:
                command_axis, temperature_axis, flow_axis, state_axis = figure.axes
                self.assertEqual([text.get_text() for text in command_axis.texts], ["Shed"])
                self.assertEqual([text.get_text() for text in state_axis.texts], ["Idle\nCurtailed", "Running\nCurtailed"])
                self.assertEqual(len(temperature_axis.patches), 1)  # Only command shading; water fill stays below flow.
                self.assertTrue(flow_axis.collections)
                self.assertIn("°F", temperature_axis.get_ylabel())
            finally:
                figure.clear()

    def test_broken_axis_uses_clock_labels_and_proportional_widths(self):
        from software.plots.water_draw_temperature_broken_axis import build_figure as broken_figure, generate as broken_generate

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_draw(root, 1)
            with self.assertRaisesRegex(ValueError, "at least two"):
                broken_figure(root)
            self.write_draw(root, 2)
            second = root / "water_draw_2.csv"
            second.write_text(second.read_text().replace("02:01:01", "02:04:01"))
            figure = broken_figure(root)
            try:
                first_axis, second_axis = figure.axes[1], figure.axes[5]
                width_ratio = first_axis.get_position().width / second_axis.get_position().width
                self.assertAlmostEqual(width_ratio, (1 + 1 / 60) / (4 + 1 / 60))
                self.assertEqual(first_axis.get_ylim(), second_axis.get_ylim())
                self.assertEqual(figure.axes[3].xaxis.get_major_formatter()(0), "01:00 AM")
                self.assertEqual(figure.axes[7].xaxis.get_major_formatter()(0), "02:00 AM")
                self.assertEqual(second_axis.get_ylabel(), "")
                self.assertEqual(figure.axes[2].get_ylabel(), "")
                self.assertTrue(any("omitted" in text.get_text() for text in figure.texts))
            finally:
                figure.clear()
            output = broken_generate(root)
            self.assertEqual(output.name, "water_draw_temperature_broken_axis.png")
            self.assertFalse((root / "water_draw_temperature.png").exists())
            self.assertFalse((root / "water_draw_temperature_side_by_side.png").exists())

    def test_cut_in_reason_comes_from_orchestrator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_draw(root, 1)
            with (root / "orchestrator_events.csv").open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["event", "event_id", "details"])
                writer.writerow(["water_draw_completed", "water_draw_1", json.dumps(dict(reason="cut_in_observed"))])
            self.assertEqual(load_draws(root)[0].reason, "cut_in_observed")

    def test_continuous_command_header_checks_the_omitted_interval(self):
        from software.plots.water_draw_temperature_continuous_command import build_figure as continuous_figure

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_draw(root, 1)
            self.write_draw(root, 2)
            events = root / "cta_events.csv"
            with events.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["timestamp_pacific", "event", "command", "result"])
                writer.writerow(["2026-11-16T00:50:00-08:00", "application_ack", "shed", "ack"])
            figure = continuous_figure(root)
            try:
                self.assertFalse(figure.axes[0].get_visible())
                self.assertFalse(figure.axes[4].get_visible())
                header = figure.axes[-1]
                self.assertIn("Shed", header.texts[0].get_text())
                self.assertIn("unchanged", header.texts[0].get_text())
                self.assertGreater(header.get_position().width, .8)
            finally:
                figure.clear()
            with events.open("a", newline="") as handle:
                csv.writer(handle).writerow(["2026-11-16T01:30:00-08:00", "application_ack", "run_normal", "ack"])
            with self.assertRaisesRegex(ValueError, "changes between draws"):
                continuous_figure(root)
