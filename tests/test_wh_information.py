import csv
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from software.wh_information import decode_capabilities, read_wh_information


DEVICE_INFORMATION_COLUMNS = (
    "timestamp_pacific",
    "response_code",
    "response_name",
    "capability_bitmap_hex",
)


class WaterHeaterInformationTests(unittest.TestCase):
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
                with information_path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=DEVICE_INFORMATION_COLUMNS)
                    writer.writeheader()
                    writer.writerow(
                        {
                            "timestamp_pacific": "2026-08-17T12:34:56.000-07:00",
                            "response_code": "0",
                            "response_name": "success",
                            "capability_bitmap_hex": "00000141",
                        }
                    )
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("software.wh_information.subprocess.run", side_effect=fake_run):
                result = read_wh_information(
                    cta_binary=binary,
                    cta_directory=root,
                )

        self.assertEqual(result["bitmap"], "0x00000141")
        self.assertEqual(result["raw_bitmap"], "0x00000141")
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
