"""The docs tell a contributor to write a fragment, not a CHANGELOG.md line.

Each change writes changelog.d/<slug>.md and scripts/release.py collates the
fragments at release (test_release_fragments covers the code). These tests
hold the words that send a contributor there: the CHANGELOG.md header, the
how-to in changelog.d/README.md, and the Makefile's `changelog` target,
whose recipe is run here as written.
"""
from __future__ import annotations

import re
import subprocess
import sys
import unittest

from tests import _changelog

ROOT = _changelog.ROOT
FRAGMENT = "changelog.d/<slug>.md"


def _flat(text: str) -> str:
    """Whitespace folded to single spaces, so a wrapped line still matches."""
    return " ".join(text.split())


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _changelog_recipe() -> str:
    """The one recipe line under the Makefile's `changelog:` target."""
    m = re.search(r"^changelog:[^\n]*## [^\n]+\n\t(.+)$", _read("Makefile"), re.MULTILINE)
    assert m, "Makefile has no `changelog:` target with a `## ` help line and one recipe"
    return m.group(1)


class ChangelogDocs(unittest.TestCase):
    def test_the_changelog_header_points_at_the_fragments_above_unreleased(self):
        header, sep, _ = _read("CHANGELOG.md").partition("\n## [Unreleased]\n")
        self.assertTrue(sep, "CHANGELOG.md has no `## [Unreleased]` line")
        header = _flat(header)
        for phrase in ("`changelog.d/`", "`changelog.d/README.md`", "`make changelog`"):
            self.assertIn(phrase, header, f"the CHANGELOG.md header, above [Unreleased], does not name {phrase}")

    def test_the_fragment_readme_says_how_to_write_one(self):
        text = _flat(_read("changelog.d/README.md"))
        for phrase in (
            f"`{FRAGMENT}`",  # the path, one per change
            "`### Added`",  # sessionview's shape: Keep a Changelog
            "`### Security`",
            "no tracker ID",  # neither in the name nor in the text
            "`Changelog: none, no user-visible change`",  # no fragment, said so
            "No relative links",  # a fragment's link breaks once collated
            "Keep a Changelog order",  # how sections merge
            "numbers compared as numbers",  # the order, which no author picks
            "no say in where an entry lands",
            "modify/delete conflict",  # the scrub that meets a release
            "Never resolve it by keeping the deletion alone",
            "`make scan`",
            "`make changelog`",
            "`python3 scripts/release.py patch --dry-run`",  # never uv run: it re-locks
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text, f"changelog.d/README.md does not say {phrase!r}")

    def test_the_makefile_changelog_target_previews_and_writes_nothing(self):
        recipe = _changelog_recipe()
        self.assertEqual(recipe, "@python3 scripts/release.py --preview")
        before = _read("CHANGELOG.md")
        out = subprocess.run([sys.executable, "-B", "scripts/release.py", "--preview"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout
        self.assertTrue(out.startswith("## [Unreleased]\n"), out[:80])
        self.assertNotIn("\n## [", out, "the preview printed more than [Unreleased]")
        for fragment in _changelog.fragments():
            for line in fragment.read_text(encoding="utf-8").splitlines():
                if line.startswith("### ") or line.startswith("- "):
                    self.assertIn(f"\n{line}\n", out, f"make changelog does not print {fragment.name}'s {line!r}")
        self.assertEqual(_read("CHANGELOG.md"), before, "make changelog wrote CHANGELOG.md")

    def test_agents_md_sends_a_branch_to_one_fragment_never_to_changelog_md(self):
        text = _flat(_read("AGENTS.md"))
        for phrase in (
            f"ONE fragment, `{FRAGMENT}`",
            "never edits `CHANGELOG.md`",
            "nothing goes under its `## [Unreleased]` heading",
            "neither the file name nor its text carries a tracker ID",
            "`changelog.d/README.md` says how",
            "`make changelog` prints the pending changelog entries",
            "collects `changelog.d/` into `CHANGELOG.md`",  # the release bullet
            "`python3 scripts/release.py patch --dry-run`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text, f"AGENTS.md does not say {phrase!r}")
        self.assertNotIn("uv run python scripts/release.py", text, "AGENTS.md runs the release through a re-locking uv run")
        self.assertNotRegex(text, r"\[Unreleased\][^.]*\b(add|write)s?\b",
                            "AGENTS.md tells a branch to write under [Unreleased]")

    def test_make_help_lists_changelog(self):
        help_lines = re.search(r"^help:.*\n((?:\t.*\n)+)", _read("Makefile"), re.MULTILINE).group(1)
        self.assertRegex(help_lines, r"\bchangelog\b")


if __name__ == "__main__":
    unittest.main()
