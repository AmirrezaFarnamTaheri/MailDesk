from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from openpyxl import load_workbook

from mailmerge_app.google_sheets import snapshot_spreadsheet


class GoogleSheetChunkingTests(unittest.TestCase):
    def test_chunked_snapshot_preserves_internal_blank_row_positions(self):
        metadata = {
            "properties": {"title": "Book"},
            "sheets": [
                {
                    "properties": {
                        "title": "People",
                        "sheetType": "GRID",
                        "gridProperties": {"rowCount": 2501, "columnCount": 2},
                    }
                }
            ],
        }
        values = AsyncMock(side_effect=[
            [["Name", "Email"], ["Ada", "ada@example.com"]],
            [["Later", "later@example.com"]],
            [],
        ])
        with tempfile.TemporaryDirectory() as td, patch(
            "mailmerge_app.google_sheets.google_sheet_metadata", AsyncMock(return_value=metadata)
        ), patch("mailmerge_app.google_sheets.google_sheet_values", values):
            destination = Path(td) / "snapshot.xlsx"
            result = asyncio.run(snapshot_spreadsheet({"access_token": "token"}, "sheet-id", destination))
            self.assertEqual(result["sheets"], ["People"])
            self.assertEqual(values.await_count, 3)
            self.assertEqual(values.await_args_list[0].args[-2:], (1, 1000))
            self.assertEqual(values.await_args_list[1].args[-2:], (1001, 2000))
            self.assertEqual(values.await_args_list[2].args[-2:], (2001, 2501))

            workbook = load_workbook(destination, read_only=True, data_only=True)
            try:
                sheet = workbook["People"]
                self.assertEqual(sheet["A1"].value, "Name")
                self.assertEqual(sheet["A2"].value, "Ada")
                self.assertEqual(sheet["A1001"].value, "Later")
                self.assertIsNone(sheet["A1000"].value)
            finally:
                workbook.close()

    def test_row_limit_is_checked_before_fetching_values(self):
        metadata = {
            "properties": {"title": "Huge"},
            "sheets": [
                {
                    "properties": {
                        "title": "Too many rows",
                        "sheetType": "GRID",
                        "gridProperties": {"rowCount": 100001, "columnCount": 1},
                    }
                }
            ],
        }
        values = AsyncMock()
        with tempfile.TemporaryDirectory() as td, patch(
            "mailmerge_app.google_sheets.google_sheet_metadata", AsyncMock(return_value=metadata)
        ), patch("mailmerge_app.google_sheets.google_sheet_values", values):
            with self.assertRaisesRegex(ValueError, "100,000"):
                asyncio.run(snapshot_spreadsheet({"access_token": "token"}, "sheet-id", Path(td) / "snapshot.xlsx"))
            values.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
