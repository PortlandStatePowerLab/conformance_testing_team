#!/usr/bin/env python3
"""Build a concise, human-readable workbook from one conformance run."""

from __future__ import annotations

import argparse
import csv
import math
import os
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree


REPORT_FILENAME = "conformance_test_report.xlsx"
TIMELINE_COLUMNS = (
    "timestamp_pacific",
    "operational_state",
    "operational_state_name",
    "event",
    "command",
    "result",
    "voltage_rms",
    "current_rms",
    "real_power",
    "reactive_power",
    "apparent_power",
    "power_factor",
    "accumulated_volume_gal",
    "flow_gpm",
    "hot_temp_c",
    "hot_temp_f",
    "cold_temp_c",
    "cold_temp_f",
    "ambient_temp_c",
    "ambient_temp_f",
)
POWER_COLUMNS = (
    "voltage_rms",
    "current_rms",
    "real_power",
    "reactive_power",
    "apparent_power",
    "power_factor",
)
WATER_COLUMNS = (
    "accumulated_volume_gal",
    "flow_gpm",
    "hot_temp_c",
    "hot_temp_f",
    "cold_temp_c",
    "cold_temp_f",
    "ambient_temp_c",
    "ambient_temp_f",
)
CTA_LIFECYCLE_EVENTS = {
    "controller_started",
    "serial_open",
    "communication_started",
    "communication_stopped",
    "controller_stopped",
}
CTA_COMMAND_EVENTS = {"command_sent", "command_completed"}
ORCHESTRATOR_WATER_EVENTS = {"water_draw_started", "water_draw_completed"}

SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELATIONSHIP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_RELATIONSHIP_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _read_csv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise FileNotFoundError(f"required report source not found: {path}")
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _number(value: str | None) -> float | int | str:
    stripped = (value or "").strip()
    if not stripped:
        return ""
    try:
        parsed = float(stripped)
    except ValueError:
        return stripped
    if not math.isfinite(parsed):
        return stripped
    if parsed.is_integer() and "." not in stripped:
        return int(parsed)
    return parsed


def _timeline_row(timestamp: str) -> dict[str, Any]:
    row = {column: "" for column in TIMELINE_COLUMNS}
    row["timestamp_pacific"] = timestamp
    return row


