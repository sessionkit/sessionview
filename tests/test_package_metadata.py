"""pyproject.toml is what PyPI shows: the description becomes the project's
Summary line. The 0.0.1 name-reservation text must never ship again (SV-156).
SESSIONVIEW_PYPROJECT points the check at another file, so the guard can be
shown failing on an old pyproject.toml."""
import os
import re
import tomllib
import unittest

from tests import support

PYPROJECT = os.environ.get("SESSIONVIEW_PYPROJECT") or os.path.join(support.REPO, "pyproject.toml")


class PackageMetadata(unittest.TestCase):
    def setUp(self):
        with open(PYPROJECT, encoding="utf-8") as f:
            self.text = f.read()
        self.project = tomllib.loads(self.text)["project"]

    def test_no_name_reservation_text(self):
        self.assertNotRegex(self.text, re.compile(r"name\s+reserved", re.I))
        self.assertNotRegex(self.text, re.compile(r"the tool follows", re.I))

    def test_summary_is_the_readme_lead(self):
        self.assertEqual(
            self.project["description"],
            "A sidebar for tmux: your projects (sessions) and your agents,"
            " here and on remote hosts.")

    def test_a_version_is_set(self):
        self.assertRegex(self.project.get("version", ""), r"^\d+\.\d+\.\d+")
        self.assertNotEqual(self.project["version"], "0.0.1")


if __name__ == "__main__":
    unittest.main()
