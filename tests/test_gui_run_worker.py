import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from software.gui.gui_run_worker import run


class GuiRunWorkerTests(unittest.TestCase):
    def test_early_failure_replaces_running_message_with_runner_diagnostic(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "status.json").write_text('{}', encoding="utf-8")
            (root / "runner_stage.json").write_text(json.dumps({
                "state": "running", "message": "Hardware test is running.",
            }), encoding="utf-8")
            (root / "runner.log").write_text(
                "CONFORMANCE_TEST_ERROR RuntimeError: missing equipment setpoint\n",
                encoding="utf-8",
            )
            process = Mock(pid=123, returncode=1)
            process.poll.return_value = 1
            args = argparse.Namespace(
                run_directory=root, repository_root=repository,
                schedule=repository / "software/gui/gui_schedules/FHR-GE.csv",
                result_name="FHR-GE", water=True,
            )
            with patch("software.gui.gui_run_worker.subprocess.Popen", return_value=process):
                self.assertEqual(run(args), 1)
            status = json.loads((root / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "failed")
            self.assertEqual(status["message"], "The test runner exited before completion.")
            self.assertEqual(status["error"], "RuntimeError: missing equipment setpoint")
