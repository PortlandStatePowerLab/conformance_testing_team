#!/usr/bin/env python3
"""Run one GUI-launched conformance test and maintain persistent status."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .schedule_parser import load_schedule
from .pacific_time import pacific_filename_timestamp

PACIFIC = ZoneInfo("America/Los_Angeles")


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".status.",
            suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run(args: argparse.Namespace) -> int:
    status_path = args.run_directory / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    events = load_schedule(args.schedule)
    test_end = next(event for event in events if event.event_type == "test")
    duration = test_end.offset_seconds
    started = datetime.now(PACIFIC)
    status.update(
        state="initializing", worker_pid=os.getpid(), started_at=started.isoformat(),
        expected_end_at=(started + timedelta(seconds=duration)).isoformat(),
        duration_seconds=duration, dependent_end=test_end.dependent_end,
        duration_estimated=test_end.dependent_end, error=None,
    )
    atomic_json(status_path, status)
    command = [
        sys.executable, "-m", "software.conformance_test_runner", "--run-hardware",
        "--master-schedule", str(args.schedule),
        "--run-id", f"{args.result_name}_{pacific_filename_timestamp()}",
        "--test-name", args.result_name,
    ]
    if args.water:
        command.append("--enable-water-output")
    log_path = args.run_directory / "runner.log"
    stage_path = args.run_directory / "runner_stage.json"
    return_code = 1
    try:
        with log_path.open("a", encoding="utf-8", buffering=1) as log:
            environment = os.environ.copy()
            environment["CONFORMANCE_GUI_STAGE_PATH"] = str(stage_path)
            process = subprocess.Popen(
                command, cwd=args.repository_root, stdout=log,
                stderr=subprocess.STDOUT, text=True, env=environment,
            )
            status.update(state="running", runner_pid=process.pid)
            atomic_json(status_path, status)
            while process.poll() is None:
                now = datetime.now(PACIFIC)
                elapsed = max(0, int((now - started).total_seconds()))
                if stage_path.is_file():
                    try:
                        stage = json.loads(stage_path.read_text(encoding="utf-8"))
                        status.update(state=stage["state"], message=stage["message"])
                    except (KeyError, OSError, json.JSONDecodeError):
                        pass
                status.update(
                    last_heartbeat_at=now.isoformat(),
                    elapsed_seconds=min(elapsed, duration),
                    remaining_seconds=(
                        0 if status.get("state") in {"finalizing", "generating_outputs"}
                        else max(0, duration - elapsed)
                    ),
                )
                atomic_json(status_path, status)
                time.sleep(5)
            return_code = process.returncode
        status.update(
            state="completed" if return_code == 0 else "failed",
            finished_at=datetime.now(PACIFIC).isoformat(), return_code=return_code,
            remaining_seconds=0 if return_code == 0 else status.get("remaining_seconds"),
            message=(
                "Test complete; shutdown and final report generation finished."
                if return_code == 0 else "The test runner exited before completion."
            ),
        )
    except Exception as exc:
        status.update(
            state="failed", finished_at=datetime.now(PACIFIC).isoformat(),
            error=f"{type(exc).__name__}: {exc}", return_code=return_code,
        )
    atomic_json(status_path, status)
    return 0 if status["state"] == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--result-name", required=True)
    parser.add_argument("--water", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
