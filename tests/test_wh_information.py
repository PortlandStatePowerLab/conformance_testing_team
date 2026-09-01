import csv
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from software.wh_information import (
    decode_capabilities,
    decode_dr_readiness,
    read_wh_information,
)


DEVICE_INFORMATION_COLUMNS = (
    "timestamp_pacific",
    "response_code",
    "response_name",
    "cta2045_version",
    "capability_bitmap_hex",
)


class WaterHeaterInformationTests(unittest.TestCase):
    def test_only_opted_out_states_are_not_dr_ready(self):
        self.assertTrue(decode_dr_readiness(0))
        self.assertTrue(decode_dr_readiness(5))
        self.assertFalse(decode_dr_readiness(11))
        self.assertFalse(decode_dr_readiness(12))
        self.assertIsNone(decode_dr_readiness(None))

    def test_capability_bits_are_decoded_across_protocol_bytes(self):
        self.assertEqual(
            decode_capabilities("00000141"),
            [
                {"bit": 0, "name": "Cycling"},
                {"bit": 6, "name": "Advanced Load Up"},
                {"bit": 8, "name": "SGD Efficiency Level"},
            ],
        )

    def test_wh3_bitmap_keeps_recorded_hex_order(self):
        self.assertEqual(
            decode_capabilities("000001C0"),
            [
                {"bit": 6, "name": "Advanced Load Up"},
                {"bit": 7, "name": "Price Stream"},
                {"bit": 8, "name": "SGD Efficiency Level"},
            ],
        )

    def test_existing_controller_query_is_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "cta2045_controller"
            binary.touch()

            def fake_run(command, **kwargs):
                information_path = Path(kwargs["env"]["CTA_DEVICE_INFO_LOG_PATH"])
                event_path = Path(kwargs["env"]["CTA_EVENT_LOG_PATH"])
                with information_path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=DEVICE_INFORMATION_COLUMNS)
                    writer.writeheader()
                    writer.writerow(
                        {
                            "timestamp_pacific": "2026-08-17T12:34:56.000-07:00",
                            "response_code": "0",
                            "response_name": "success",
                            "cta2045_version": "B",
                            "capability_bitmap_hex": "00000141",
                        }
                    )
                with event_path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=("event", "operational_state"),
                    )
                    writer.writeheader()
                    writer.writerow(
                        {"event": "operational_state", "operational_state": "11"}
                    )
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("software.wh_information.subprocess.run", side_effect=fake_run):
                result = read_wh_information(
                    cta_binary=binary,
                    cta_directory=root,
                )

        self.assertEqual(result["bitmap"], "0x00000141")
        self.assertEqual(result["cta2045_version"], "B")
        self.assertEqual(result["raw_bitmap"], "0x00000141")
        self.assertFalse(result["dr_ready"])
        self.assertEqual([item["bit"] for item in result["capabilities"]], [0, 6, 8])

    def test_timeout_is_reported_concisely(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "cta2045_controller"
            binary.touch()
            with patch(
                "software.wh_information.subprocess.run",
                side_effect=subprocess.TimeoutExpired("controller", 20),
            ):
                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    read_wh_information(cta_binary=binary, cta_directory=root)


if __name__ == "__main__":
    unittest.main()
