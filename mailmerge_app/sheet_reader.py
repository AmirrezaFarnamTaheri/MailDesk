from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import Counter
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .template_engine import is_valid_email

MAX_ROWS = 100_000
MAX_COLUMNS = 1_000
MAX_CELLS = 2_000_000
MAX_CELL_CHARS = 20_000
MAX_CSV_FIELD_BYTES = 2 * 1024 * 1024
MAX_CSV_COLUMNS = MAX_COLUMNS
MAX_XLSX_ARCHIVE_MEMBERS = 10_000
MAX_XLSX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_XLSX_MEMBER_BYTES = 192 * 1024 * 1024
HEADER_SCAN_ROWS = 25


def _validate_xlsx_archive(path: Path) -> None:
    """Reject obviously dangerous/corrupt OOXML archives before openpyxl parses XML."""
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_XLSX_ARCHIVE_MEMBERS:
                raise ValueError(
                    f"Workbook archive contains too many files ({len(members):,}); limit is {MAX_XLSX_ARCHIVE_MEMBERS:,}."
                )
            expanded = 0
            for member in members:
                if member.flag_bits & 0x1:
                    raise ValueError("Encrypted workbook archives are not supported.")
                if member.file_size < 0 or member.file_size > MAX_XLSX_MEMBER_BYTES:
                    raise ValueError(
                        f"Workbook archive member {member.filename!r} is too large when expanded."
                    )
                expanded += member.file_size
                if expanded > MAX_XLSX_UNCOMPRESSED_BYTES:
                    raise ValueError(
                        f"Workbook expands beyond the {MAX_XLSX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB safety limit."
                    )
    except zipfile.BadZipFile as exc:
        raise ValueError("The workbook is not a valid XLSX/ZIP file.") from exc


