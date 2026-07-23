#!/usr/bin/env python3
"""Convert the schedule-authoring XLSX workbook into the canonical CSV."""

from __future__ import annotations

import argparse
import csv
import math
import os
import tempfile
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

try:
    from .cta_operational_states import EXPECTED_STATES_BY_ACTION
    from .schedule_parser import SCHEDULE_COLUMNS, load_schedule
except ImportError:
    from cta_operational_states import EXPECTED_STATES_BY_ACTION
    from schedule_parser import SCHEDULE_COLUMNS, load_schedule


MAIN_SHEET_NAME = "conformance_test_schedule_main"
SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOCUMENT_REL_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

class XlsxScheduleError(ValueError):
    """Raised when the authoring workbook cannot be converted safely."""


def _column_index(cell_reference: str) -> int:
    letters = "".join(character for character in cell_reference if character.isalpha())
    result = 0
    for character in letters.upper():
        result = result * 26 + ord(character) - ord("A") + 1
    return result - 1


def _read_xml(archive: zipfile.ZipFile, member: str) -> ElementTree.Element:
    try:
        with archive.open(member) as handle:
            return ElementTree.parse(handle).getroot()
    except KeyError as exc:
        raise XlsxScheduleError(f"workbook is missing required file '{member}'") from exc
    except ElementTree.ParseError as exc:
        raise XlsxScheduleError(f"invalid workbook XML in '{member}'") from exc


def _shared_strings(
    archive: zipfile.ZipFile,
) -> list[str]:
    try:
        root = _read_xml(archive, "xl/sharedStrings.xml")
    except XlsxScheduleError:
        return []
    return [
        "".join(text.text or "" for text in item.iter(f"{{{SPREADSHEET_NS}}}t"))
        for item in root.findall(f"{{{SPREADSHEET_NS}}}si")
    ]


def _worksheet_path(archive: zipfile.ZipFile, sheet_name: str) -> str:
    workbook = _read_xml(archive, "xl/workbook.xml")
    relationships = _read_xml(archive, "xl/_rels/workbook.xml.rels")
    relationship_targets = {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in relationships.findall(
            f"{{{PACKAGE_REL_NS}}}Relationship"
        )
    }
    for sheet in workbook.findall(
        f".//{{{SPREADSHEET_NS}}}sheet"
    ):
        if sheet.attrib.get("name") != sheet_name:
            continue
        relationship_id = sheet.attrib.get(f"{{{DOCUMENT_REL_NS}}}id")
        target = relationship_targets.get(relationship_id or "")
        if not target:
            break
        if target.startswith("/"):
            return target.lstrip("/")
        return str(PurePosixPath("xl") / target)
    raise XlsxScheduleError(f"workbook must contain a sheet named '{sheet_name}'")


def _cell_value(
    cell: ElementTree.Element,
    shared_strings: list[str],
) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return "".join(
            text.text or "" for text in cell.iter(f"{{{SPREADSHEET_NS}}}t")
        )
    value_node = cell.find(f"{{{SPREADSHEET_NS}}}v")
    if value_node is None or value_node.text is None:
        return ""
    value = value_node.text
    if cell_type == "s":
        try:
            return shared_strings[int(value)]
        except (IndexError, ValueError) as exc:
            raise XlsxScheduleError("workbook contains an invalid shared string") from exc
    if cell_type == "b":
        return "TRUE" if value == "1" else "FALSE"
    return value


def _read_rows(path: Path, sheet_name: str) -> list[list[str]]:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise XlsxScheduleError(f"cannot open XLSX workbook: {path}") from exc
    with archive:
        shared_strings = _shared_strings(archive)
        worksheet = _read_xml(archive, _worksheet_path(archive, sheet_name))
        rows: list[list[str]] = []
        for row in worksheet.findall(f".//{{{SPREADSHEET_NS}}}row"):
            values = [""] * len(SCHEDULE_COLUMNS)
            for cell in row.findall(f"{{{SPREADSHEET_NS}}}c"):
                index = _column_index(cell.attrib.get("r", ""))
                if 0 <= index < len(values):
                    values[index] = _cell_value(cell, shared_strings)
            rows.append(values)
        return rows


