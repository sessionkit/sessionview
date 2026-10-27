"""The live changelog.d/: every pending fragment is one the release can collate.

A change writes its entry to changelog.d/<slug>.md, and scripts/release.py
moves it into CHANGELOG.md at the release. These checks read this repo's own
fragments, so a bad one goes red on the branch that adds it, not at the
release:

- every fragment parses as the release parses it (its own parse_fragment);
- no fragment holds a relative link. A link resolves from the file that holds
  it, so one written for changelog.d/ breaks once the entry sits in
  CHANGELOG.md, and one written for CHANGELOG.md is broken here. "Relative"
  is the README link gate's own relative(), which counts an in-page #anchor
  too (it would point into CHANGELOG.md once collated), plus an HTML href;
- every file git tracks under changelog.d/, at any depth, is
  changelog.d/README.md or a fragment changelog.d/<slug>.md: lower-case
  words joined by single hyphens. It compares paths, so a nested README.md is
  a stray too, and a file the release would not read is caught here, not
  left behind at the release. `readme.md` is no slug: on a Mac's disk it is
  the README's own name;
- no two fragments share a name as the release orders names (numbers
  compared as numbers, so step-07 is step-7). One change writes one
  fragment, and two names the release cannot order apart would collate in
  whatever order the disk lists them;
- CHANGELOG.md's [Unreleased] is an empty heading. A branch cut after the
  switch that still writes there merges clean, and the release would put
  that text under the new version after the merged sections, a second
  `### Fixed` among them. This fails that branch, and names changelog.d/.

A fragment's text holds no tracker ID either; tests/test_code_no_tracker_ids
reads changelog.d/ for that (its SCOPE), so it is not checked twice.

Each check is a function over its input, run on the live tree and on a
planted bad case, so each is shown to go red.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import _changelog
from tests import test_readme_links as readme_links  # its relative(): the link gate's own rule

ROOT = _changelog.ROOT
README = "changelog.d/README.md"
# changelog.d/<slug>.md: lower-case words of letters and digits, joined by
# single hyphens. No tracker ID: a file name on master is public text.
# readme.md is refused: on a case-insensitive disk it is README.md.
FRAGMENT = re.compile(r"changelog\.d/(?!readme\.md$)(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)\.md")
# An HTML link's target; readme_links.relative() reads Markdown links only.
HREF = re.compile(r"""\bhref\s*=\s*["']?([^"'\s>]+)""", re.I)


def parse_faults(paths: list[Path]) -> list[str]:
    """What the release's own parse_fragment refuses, one line per fragment."""
    faults = []
    for path in paths:
        try:
            sections = _changelog.release().parse_fragment(path)
        except SystemExit as e:
            faults.append(str(e.code))
            continue
        if not sections:  # parse_fragment refuses this itself; kept as a floor
            faults.append(f"{path}: no sections")
    return faults


def relative_links(paths: list[Path]) -> list[str]:
    """`name: target` for each relative link in each fragment."""
    out = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        found = [t for _, t in readme_links.relative(text)]
        found += [t for t in HREF.findall(text) if not readme_links.ABSOLUTE.match(t)]
        out += [f"{path.name}: {target}" for target in found]
    return out


def name_faults(tracked: list[str]) -> list[str]:
    """Each tracked path under changelog.d/ that is neither its README.md nor
    a fragment the release collects."""
    return [p for p in tracked if p != README and not FRAGMENT.fullmatch(p)]


def name_key(path: str):
    """A fragment's name as the release orders it (its own _name_key), so
    step-07 and step-7 are one name."""
    return tuple(_changelog.release()._name_key(Path(path)))


def shared_names(paths: list[str]) -> list[str]:
    """The fragments the release cannot order apart, grouped, in path order."""
    seen: dict[tuple, list[str]] = {}
    for p in sorted(paths):
        if FRAGMENT.fullmatch(p):
            seen.setdefault(name_key(p), []).append(p)
    return [", ".join(group) for group in seen.values() if len(group) > 1]


def unreleased_faults(text: str) -> list[str]:
    """`line N: text` for each non-blank line under CHANGELOG.md's
    `## [Unreleased]`, up to the next version heading; a missing heading is
    one fault too."""
    lines = text.splitlines()
    at = next((i for i, line in enumerate(lines) if line == _changelog.release().UNRELEASED), None)
    if at is None:
        return ["no line that is exactly '## [Unreleased]'"]
    end = _changelog.release()._next_version(lines, at + 1)
    return [f"line {i + 1}: {lines[i]}" for i in range(at + 1, end) if lines[i].strip()]


def _repo(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


GOOD = "### Fixed\n\n- An entry, naming `README.md` in a code span.\n"


def in_checkout() -> bool:
    if shutil.which("git") is None:
        return False
    out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, check=False)
    return out.returncode == 0 and Path(out.stdout.strip()).resolve() == ROOT.resolve()


NO_CHECKOUT = "not a git checkout (an sdist?): no tracked files to read"


def tracked() -> list[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", "changelog.d"],
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p]


class Planted(unittest.TestCase):
    """A scratch changelog.d/ per test."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="sv-fragments-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def plant(self, name: str, text: str) -> Path:
        d = self.tmp / "changelog.d"
        d.mkdir(exist_ok=True)
        p = d / name
        p.write_text(text, encoding="utf-8")
        return p


# ---- the live tree ----------------------------------------------------------------


class LiveFragments(unittest.TestCase):
    def test_the_checks_read_the_live_fragments(self):
        """A proven non-zero beside the zeros below, while an entry is pending.

        The checks read this repo's own changelog.d/, where its README.md is.
        Right after a release that directory holds no fragment, and that is its
        right state, so this never fails for an empty changelog.d/. It skips,
        and says so: a check with nothing to read never passes quietly."""
        self.assertTrue((_changelog.FRAGMENTS / "README.md").is_file(), "the checks read the live changelog.d/")
        if not _changelog.fragments():
            self.skipTest("no pending fragment: changelog.d/ holds only its README.md, as right after a release")

    def test_every_live_fragment_parses_as_the_release_parses_it(self):
        self.assertEqual(parse_faults(_changelog.fragments()), [])

    def test_no_live_fragment_holds_a_relative_link(self):
        self.assertEqual(relative_links(_changelog.fragments()), [])

    @unittest.skipUnless(in_checkout(), NO_CHECKOUT)
    def test_every_tracked_path_under_changelog_d_is_its_readme_or_a_fragment(self):
        paths = tracked()
        self.assertIn(README, paths, "changelog.d/README.md is tracked")
        self.assertEqual(name_faults(paths), [])

    @unittest.skipUnless(in_checkout(), NO_CHECKOUT)
    def test_git_and_the_collector_agree_on_the_fragments(self):
        """Every fragment git tracks is one the release collects: the name rule
        and release.fragment_paths say the same."""
        named = {p for p in tracked() if p != README}
        self.assertEqual(named - {_repo(p) for p in _changelog.fragments()}, set())

    def test_no_two_live_fragments_share_a_name(self):
        self.assertEqual(shared_names([_repo(p) for p in _changelog.fragments()]), [])

    def test_the_live_unreleased_is_an_empty_heading(self):
        faults = unreleased_faults(_changelog.CHANGELOG.read_text(encoding="utf-8"))
        self.assertEqual(faults, [], "CHANGELOG.md's [Unreleased] holds text: write the entry as a fragment, "
                                     "changelog.d/<slug>.md (changelog.d/README.md says how), and leave "
                                     "[Unreleased] an empty heading")


# ---- each check goes red on a planted bad case ---------------------------------------


class ParseCheck(Planted):
    def test_the_parse_check_refuses_a_planted_bad_fragment(self):
        for text, says in (
            ("Loose text first.\n\n### Fixed\n\n- an entry\n", "text outside a ### section"),
            ("## [9.9.9] - 2000-01-01\n\n- an entry\n", "a fragment holds only"),
            ("#### Too deep\n\n- an entry\n", "a fragment holds only"),
            ("### A headline\n\n- an entry\n", "a fragment holds only"),
            ("### Fixed\n", "no entries"),
            ("", "no entries"),
        ):
            with self.subTest(text=text):
                good = self.plant("good.md", GOOD)
                bad = self.plant("bad.md", text)
                self.assertEqual(parse_faults([good]), [])
                faults = parse_faults([good, bad])
                self.assertEqual(len(faults), 1, faults)
                self.assertIn(says, faults[0])
                self.assertIn("bad.md", faults[0])


class LinkCheck(Planted):
    def test_the_link_check_refuses_a_planted_relative_link(self):
        for link in (
            "[the README](README.md)",
            "[the README](../README.md)",
            "[a section](../README.md#status)",
            "[the how-to](./README.md)",
            "[the top](#fixed)",
            "<a href=\"../CHANGELOG.md\">the changelog</a>",
            "[setup]\n\n[setup]: ../docs/setup.md",
        ):
            with self.subTest(link=link):
                bad = self.plant("link.md", f"### Fixed\n\n- See {link}.\n")
                self.assertTrue(relative_links([bad]), link)

    def test_the_link_check_passes_what_is_not_a_relative_link(self):
        for text in (
            "- See [a page](https://example.com/page).",
            "- See <a href=\"https://example.com/\">a page</a>.",
            "- Name the file in a code span: `README.md`.",
            "- Mail [us](mailto:someone@example.com).",
        ):
            with self.subTest(text=text):
                ok = self.plant("ok.md", f"### Fixed\n\n{text}\n")
                self.assertEqual(relative_links([ok]), [])


class NameCheck(Planted):
    def test_the_name_check_refuses_a_planted_stray(self):
        for path in (
            "changelog.d/x.markdown",
            "changelog.d/x.txt",
            "changelog.d/sub/x.md",
            "changelog.d/sub/README.md",
            "changelog.d/readme.md",
            "changelog.d/Some-Slug.md",
            "changelog.d/" + "-".join(("AB", "9")) + "-x.md",
            "changelog.d/x--y.md",
            "changelog.d/x-.md",
            "changelog.d/-x.md",
            "changelog.d/x_y.md",
            "changelog.d/.md",
            "changelog.d/.DS_Store",
        ):
            with self.subTest(path=path):
                self.assertEqual(name_faults([README, "changelog.d/good.md", path]), [path])

    def test_the_name_check_passes_a_fragment(self):
        for path in (
            "changelog.d/x.md",
            "changelog.d/changelog-fragments.md",
            "changelog.d/a-b-c.md",
            "changelog.d/fix-2fa.md",
            "changelog.d/notes.md",
            "changelog.d/readme-links.md",
        ):
            with self.subTest(path=path):
                self.assertEqual(name_faults([README, path]), [])

    def test_every_name_the_check_passes_is_one_the_release_collects(self):
        for name in ("x.md", "a-b-c.md", "step-20.md"):
            self.plant(name, GOOD)
        collected = [p.name for p in _changelog.fragments(self.tmp / "changelog.d")]
        self.assertEqual(collected, ["a-b-c.md", "step-20.md", "x.md"])
        self.assertEqual(name_faults([f"changelog.d/{n}" for n in collected]), [])

    def test_a_tracker_id_in_a_name_is_refused(self):
        """The name carries no ID: changelog.d/<slug>.md only."""
        named = "changelog.d/" + "-".join(("SV", "206")) + "-changelog-fragments.md"
        self.assertEqual(name_faults([README, named]), [named])


class IsFragment(Planted):
    """_changelog.is_fragment, which the history-exempt guards use, says what
    release.fragment_paths says: their README.md is never exempt."""

    def test_is_fragment_agrees_with_the_release(self):
        for name in ("README.md", "x.md", "a-b.md", "x.txt", ".DS_Store"):
            self.plant(name, GOOD)
        (self.tmp / "changelog.d" / "sub").mkdir()
        self.plant("sub/y.md", GOOD)
        collected = {f"changelog.d/{p.name}" for p in _changelog.fragments(self.tmp / "changelog.d")}
        every = {p.relative_to(self.tmp).as_posix() for p in (self.tmp / "changelog.d").rglob("*") if p.is_file()}
        self.assertEqual({p for p in every if _changelog.is_fragment(p)}, collected)
        self.assertEqual(collected, {"changelog.d/x.md", "changelog.d/a-b.md"})

    def test_the_readme_and_the_changelog_are_no_fragment(self):
        for rel in (README, "CHANGELOG.md", "docs/x.md", "x.md"):
            with self.subTest(rel=rel):
                self.assertFalse(_changelog.is_fragment(rel))


class SharedNameCheck(unittest.TestCase):
    def test_the_name_check_refuses_two_names_the_release_cannot_order_apart(self):
        self.assertEqual(shared_names(["changelog.d/good.md", "changelog.d/step-7.md", "changelog.d/step-07.md"]),
                         ["changelog.d/step-07.md, changelog.d/step-7.md"])

    def test_the_name_check_passes_distinct_names(self):
        """step-7 and step-70 are different names; so are step-7 and steps-7."""
        self.assertEqual(shared_names(["changelog.d/step-7.md", "changelog.d/step-70.md",
                                       "changelog.d/steps-7.md"]), [])


class UnreleasedCheck(unittest.TestCase):
    LOG = "# Changelog\n\nHeader.\n\n## [Unreleased]\n\n## [0.0.1] - 2026-01-02\n\n### Added\n\n- born\n"

    def test_an_empty_heading_passes(self):
        self.assertEqual(unreleased_faults(self.LOG), [])
        self.assertEqual(unreleased_faults("# Changelog\n\n## [Unreleased]\n"), [])

    def test_a_planted_entry_under_unreleased_is_refused(self):
        bad = self.LOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Fixed\n\n- a line\n", 1)
        self.assertEqual(unreleased_faults(bad), ["line 7: ### Fixed", "line 9: - a line"])

    def test_a_missing_heading_is_refused(self):
        self.assertEqual(len(unreleased_faults(self.LOG.replace("## [Unreleased]", "## [Next]"))), 1)

    def test_a_stamped_changelog_passes(self):
        """The stamp leaves [Unreleased] an empty heading above the new version."""
        stamped = self.LOG.replace("## [Unreleased]", "## [Unreleased]\n\n## [0.0.2] - 2026-02-03\n\n### Fixed\n\n- x", 1)
        self.assertEqual(unreleased_faults(stamped), [])


class AfterRelease(unittest.TestCase):
    def test_the_live_checks_hold_right_after_a_release(self):
        """A release collates every fragment and leaves changelog.d/ holding only
        its README.md, and [Unreleased] empty. No live check may go red on that
        tree: the release commit runs the same suite."""
        with tempfile.TemporaryDirectory(prefix="sv-fragments-") as tmp:
            d = Path(tmp) / "changelog.d"
            d.mkdir()
            (d / "README.md").write_text("# changelog.d\n", encoding="utf-8")
            real = _changelog.fragments
            with mock.patch.object(_changelog, "FRAGMENTS", d), \
                    mock.patch.object(_changelog, "fragments", lambda directory=d: real(directory)):
                self.assertEqual(_changelog.fragments(), [])
                live = LiveFragments()
                with self.assertRaisesRegex(unittest.SkipTest, "no pending fragment"):
                    live.test_the_checks_read_the_live_fragments()
                live.test_every_live_fragment_parses_as_the_release_parses_it()
                live.test_no_live_fragment_holds_a_relative_link()
                live.test_no_two_live_fragments_share_a_name()
        # The tracked-path checks read git, not the directory: their functions on
        # what git would list there.
        self.assertEqual(parse_faults([]), [])
        self.assertEqual(relative_links([]), [])
        self.assertEqual(name_faults([README]), [])
        self.assertEqual(shared_names([]), [])


if __name__ == "__main__":
    unittest.main()
