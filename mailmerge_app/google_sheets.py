from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook

from .gmail_client import google_sheet_metadata, google_sheet_values


async def snapshot_spreadsheet(token: dict[str, Any], spreadsheet_id: str, destination: Path) -> dict[str, Any]:
    metadata = await google_sheet_metadata(token, spreadsheet_id)
    sheets = metadata.get("sheets", [])
    source_titles = [str(item.get("properties", {}).get("title", "")).strip() for item in sheets]
    source_titles = [title for title in source_titles if title]
    if not source_titles:
        raise ValueError("The Google spreadsheet has no readable worksheets.")

    wb = Workbook()
    wb.remove(wb.active)
    total_cells = 0
    saved_titles: list[str] = []
    used: set[str] = set()
    for source_title in source_titles:
        values = await google_sheet_values(token, spreadsheet_id, source_title)
        title = _unique_excel_title(source_title, used)
        used.add(title.casefold())
        saved_titles.append(title)
        ws = wb.create_sheet(title=title)
        for row in values:
            ws.append(list(row))
            total_cells += len(row)
            if total_cells > 1_000_000:
                wb.close()
                raise ValueError("Google Sheet snapshot exceeds the 1,000,000-cell safety limit.")
    wb.save(destination)
    wb.close()
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
