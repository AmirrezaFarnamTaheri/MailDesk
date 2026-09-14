from __future__ import annotations
import unittest
from fastapi import HTTPException
from mailmerge_app.main import RenderRequest, _render_row, _validate_mapping_columns

class PlaceholderMappingTests(unittest.TestCase):
    def _payload(self, **changes):
        values = dict(import_id="import", sheet="Sheet1", to_column="Email", subject="Hello {{First}}", body="Welcome to {{Company}}.", placeholder_mappings={"First": "Full Name", "Company": "Organisation"})
        values.update(changes)
        return RenderRequest(**values)

    def test_placeholder_can_map_to_differently_named_column(self):
        message = _render_row(self._payload(), {"_row": "2", "Email": "ada@example.com", "Full Name": "Ada", "Organisation": "Analytical Engines"}, {}, {})
        self.assertEqual(message["subject"], "Hello Ada")
        self.assertEqual(message["body"], "Welcome to Analytical Engines.")
        self.assertEqual(message["errors"], [])

    def test_mapping_target_must_exist(self):
        with self.assertRaises(HTTPException):
            _validate_mapping_columns(self._payload(placeholder_mappings={"First": "Missing"}), ["Email", "Full Name"])