def _plain_number(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    try:
        number = float(stripped)
    except ValueError:
        return stripped
    if not math.isfinite(number):
        return stripped
    if number.is_integer():
        return str(int(number))
    return format(number, ".15g")


def _elapsed_time(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    if ":" in stripped:
        return stripped
    try:
        excel_days = float(stripped)
    except ValueError:
        return stripped
    if not math.isfinite(excel_days) or excel_days < 0:
        return stripped
    total_seconds = round(excel_days * 24 * 60 * 60)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def workbook_rows(
    workbook_path: Path | str,
    *,
    sheet_name: str = MAIN_SHEET_NAME,
) -> list[dict[str, str]]:
    """Read active schedule rows and derive formula-backed metadata."""
    path = Path(workbook_path)
    rows = _read_rows(path, sheet_name)
    if not rows:
        raise XlsxScheduleError("schedule worksheet is empty")
    headers = tuple(value.strip() for value in rows[0])
    if headers != SCHEDULE_COLUMNS:
        raise XlsxScheduleError(
            "XLSX columns must exactly match: "
            + ",".join(SCHEDULE_COLUMNS)
            + "\nfound: "
            + ",".join(headers)
        )

    action_counts: Counter[str] = Counter()
    canonical_rows: list[dict[str, str]] = []
    for source_row, values in enumerate(rows[1:], start=2):
        raw = dict(zip(SCHEDULE_COLUMNS, values))
        action = raw["action"].strip().lower()
        if not action:
            continue

        action_counts[action] += 1
        if action == "end":
            event_id = "test_end"
            event_type = "test"
        elif action == "water_draw":
            event_id = f"water_draw_{action_counts[action]}"
            event_type = "water_draw"
        else:
            event_id = f"{action}_{action_counts[action]}"
            event_type = "cta"

        expected_states = EXPECTED_STATES_BY_ACTION.get(action, ())
        row = {
            "enabled": raw["enabled"].strip(),
            "event_id": event_id,
            "time_after_start": _elapsed_time(raw["time_after_start"]),
            "phase": raw["phase"].strip(),
            "event_type": event_type,
            "action": action,
            "event_duration_minutes": _plain_number(
                raw["event_duration_minutes"]
            ).lower(),
            "advanced_duration_minutes": _plain_number(
                raw["advanced_duration_minutes"]
            ),
            "advanced_value": _plain_number(raw["advanced_value"]),
            "advanced_units": raw["advanced_units"].strip().lower(),
            "expected_operational_states": "|".join(
                str(state) for state in expected_states
            ),
            "target_volume_gal": _plain_number(raw["target_volume_gal"]),
            "expected_flow_gpm": _plain_number(raw["expected_flow_gpm"]),
            "notes": raw["notes"].strip(),
        }
        canonical_rows.append(row)

    if not canonical_rows:
        raise XlsxScheduleError("schedule worksheet contains no actions")
    return canonical_rows


def import_xlsx_schedule(
    workbook_path: Path | str,
    output_csv: Path | str,
    *,
    sheet_name: str = MAIN_SHEET_NAME,
) -> Path:
    """Generate and validate the canonical schedule CSV atomically."""
    destination = Path(output_csv)
    rows = workbook_rows(workbook_path, sheet_name=sheet_name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=SCHEDULE_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        load_schedule(temporary_path)
        os.replace(temporary_path, destination)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("output_csv", type=Path)
    parser.add_argument("--sheet-name", default=MAIN_SHEET_NAME)
    args = parser.parse_args()
    try:
        destination = import_xlsx_schedule(
            args.workbook,
            args.output_csv,
            sheet_name=args.sheet_name,
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{type(exc).__name__}: {exc}\n")
    print(f"CANONICAL_SCHEDULE {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
