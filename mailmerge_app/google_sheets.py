from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import httpx
from openpyxl import Workbook

from .gmail_client import google_sheet_metadata, google_sheet_values

MAX_SNAPSHOT_CELLS = 1_000_000
MAX_SNAPSHOT_ROWS = 100_000
MAX_SNAPSHOT_COLUMNS = 1_000
MAX_CHUNK_ROWS = 1_000
MAX_CHUNK_CELLS = 250_000


async def snapshot_spreadsheet(token: dict[str, Any], spreadsheet_id: str, destination: Path) -> dict[str, Any]:
    # Reuse one connection pool for metadata plus all row chunks. Large sheets can
    # require tens or hundreds of requests; constructing a new AsyncClient for each
    # chunk repeatedly pays DNS/TLS setup costs and can exhaust ephemeral sockets.
    async with httpx.AsyncClient(timeout=60) as http:
        metadata = await google_sheet_metadata(token, spreadsheet_id, http=http)
        sheets = metadata.get("sheets", [])
        if not isinstance(sheets, list):
            raise ValueError("Google Sheets returned invalid worksheet metadata.")

        source_sheets: list[tuple[str, int, int]] = []
        for item in sheets:
            properties = item.get("properties", {}) if isinstance(item, dict) else {}
            if not isinstance(properties, dict) or properties.get("sheetType", "GRID") != "GRID":
                continue
            source_title = str(properties.get("title", "")).strip()
            if not source_title:
                continue
            grid = properties.get("gridProperties", {})
            if not isinstance(grid, dict):
                grid = {}
            # Older/mocked metadata may omit gridProperties. Use one bounded chunk as
            # a compatibility fallback rather than making an unbounded values request.
            row_count = max(1, int(grid.get("rowCount") or MAX_CHUNK_ROWS))
            column_count = max(1, int(grid.get("columnCount") or 26))
            if row_count > MAX_SNAPSHOT_ROWS:
                raise ValueError(
                    f"Worksheet {source_title!r} has {row_count:,} rows; the safety limit is {MAX_SNAPSHOT_ROWS:,}."
                )
            if column_count > MAX_SNAPSHOT_COLUMNS:
                raise ValueError(
                    f"Worksheet {source_title!r} has {column_count:,} columns; the safety limit is {MAX_SNAPSHOT_COLUMNS:,}."
                )
            source_sheets.append((source_title, row_count, column_count))
        if not source_sheets:
            raise ValueError("The Google spreadsheet has no readable grid worksheets.")

        # write_only avoids retaining up to a million cell objects in memory. Values
        # are requested in row chunks so the Google JSON response itself is bounded as
        # well; the old whole-worksheet request could exceed memory before the cell cap
        # was enforced. Save to a sibling temporary file and atomically replace the
        # previous snapshot so a failed refresh never destroys the reviewable copy.
        wb = Workbook(write_only=True)
        total_cells = 0
        saved_titles: list[str] = []
        used: set[str] = set()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            for source_title, row_count, column_count in source_sheets:
                title = _unique_excel_title(source_title, used)
                used.add(title.casefold())
                saved_titles.append(title)
                ws = wb.create_sheet(title=title)

                rows_per_chunk = max(1, min(MAX_CHUNK_ROWS, MAX_CHUNK_CELLS // max(column_count, 1)))
                pending_blank_rows = 0
                for start_row in range(1, row_count + 1, rows_per_chunk):
                    end_row = min(row_count, start_row + rows_per_chunk - 1)
                    values = await google_sheet_values(
                        token,
                        spreadsheet_id,
                        source_title,
                        start_row,
                        end_row,
                        http=http,
                    )
                    expected_rows = end_row - start_row + 1
                    if len(values) > expected_rows:
                        raise ValueError("Google Sheets returned more rows than requested.")

                    for offset in range(expected_rows):
                        raw_row = values[offset] if offset < len(values) else []
                        if not isinstance(raw_row, list):
                            raise ValueError("Google Sheets returned an invalid row payload.")
                        if len(raw_row) > column_count:
                            raise ValueError("Google Sheets returned more columns than worksheet metadata allows.")
                        cells = list(raw_row)
                        total_cells += len(cells)
                        if total_cells > MAX_SNAPSHOT_CELLS:
                            raise ValueError(f"Google Sheet snapshot exceeds the {MAX_SNAPSHOT_CELLS:,}-cell safety limit.")

                        if any(cell not in (None, "") for cell in cells):
                            # Google omits trailing empty rows from each values range. We
                            # defer blank rows so internal gaps keep their original row
                            # numbers while truly trailing blank grid rows are not saved.
                            while pending_blank_rows:
                                ws.append([])
                                pending_blank_rows -= 1
                            ws.append(cells)
                        else:
                            pending_blank_rows += 1

            wb.save(temporary)
            os.replace(temporary, destination)
        finally:
            wb.close()
            temporary.unlink(missing_ok=True)

    properties = metadata.get("properties", {})
    title = properties.get("title", "Google Sheet") if isinstance(properties, dict) else "Google Sheet"
    return {
        "title": title,
        "sheets": saved_titles,
        "total_cells": total_cells,
    }


def _unique_excel_title(source: str, used: set[str]) -> str:
    safe = "".join("_" if ch in "[]:*?/\\" else ch for ch in source).strip() or "Sheet"
    base = safe[:31]
    candidate = base
    counter = 2
    while candidate.casefold() in used:
        suffix = f" ({counter})"
        candidate = base[: 31 - len(suffix)] + suffix
        counter += 1
    return candidate
