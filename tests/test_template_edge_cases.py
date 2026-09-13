from __future__ import annotations

import unittest

from mailmerge_app.template_engine import is_valid_email, render_text


class TemplateEdgeCaseTests(unittest.TestCase):
    def test_more_than_ten_independent_conditionals_render_completely(self):
        template = " ".join(f"{{{{#if K{i}}}}}V{i}{{{{/if}}}}" for i in range(25))
        row = {f"K{i}": "yes" for i in range(25)}
        rendered = render_text(template, row)
        self.assertNotIn("{{#if", rendered.text)
        self.assertNotIn("{{/if}}", rendered.text)
        for i in range(25):
            self.assertIn(f"V{i}", rendered.text)

    def test_email_domain_label_boundaries_are_rejected(self):
        self.assertFalse(is_valid_email("a@-example.com"))
        self.assertFalse(is_valid_email("a@example-.com"))
        self.assertFalse(is_valid_email(f"a@{'x' * 64}.com"))
        self.assertTrue(is_valid_email("person@example.com"))


if __name__ == "__main__":
    unittest.main()
