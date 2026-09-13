from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryIntegrityTests(unittest.TestCase):
    def test_runtime_dependencies_match_pyproject(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        pyproject_dependencies = [str(item).strip() for item in project.get("dependencies", [])]
        requirements = [
            line.strip()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(requirements, pyproject_dependencies)

    def test_version_is_consistent_across_runtime_and_packaging(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        expected = str(project["version"])

        init_text = (ROOT / "mailmerge_app" / "__init__.py").read_text(encoding="utf-8")
        main_text = (ROOT / "mailmerge_app" / "main.py").read_text(encoding="utf-8")
        installer_text = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")

        init_match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', init_text, re.M)
        main_match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', main_text, re.M)
        installer_match = re.search(r'^#define MyAppVersion\s+["\']([^"\']+)["\']', installer_text, re.M)
        self.assertIsNotNone(init_match)
        self.assertIsNotNone(main_match)
        self.assertIsNotNone(installer_match)
        self.assertEqual(init_match.group(1), expected)
        self.assertEqual(main_match.group(1), expected)
        self.assertEqual(installer_match.group(1), expected)

    def test_dev_requirements_include_runtime_requirements(self):
        text = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^-r\s+requirements\.txt\s*$")


if __name__ == "__main__":
    unittest.main()