def _timestamp_key(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timeline timestamp must include a UTC offset: {value}")
    return parsed


def _cta_timeline_rows(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    previous_state: str | None = None
    for source in _read_csv(path):
        event = source.get("event", "")
        state = source.get("operational_state", "").strip()
        state_changed = event == "operational_state" and state != previous_state
        if event == "operational_state":
            previous_state = state
        failure = any(
            token in source.get("result", "").lower()
            for token in ("fail", "nak", "timeout", "no_ack", "error")
        )
        if not (
            event in CTA_LIFECYCLE_EVENTS
            or event in CTA_COMMAND_EVENTS
            or state_changed
            or failure
        ):
            continue
        row = _timeline_row(source.get("timestamp_pacific", ""))
        row.update(
            {
                "operational_state": _number(state),
                "operational_state_name": source.get(
                    "operational_state_name", ""
                ),
                "event": event,
                "command": source.get("command", ""),
                "result": source.get("result", ""),
            }
        )
        result.append(row)
    return result


def _power_timeline_rows(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in _read_csv(path):
        if source.get("status") != "ok":
            continue
        reasons = {
            reason for reason in source.get("record_reason", "").split("|") if reason
        }
        if reasons == {"heartbeat"}:
            continue
        row = _timeline_row(source.get("timestamp_pacific", ""))
        for column in POWER_COLUMNS:
            row[column] = _number(source.get(column))
        result.append(row)
    return result


def _sample_water_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if not rows:
        return []
    selected_indexes = set(range(0, len(rows), 4))
    selected_indexes.add(len(rows) - 1)
    return [rows[index] for index in sorted(selected_indexes)]


def _water_timeline_rows(run_directory: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted(run_directory.glob("water_draw_*.csv")):
        for source in _sample_water_rows(_read_csv(path)):
            row = _timeline_row(source.get("timestamp_pacific", ""))
            for column in WATER_COLUMNS:
                row[column] = _number(source.get(column))
            result.append(row)
    return result


def _water_event_rows(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in _read_csv(path, required=False):
        event = source.get("event", "")
        if event not in ORCHESTRATOR_WATER_EVENTS:
            continue
        row = _timeline_row(source.get("timestamp_pacific", ""))
        row.update(
            {
                "event": event,
                "command": source.get("event_id", ""),
                "result": source.get("status", ""),
            }
        )
        result.append(row)
    return result


def build_timeline(run_directory: Path | str) -> list[dict[str, Any]]:
    """Return selected CTA, power, and water records in chronological order."""
    directory = Path(run_directory)
    rows = (
        _cta_timeline_rows(directory / "cta_events.csv")
        + _power_timeline_rows(directory / "power.csv")
        + _water_timeline_rows(directory)
        + _water_event_rows(directory / "orchestrator_events.csv")
    )
    indexed = list(enumerate(rows))
    indexed.sort(
        key=lambda item: (
            _timestamp_key(str(item[1]["timestamp_pacific"])),
            item[0],
        )
    )
    return [row for _, row in indexed]


def _first_number(rows: list[dict[str, str]], column: str) -> float | str:
    values = [_number(row.get(column)) for row in rows]
    return next((value for value in values if value != ""), "")


def _numeric_values(rows: list[dict[str, str]], column: str) -> list[float]:
    result: list[float] = []
    for row in rows:
        value = _number(row.get(column))
        if isinstance(value, (int, float)):
            result.append(float(value))
    return result


def build_commodity_summary(path: Path | str) -> list[dict[str, Any]]:
    """Summarize useful commodity values without adding minute-level clutter."""
    rows = _read_csv(Path(path), required=False)
    summary: list[tuple[str, Any]] = []
    cumulative = _numeric_values(rows, "cumulative_electricity_Wh")
    if cumulative:
        summary.extend(
            [
                ("cumulative_electricity_start_Wh", cumulative[0]),
                ("cumulative_electricity_end_Wh", cumulative[-1]),
                ("cumulative_electricity_change_Wh", cumulative[-1] - cumulative[0]),
            ]
        )
    fields = (
        ("total_energy_storage_Wh", False),
        ("present_energy_storage_Wh", True),
        ("advanced_total_energy_storage_Wh", False),
        ("advanced_present_energy_storage_Wh", True),
    )
    for column, variable in fields:
        values = _numeric_values(rows, column)
        if not values:
            summary.append((column, ""))
        elif not variable:
            summary.append((column, _first_number(rows, column)))
        else:
            summary.extend(
                [
                    (f"{column.removesuffix('_Wh')}_start_Wh", values[0]),
                    (f"{column.removesuffix('_Wh')}_end_Wh", values[-1]),
                    (f"{column.removesuffix('_Wh')}_minimum_Wh", min(values)),
                    (f"{column.removesuffix('_Wh')}_maximum_Wh", max(values)),
                ]
            )
    return [{"metric": metric, "value": value} for metric, value in summary]


def _table_from_csv(path: Path, *, required: bool = True) -> tuple[list[str], list[list[Any]]]:
    rows = _read_csv(path, required=required)
    if not rows:
        return [], []
    columns = list(rows[0])
    return columns, [[row.get(column, "") for column in columns] for row in rows]


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _xml_bytes(element: ElementTree.Element) -> bytes:
    return ElementTree.tostring(element, encoding="utf-8", xml_declaration=True)


def _worksheet_xml(headers: list[str], rows: Iterable[list[Any]]) -> bytes:
    worksheet = ElementTree.Element(f"{{{SPREADSHEET_NS}}}worksheet")
    views = ElementTree.SubElement(worksheet, f"{{{SPREADSHEET_NS}}}sheetViews")
    view = ElementTree.SubElement(views, f"{{{SPREADSHEET_NS}}}sheetView", workbookViewId="0")
    ElementTree.SubElement(
        view,
        f"{{{SPREADSHEET_NS}}}pane",
        ySplit="1",
        topLeftCell="A2",
        activePane="bottomLeft",
        state="frozen",
    )
    all_rows = [headers] + list(rows)
    widths = [len(str(header)) for header in headers]
    for row in all_rows[1:]:
        for index, value in enumerate(row):
            if index < len(widths):
                widths[index] = min(max(widths[index], len(str(value))), 40)
    columns = ElementTree.SubElement(worksheet, f"{{{SPREADSHEET_NS}}}cols")
    for index, width in enumerate(widths, start=1):
        ElementTree.SubElement(
            columns,
            f"{{{SPREADSHEET_NS}}}col",
            min=str(index),
            max=str(index),
            width=str(max(width + 2, 10)),
            customWidth="1",
        )
    sheet_data = ElementTree.SubElement(worksheet, f"{{{SPREADSHEET_NS}}}sheetData")
    for row_index, values in enumerate(all_rows, start=1):
        row_element = ElementTree.SubElement(
            sheet_data, f"{{{SPREADSHEET_NS}}}row", r=str(row_index)
        )
        for column_index, value in enumerate(values, start=1):
            if value == "" or value is None:
                continue
            reference = f"{_column_name(column_index)}{row_index}"
            attributes = {"r": reference}
            if row_index == 1:
                attributes["s"] = "1"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cell = ElementTree.SubElement(
                    row_element, f"{{{SPREADSHEET_NS}}}c", **attributes
                )
                ElementTree.SubElement(cell, f"{{{SPREADSHEET_NS}}}v").text = str(value)
            else:
                attributes["t"] = "inlineStr"
                cell = ElementTree.SubElement(
                    row_element, f"{{{SPREADSHEET_NS}}}c", **attributes
                )
                inline = ElementTree.SubElement(cell, f"{{{SPREADSHEET_NS}}}is")
                ElementTree.SubElement(inline, f"{{{SPREADSHEET_NS}}}t").text = str(value)
    if headers:
        ElementTree.SubElement(
            worksheet,
            f"{{{SPREADSHEET_NS}}}autoFilter",
            ref=f"A1:{_column_name(len(headers))}{len(all_rows)}",
        )
    return _xml_bytes(worksheet)


def _write_workbook(
    destination: Path,
    sheets: list[tuple[str, list[str], list[list[Any]]]],
) -> None:
    ElementTree.register_namespace("", SPREADSHEET_NS)
    ElementTree.register_namespace("r", RELATIONSHIP_NS)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        with zipfile.ZipFile(temporary_path, "w", zipfile.ZIP_DEFLATED) as archive:
            types = ElementTree.Element(
                "Types",
                xmlns="http://schemas.openxmlformats.org/package/2006/content-types",
            )
            ElementTree.SubElement(types, "Default", Extension="rels", ContentType="application/vnd.openxmlformats-package.relationships+xml")
            ElementTree.SubElement(types, "Default", Extension="xml", ContentType="application/xml")
            ElementTree.SubElement(types, "Override", PartName="/xl/workbook.xml", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml")
            ElementTree.SubElement(types, "Override", PartName="/xl/styles.xml", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml")
            for index in range(1, len(sheets) + 1):
                ElementTree.SubElement(types, "Override", PartName=f"/xl/worksheets/sheet{index}.xml", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml")
            archive.writestr("[Content_Types].xml", _xml_bytes(types))

            relationships = ElementTree.Element("Relationships", xmlns=PACKAGE_RELATIONSHIP_NS)
            ElementTree.SubElement(relationships, "Relationship", Id="rId1", Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", Target="xl/workbook.xml")
            archive.writestr("_rels/.rels", _xml_bytes(relationships))

            workbook = ElementTree.Element(f"{{{SPREADSHEET_NS}}}workbook")
            sheet_nodes = ElementTree.SubElement(workbook, f"{{{SPREADSHEET_NS}}}sheets")
            workbook_relationships = ElementTree.Element("Relationships", xmlns=PACKAGE_RELATIONSHIP_NS)
            for index, (name, _, _) in enumerate(sheets, start=1):
                ElementTree.SubElement(sheet_nodes, f"{{{SPREADSHEET_NS}}}sheet", name=name, sheetId=str(index), **{f"{{{RELATIONSHIP_NS}}}id": f"rId{index}"})
                ElementTree.SubElement(workbook_relationships, "Relationship", Id=f"rId{index}", Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet", Target=f"worksheets/sheet{index}.xml")
            style_id = len(sheets) + 1
            ElementTree.SubElement(workbook_relationships, "Relationship", Id=f"rId{style_id}", Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles", Target="styles.xml")
            archive.writestr("xl/workbook.xml", _xml_bytes(workbook))
            archive.writestr("xl/_rels/workbook.xml.rels", _xml_bytes(workbook_relationships))

            styles = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="{SPREADSHEET_NS}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs></styleSheet>'''
            archive.writestr("xl/styles.xml", styles)
            for index, (_, headers, rows) in enumerate(sheets, start=1):
                archive.writestr(
                    f"xl/worksheets/sheet{index}.xml",
                    _worksheet_xml(headers, rows),
                )
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def generate_conformance_report(
    run_directory: Path | str,
    *,
    output_path: Path | str | None = None,
) -> Path:
    """Generate the final report workbook and return its path."""
    directory = Path(run_directory).resolve()
    if not directory.is_dir():
        raise NotADirectoryError(f"run directory not found: {directory}")
    destination = (
        Path(output_path).resolve()
        if output_path is not None
        else directory / REPORT_FILENAME
    )
    destination.parent.mkdir(parents=True, exist_ok=True)

    timeline = build_timeline(directory)
    device_headers, device_rows = _table_from_csv(
        directory / "cta_device_information.csv"
    )
    schedule_headers, schedule_rows = _table_from_csv(
        directory / "master_schedule.csv"
    )
    commodity = build_commodity_summary(directory / "cta_commodity.csv")
    sheets = [
        (
            "Event Timeline",
            list(TIMELINE_COLUMNS),
            [[row[column] for column in TIMELINE_COLUMNS] for row in timeline],
        ),
        ("Device Information", device_headers, device_rows),
        ("Master Schedule", schedule_headers, schedule_rows),
        (
            "Commodity Summary",
            ["metric", "value"],
            [[row["metric"], row["value"]] for row in commodity],
        ),
    ]
    _write_workbook(destination, sheets)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = generate_conformance_report(
            args.run_directory,
            output_path=args.output,
        )
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f"CONFORMANCE_REPORT_ERROR {type(exc).__name__}: {exc}\n")
    print(f"CONFORMANCE_REPORT {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