def list_sheets(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        _validate_xlsx_archive(path)
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            return list(wb.sheetnames)
        finally:
            wb.close()
    if suffix == ".csv":
        return ["CSV"]
    raise ValueError("Unsupported spreadsheet format. Use .xlsx, .xlsm, or .csv.")


def table(path: Path, sheet: str, header_row: int | None = None) -> tuple[list[str], list[dict[str, str]], int]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        if sheet != "CSV":
            raise ValueError("CSV imports only contain the CSV sheet.")
        rows = _csv_rows(path)
        detected = header_row or _detect_header(rows)
        return _tabular(rows, detected)

    _validate_xlsx_archive(path)
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet not in wb.sheetnames:
            raise ValueError("Worksheet not found.")
        ws = wb[sheet]
        if ws.max_column and ws.max_column > MAX_COLUMNS:
            raise ValueError(f"Worksheet has {ws.max_column:,} columns; the safety limit is {MAX_COLUMNS:,}.")
        if ws.max_row and ws.max_row > MAX_ROWS + 1_000:
            # The extra allowance lets header detection tolerate leading title rows
            # without allowing an effectively unbounded sheet.
            raise ValueError(f"Worksheet has {ws.max_row:,} rows; the safety limit is about {MAX_ROWS:,} data rows.")
        if ws.max_row and ws.max_column and ws.max_row * ws.max_column > MAX_CELLS:
            raise ValueError(f"Worksheet exceeds the {MAX_CELLS:,}-cell safety limit.")
        values: list[list[Any]] = []
        for index, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if index > MAX_ROWS + 1_000:
                raise ValueError(f"Worksheet exceeds the {MAX_ROWS:,}-row safety limit.")
            cells = list(row[:MAX_COLUMNS])
            values.append(cells)
            if len(values) * max(1, ws.max_column or len(cells)) > MAX_CELLS:
                raise ValueError(f"Worksheet exceeds the {MAX_CELLS:,}-cell safety limit.")
        detected = header_row or _detect_header(values)
        return _tabular(values, detected)
    finally:
        wb.close()


def _csv_rows(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    # utf-8-sig must be attempted before plain utf-8. A BOM is valid UTF-8, so
    # trying utf-8 first succeeds but leaves U+FEFF attached to the first header,
    # which breaks mapping/suggestion logic for common Excel-exported CSVs.
    text: str | None = None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("CSV encoding is not supported. Use UTF-8 or Windows-1252.")
    sample = text[:64_000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    delimiter = getattr(dialect, "delimiter", ",") or ","
    # Reject wildly wide input before the csv module materializes a giant row.
    if raw.count(delimiter.encode("utf-8")) > (MAX_CSV_COLUMNS * (MAX_ROWS + 100)):
        raise ValueError("CSV appears to exceed the row/column safety limits.")
    old_limit = csv.field_size_limit()
    csv.field_size_limit(MAX_CSV_FIELD_BYTES)
    try:
        reader = csv.reader(io.StringIO(text), dialect)
        rows: list[list[str]] = []
        for index, row in enumerate(reader, start=1):
            if index > MAX_ROWS + 100:
                raise ValueError(f"CSV exceeds the {MAX_ROWS:,}-row safety limit.")
            if len(row) > MAX_CSV_COLUMNS:
                raise ValueError(f"CSV has more than {MAX_CSV_COLUMNS:,} columns.")
            rows.append(row)
            if len(rows) * max((len(item) for item in rows[-100:]), default=0) > MAX_CELLS:
                raise ValueError(f"CSV exceeds the {MAX_CELLS:,}-cell safety limit.")
        return rows
    except csv.Error as exc:
        raise ValueError(f"Could not parse CSV: {exc}") from exc
    finally:
        csv.field_size_limit(old_limit)


def _detect_header(rows: list[list[Any]]) -> int:
    if not rows:
        return 1
    best_index = 0
    best_score = float("-inf")
    for idx, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        cells = [_safe_text(value).strip() for value in row]
        nonempty = [cell for cell in cells if cell]
        if not nonempty:
            continue
        unique = len(set(cell.casefold() for cell in nonempty))
        textish = sum(not _looks_numeric(cell) for cell in nonempty)
        next_rows = rows[idx + 1 : idx + 6]
        next_nonempty = sum(sum(bool(_safe_text(value).strip()) for value in candidate) for candidate in next_rows)
        score = len(nonempty) * 4 + unique * 2 + textish + min(next_nonempty, len(nonempty) * 3) - idx * 0.25
        if score > best_score:
            best_index = idx
            best_score = score
    return best_index + 1


def _tabular(values: list[list[Any]], header_row: int) -> tuple[list[str], list[dict[str, str]], int]:
    if header_row < 1 or header_row > len(values):
        raise ValueError("Header row is outside the spreadsheet.")
    raw_headers = [_safe_text(value).strip() for value in values[header_row - 1]]
    while raw_headers and not raw_headers[-1]:
        raw_headers.pop()
    if not raw_headers:
        raise ValueError("The selected header row is blank.")
    if len(raw_headers) > MAX_COLUMNS:
        raise ValueError(f"Spreadsheet has more than {MAX_COLUMNS:,} columns.")

    headers: list[str] = []
    seen: Counter[str] = Counter()
    for index, value in enumerate(raw_headers, start=1):
        base = value or f"Column {index}"
        seen[base.casefold()] += 1
        count = seen[base.casefold()]
        headers.append(base if count == 1 else f"{base} ({count})")

    rows: list[dict[str, str]] = []
    for row_index, raw in enumerate(values[header_row:], start=header_row + 1):
        row: dict[str, str] = {"_row": str(row_index)}
        has_value = False
        for column_index, header in enumerate(headers):
            value = _safe_text(raw[column_index] if column_index < len(raw) else "")
            if len(value) > MAX_CELL_CHARS:
                raise ValueError(
                    f"Cell {header} in row {row_index} exceeds the {MAX_CELL_CHARS:,}-character safety limit."
                )
            row[header] = value
            has_value = has_value or bool(value.strip())
        if has_value:
            rows.append(row)
            if len(rows) > MAX_ROWS:
                raise ValueError(f"Spreadsheet exceeds the {MAX_ROWS:,}-data-row safety limit.")
    return headers, rows, header_row


def suggest_mappings(headers: list[str], rows: list[dict[str, str]]) -> dict[str, str]:
    suggestions: dict[str, str] = {}
    name_patterns = {
        "to": [r"(^|\b)e[-_ ]?mail( address)?($|\b)", r"(^|\b)recipient($|\b)", r"ایمیل", r"پست.*الکترون"],
        "name": [r"(^|\b)(full )?name($|\b)", r"نام( دانشجو)?"],
        "cc": [r"(^|\b)cc($|\b)"],
        "bcc": [r"(^|\b)bcc($|\b)"],
        "attachment": [r"attach", r"فایل", r"پیوست"],
        "status": [r"status", r"state", r"وضعیت"],
    }
    for target, patterns in name_patterns.items():
        for header in headers:
            if any(re.search(pattern, header, re.IGNORECASE) for pattern in patterns):
                suggestions[target] = header
                break

    if "to" not in suggestions:
        best: tuple[float, str] = (0.0, "")
        sample = rows[:100]
        for header in headers:
            values = [row.get(header, "").strip() for row in sample if row.get(header, "").strip()]
            if not values:
                continue
            ratio = sum(is_valid_email(value) for value in values) / len(values)
            if ratio > best[0]:
                best = (ratio, header)
        if best[0] >= 0.6:
            suggestions["to"] = best[1]
    return suggestions


def column_profiles(headers: list[str], rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for header in headers:
        values = [row.get(header, "") for row in rows]
        nonempty = [value for value in values if value.strip()]
        unique = len(set(nonempty))
        profiles[header] = {
            "non_empty": len(nonempty),
            "unique": unique,
            "sample": nonempty[:5],
            "email_ratio": (sum(is_valid_email(value.strip()) for value in nonempty[:100]) / min(len(nonempty), 100)) if nonempty else 0,
        }
    return profiles


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, (date, time)):
        return value.isoformat()
    return str(value)


def _looks_numeric(value: str) -> bool:
    try:
        float(value.replace(",", ""))
        return True
    except ValueError:
        return False
