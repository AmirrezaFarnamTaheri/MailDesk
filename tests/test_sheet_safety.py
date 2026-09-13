from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mailmerge_app.sheet_reader import MAX_COLUMNS, table


class SheetSafetyTests(unittest.TestCase):
    def test_semicolon_delimited_csv_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "contacts.csv"
            path.write_text("Name;Email;Status\nAda;ada@example.com;Ready\n", encoding="utf-8")
            headers, rows, header = table(path, "contacts", 1)
            self.assertEqual(header, 1)
            self.assertEqual(headers, ["Name", "Email", "Status"])
            self.assertEqual(rows[0]["Email"], "ada@example.com")

    def test_pathologically_wide_csv_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "wide.csv"
            path.write_text(",".join(f"c{i}" for i in range(MAX_COLUMNS + 1)) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "column safety limit"):
                table(path, "wide", 1)


if __name__ == "__main__":
    unittest.main()
