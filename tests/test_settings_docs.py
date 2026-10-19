"""Guard: docs/settings.md and docs/configuration.md keep up with the code.

docs/settings.md has a table row for each key; config/config.json is the
template that holds every key. A key added to the template without a row, or a
row left behind for a key that is gone, is a hit. The default a row shows is
checked against the template for the scalar keys.

docs/configuration.md's Settings heading links docs/settings.md, and every
reference-style label either page uses is defined.
"""
import json
import os
import re
import unittest

from tests import support

DOCS = os.path.join(support.REPO, "docs")
SETTINGS = os.path.join(DOCS, "settings.md")
CONFIGURATION = os.path.join(DOCS, "configuration.md")
TEMPLATE = os.path.join(support.CONFIG, "config.json")

#: A table row: | `key` | type | default | what it does |
ROW = re.compile(r"^\| `([a-z_0-9]+)` \| ([a-z]+) \| (.+?) \| .+ \|$", re.M)

#: The type word a row uses for each JSON type.
TYPES = {bool: "boolean", int: "integer", str: "string", list: "list", dict: "object"}

#: A reference-style use [text][label] and a definition [label]: target.
USE = re.compile(r"\]\[([^\]]+)\]")
DEFINITION = re.compile(r"^\[([^\]]+)\]:\s*(\S+)", re.M)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def template_keys():
    with open(TEMPLATE, encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def rows(text):
    """{key: (type, default cell)} for every table row in TEXT."""
    return {m.group(1): (m.group(2), m.group(3)) for m in ROW.finditer(text)}


def undefined_labels(text):
    defined = {m.group(1).lower() for m in DEFINITION.finditer(text)}
    return sorted({u for u in USE.findall(text) if u.lower() not in defined})


class SettingsPage(unittest.TestCase):
    def setUp(self):
        self.keys = template_keys()
        self.rows = rows(read(SETTINGS))

    def test_finds_rows(self):
        # Not vacuous: the parser sees the tables.
        self.assertGreater(len(self.rows), 10)

    def test_every_key_has_a_row(self):
        missing = sorted(set(self.keys) - set(self.rows))
        self.assertEqual(missing, [], "keys in config/config.json with no row in docs/settings.md")

    def test_no_row_without_a_key(self):
        extra = sorted(set(self.rows) - set(self.keys))
        self.assertEqual(extra, [], "rows in docs/settings.md for keys not in config/config.json")

    def test_types_match(self):
        for k, v in self.keys.items():
            with self.subTest(key=k):
                self.assertEqual(self.rows[k][0], TYPES[type(v)])

    def test_scalar_defaults_match(self):
        # A scalar's default cell is its JSON value in backticks, verbatim.
        for k, v in self.keys.items():
            if isinstance(v, (list, dict)):
                continue
            with self.subTest(key=k):
                cell = self.rows[k][1]
                self.assertEqual(json.loads(cell.strip("`")), v)

    def test_says_the_kit_cascade_is_not_read(self):
        self.assertIn("does not read the kit's settings", read(SETTINGS))


class ConfigurationPage(unittest.TestCase):
    def test_settings_heading_links_the_settings_page(self):
        text = read(CONFIGURATION)
        self.assertRegex(text, r"(?m)^## \[Settings\]\[settings\]$")
        self.assertRegex(text, r"(?m)^\[settings\]: settings\.md$")
        self.assertTrue(os.path.isfile(SETTINGS))

    def test_labels_defined(self):
        for path in (SETTINGS, CONFIGURATION):
            with self.subTest(doc=os.path.basename(path)):
                self.assertEqual(undefined_labels(read(path)), [])


class Patterns(unittest.TestCase):
    """The parsers themselves, on text made up for the purpose."""

    def test_row(self):
        text = "| `width` | integer | `34` | Columns. |\n| Key | Type | Default | What |\n"
        self.assertEqual(rows(text), {"width": ("integer", "`34`")})

    def test_undefined_labels(self):
        self.assertEqual(undefined_labels("see [a][x] and [b][y]\n\n[x]: x.md\n"), ["y"])
        self.assertEqual(undefined_labels("[a][X]\n\n[x]: x.md\n"), [])


if __name__ == "__main__":
    unittest.main()
