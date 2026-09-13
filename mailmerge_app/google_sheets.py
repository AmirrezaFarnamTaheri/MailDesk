from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from .gmail_client import google_sheet_metadata, google_sheet_values

MAX_SNAPSHOT_CELLS = 1_000_000


async def snapshot_spreadsheet(token: dict[str, Any], spreadsheet_id: str, destination: Path) -> dict[str, Any]:
    metadata = await google_sheet_metadata(token, spreadsheet_id)
    sheets = metadata.get("sheets", [])
    source_titles = [str(item.get("properties", {}).get("title", "")).strip() for item in sheets]
    source_titles = [title for title in source_titles if title]
    if not source_titles:
        raise ValueError("The Google spreadsheet has no readable worksheets.")

    # write_only avoids retaining up to a million cell objects in memory. Save to a
    # sibling temporary file and atomically replace the previous snapshot so a
    # failed refresh never destroys the last reviewable copy.
    wb = Workbook(write_only=True)
    total_cells = 0
    saved_titles: list[str] = []
    used: set[str] = set()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        for source_title in source_titles:
            values = await google_sheet_values(token, spreadsheet_id, source_title)
            title = _unique_excel_title(source_title, used)
            used.add(title.casefold())
            saved_titles.append(title)
            ws = wb.create_sheet(title=title)
            for row in values:
                cells = list(row)
                total_cells += len(cells)
                if total_cells > MAX_SNAPSHOT_CELLS:
                    raise ValueError(f"Google Sheet snapshot exceeds the {MAX_SNAPSHOT_CELLS:,}-cell safety limit.")
                ws.append(cells)
        wb.save(temporary)
        os.replace(temporary, destination)
    finally:
        wb.close()
        temporary.unlink(missing_ok=True)

    return {
        "title": metadata.get("properties", {}).get("title", "Google Sheet"),
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
