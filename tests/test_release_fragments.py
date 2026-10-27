"""CHANGELOG fragments: each change writes changelog.d/<slug>.md and
scripts/release.py collates them into CHANGELOG.md at release, so two
branches stop clashing on CHANGELOG.md.

The unit tests load scripts/release.py as a module. The end-to-end tests
(FragmentRelease) run it in test_release's scratch repo: a copy of the files
a release touches, the real uv, offline, against an empty cache of its own,
so no test touches the network, this checkout's version, or a real lock or
venv. Without uv that class is a loud skip.

sessionview's shape is SECTIONS = the Keep a Changelog tuple: only those
sections, same-named ones merged in the tuple's order. The headline cases
patch SECTIONS to None, the shape another repo copying the collector runs, so
the one family copy stays honest in both.

The test names are the family copy's, so the two copies diff.
"""
from __future__ import annotations

import contextlib
import inspect
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import support
from tests.test_release import FILES, UV_SKIP, ReleaseRepo, load_release, read

ROOT = Path(support.REPO)
SCRIPT = ROOT / "scripts" / "release.py"
KAC = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")

release = load_release()


def frag(d: Path, name: str, text: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(text)
    return p


def today() -> str:
    return release.datetime.now().astimezone().date().isoformat()


def old_stamp(text: str, version: str) -> str:
    """The stamp with no fragments: what the release wrote before changelog.d/."""
    return text.replace("## [Unreleased]", f"## [Unreleased]\n\n## [{version}] - {today()}", 1)


class Scratch(unittest.TestCase):
    """A scratch directory per test, and the cwd moved into it on request."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="sv-fragments-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def chdir(self):
        cm = contextlib.chdir(self.tmp)
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def headline(self):
        """The headline shape for this test: SECTIONS = None."""
        patch = mock.patch.object(release, "SECTIONS", None)
        patch.start()
        self.addCleanup(patch.stop)

    def refuses(self, fn, *args, **kwargs) -> str:
        with self.assertRaises(SystemExit) as e:
            fn(*args, **kwargs)
        return str(e.exception.code)


class Shape(unittest.TestCase):
    def test_sessionview_runs_the_keep_a_changelog_shape(self):
        self.assertEqual(release.SECTIONS, KAC)

    def test_stamp_keeps_its_two_argument_call(self):
        """stamp(version, dry) still works: fragments defaults to none."""
        sig = inspect.signature(release.stamp)
        self.assertEqual(list(sig.parameters), ["version", "dry", "fragments"])
        self.assertEqual(tuple(sig.parameters["fragments"].default), ())


# ---- which files are fragments, and their order --------------------------------


class Order(Scratch):
    def test_absent_dir_is_no_fragments(self):
        self.assertEqual(release.fragment_paths(self.tmp / "changelog.d"), [])

    def test_readme_and_non_markdown_are_not_fragments(self):
        d = self.tmp / "changelog.d"
        frag(d, "README.md", "# how to\n")
        frag(d, ".gitkeep", "")
        frag(d, "notes.txt", "### Fixed\n\n- x\n")
        frag(d, "x.markdown", "### Fixed\n\n- x\n")
        frag(d / "sub", "x.md", "### Fixed\n\n- x\n")
        self.assertEqual(release.fragment_paths(d), [])

    def test_order_is_by_name_with_numbers_compared_as_numbers(self):
        d = self.tmp / "changelog.d"
        names = ("step-1000.md", "log-home.md", "step-20.md", "step-999.md", "step-9.md",
                 "badge-cache-store.md", "dock-app-iterm.md", "step-9-b.md")
        for name in names:
            frag(d, name, "### Fixed\n\n- x\n")
        self.assertEqual([p.name for p in release.fragment_paths(d)], [
            "badge-cache-store.md",
            "dock-app-iterm.md",
            "log-home.md",
            "step-9-b.md",
            "step-9.md",
            "step-20.md",
            "step-999.md",
            "step-1000.md",
        ])

    def test_order_does_not_depend_on_creation_order(self):
        a, b = self.tmp / "a" / "changelog.d", self.tmp / "b" / "changelog.d"
        names = ["step-2.md", "step-10.md", "step-1.md", "alpha.md"]
        for n in names:
            frag(a, n, "### Fixed\n\n- x\n")
        for n in reversed(names):
            frag(b, n, "### Fixed\n\n- x\n")
        self.assertEqual([p.name for p in release.fragment_paths(a)], [p.name for p in release.fragment_paths(b)])


# ---- reading one fragment: Keep a Changelog (sessionview's SECTIONS) -----------------


class KacParse(Scratch):
    def test_kac_parse_reads_sections(self):
        p = frag(self.tmp, "x.md", "\n### Added\n\n- one\n- two\n  more\n\n### Fixed\n- three\n\n")
        self.assertEqual(dict(release.parse_fragment(p)), {"Added": "- one\n- two\n  more", "Fixed": "- three"})

    def test_kac_parse_merges_a_repeated_section_within_one_fragment(self):
        p = frag(self.tmp, "x.md", "### Added\n\n- one\n\n### Fixed\n\n- f\n\n### Added\n\n- two\n")
        self.assertEqual(release.parse_fragment(p), [("Added", "- one\n- two"), ("Fixed", "- f")])

    def test_kac_parse_drops_an_empty_section(self):
        p = frag(self.tmp, "x.md", "### Added\n\n### Fixed\n\n- f\n")
        self.assertEqual(release.parse_fragment(p), [("Fixed", "- f")])

    def test_a_heading_inside_a_code_fence_is_not_a_section(self):
        body = "### Fixed\n\n- shows\n\n  ```md\n  ### Nonsense\n  ## [Unreleased]\n  ```\n"
        p = frag(self.tmp, "x.md", body)
        self.assertEqual(release.parse_fragment(p),
                         [("Fixed", "- shows\n\n  ```md\n  ### Nonsense\n  ## [Unreleased]\n  ```")])

    def test_kac_parse_refuses_a_bad_fragment(self):
        for text, says in (
            ("### Addded\n\n- typo\n", "### Addded"),
            ("### A headline\n\n- x\n", "### A headline"),
            ("- loose\n\n### Added\n\n- x\n", "outside a ### section"),
            ("### Added\n\n- x\n\n## [1.0.0]\n", "## [1.0.0]"),
            ("# Title\n\n### Added\n\n- x\n", "# Title"),
            ("### Added\n\n#### Sub\n\n- x\n", "#### Sub"),
            ("\n\n", "no entries"),
            ("### Added\n\n### Fixed\n", "no entries"),
        ):
            with self.subTest(text=text):
                p = frag(self.tmp, "x.md", text)
                msg = self.refuses(release.parse_fragment, p)
                self.assertTrue(msg.startswith("release: "), msg)
                self.assertIn("x.md", msg)
                self.assertIn(says, msg)

    def test_a_heading_refusal_names_the_line_and_the_shape(self):
        p = frag(self.tmp, "x.md", "### Fixed\n\n- x\n\n## [1.0.0]\n")
        msg = self.refuses(release.parse_fragment, p)
        self.assertIn("x.md:5:", msg)
        self.assertIn("### Added, ### Changed, ### Deprecated, ### Removed, ### Fixed, ### Security", msg)


# ---- reading one fragment: the headline shape (SECTIONS = None) ---------------------


class HeadlineParse(Scratch):
    def setUp(self):
        super().setUp()
        self.headline()

    def test_headline_parse_keeps_each_section_whole_and_in_order(self):
        p = frag(self.tmp, "x.md",
                 "\n### A turn reaches the agent whole\n\n- one\n- two\n  more\n\n### Speech waits once\n- three\n\n")
        self.assertEqual(release.parse_fragment(p), [
            ("A turn reaches the agent whole", "- one\n- two\n  more"),
            ("Speech waits once", "- three"),
        ])

    def test_headline_parse_merges_nothing_within_a_fragment(self):
        p = frag(self.tmp, "x.md", "### Same\n\n- one\n\n### Other\n\n- o\n\n### Same\n\n- two\n")
        self.assertEqual(release.parse_fragment(p), [("Same", "- one"), ("Other", "- o"), ("Same", "- two")])

    def test_headline_parse_refuses_a_bad_fragment(self):
        for text, says in (
            ("- loose\n\n### Headline\n\n- x\n", "outside a ### section"),
            ("###\n\n- x\n", "'###'"),
            ("### \n\n- x\n", "'### '"),
            ("### One\n\n### Two\n", "no entries"),
        ):
            with self.subTest(text=text):
                p = frag(self.tmp, "x.md", text)
                msg = self.refuses(release.parse_fragment, p)
                self.assertIn(says, msg)
                self.assertIn("x.md", msg)

    def test_headline_collect_keeps_every_section_whole_in_fragment_order(self):
        d = self.tmp / "changelog.d"
        a = frag(d, "step-9.md", "### Calls ring once\n\n- a1\n\n### Fixed\n\n- a2\n")
        b = frag(d, "step-20.md", "### Fixed\n\n- b1\n")
        c = frag(d, "step-1000.md", "### Calls ring once\n\n- c1\n  more\n")
        paths = release.fragment_paths(d)
        self.assertEqual(paths, [a, b, c])
        self.assertEqual(release.collect(paths), (
            "### Calls ring once\n\n- a1\n\n"
            "### Fixed\n\n- a2\n\n"
            "### Fixed\n\n- b1\n\n"
            "### Calls ring once\n\n- c1\n  more"
        ))


# ---- merging fragments ------------------------------------------------------------


class Merge(Scratch):
    def test_collect_nothing_is_empty(self):
        self.assertEqual(release.collect([]), "")

    def test_kac_collect_merges_same_named_sections_in_keep_a_changelog_order(self):
        d = self.tmp / "changelog.d"
        a = frag(d, "a.md", "### Fixed\n\n- a-fix\n\n### Added\n\n- a-add\n")
        b = frag(d, "b.md", "### Security\n\n- b-sec\n\n### Added\n\n- b-add\n")
        c = frag(d, "c.md", "### Deprecated\n\n- c-dep\n\n### Changed\n\n- c-chg\n\n### Removed\n\n- c-rm\n")
        self.assertEqual(release.collect([a, b, c]), (
            "### Added\n\n- a-add\n- b-add\n\n"
            "### Changed\n\n- c-chg\n\n"
            "### Deprecated\n\n- c-dep\n\n"
            "### Removed\n\n- c-rm\n\n"
            "### Fixed\n\n- a-fix\n\n"
            "### Security\n\n- b-sec"
        ))

    def test_kac_collect_puts_entries_in_file_name_order_within_a_section(self):
        d = self.tmp / "changelog.d"
        frag(d, "step-10.md", "### Fixed\n\n- ten\n")
        frag(d, "step-9.md", "### Fixed\n\n- nine\n")
        frag(d, "alpha.md", "### Fixed\n\n- alpha\n")
        self.assertEqual(release.collect(release.fragment_paths(d)), "### Fixed\n\n- alpha\n- nine\n- ten")


# ---- stamping CHANGELOG.md ----------------------------------------------------------

#: sessionview's CHANGELOG as it reads after the switch: [Unreleased] empty.
LOG = """# Changelog

Header.

## [Unreleased]

## [0.0.1] - 2026-01-02

### Added

- born
"""

#: A CHANGELOG whose [Unreleased] still holds text (a legacy body).
LEGACY_LOG = """# Changelog

Header.

## [Unreleased]

### Added

- old-add

### Fixed

- old-fix

## [0.0.1] - 2026-01-02

### Added

- born
"""


class Stamp(Scratch):
    def setUp(self):
        super().setUp()
        self.chdir()

    def write(self, text):
        Path("CHANGELOG.md").write_text(text)

    def test_stamp_without_fragments_is_the_old_stamp(self):
        for text in (LOG, LEGACY_LOG):
            with self.subTest(legacy=text is LEGACY_LOG):
                self.write(text)
                with contextlib.redirect_stdout(io.StringIO()):
                    release.stamp("0.0.2", dry=False)
                self.assertEqual(Path("CHANGELOG.md").read_text(), old_stamp(text, "0.0.2"))

    def test_stamp_with_an_empty_fragment_list_is_the_old_stamp(self):
        self.write(LOG)
        with contextlib.redirect_stdout(io.StringIO()):
            release.stamp("0.0.2", dry=False, fragments=[])
        self.assertEqual(Path("CHANGELOG.md").read_text(), old_stamp(LOG, "0.0.2"))

    def test_kac_stamp_merges_fragments_under_the_new_version(self):
        self.write(LOG)
        d = Path("changelog.d")
        frag(d, "step-10.md", "### Fixed\n\n- ten-fix\n\n### Added\n\n- ten-add\n")
        frag(d, "step-9.md", "### Fixed\n\n- nine-fix\n")
        with contextlib.redirect_stdout(io.StringIO()):
            release.stamp("0.0.2", dry=False, fragments=release.fragment_paths(d))
        self.assertEqual(Path("CHANGELOG.md").read_text(), f"""# Changelog

Header.

## [Unreleased]

## [0.0.2] - {today()}

### Added

- ten-add

### Fixed

- nine-fix
- ten-fix

## [0.0.1] - 2026-01-02

### Added

- born
""")

    def test_kac_stamp_merges_fragments_then_the_unreleased_body(self):
        """A legacy body follows the merged sections verbatim: the family rule.
        sessionview's [Unreleased] is pinned empty, so this is the code's
        behaviour, not the tree's (test_changelog_fragments)."""
        self.write(LEGACY_LOG)
        a = frag(Path("changelog.d"), "a.md", "### Fixed\n\n- frag-fix\n\n### Added\n\n- frag-add\n")
        with contextlib.redirect_stdout(io.StringIO()):
            release.stamp("0.0.2", dry=False, fragments=[a])
        self.assertEqual(Path("CHANGELOG.md").read_text(), f"""# Changelog

Header.

## [Unreleased]

## [0.0.2] - {today()}

### Added

- frag-add

### Fixed

- frag-fix

### Added

- old-add

### Fixed

- old-fix

## [0.0.1] - 2026-01-02

### Added

- born
""")

    def test_stamp_with_an_empty_unreleased_and_no_older_version(self):
        self.write("# Changelog\n\n## [Unreleased]\n")
        a = frag(Path("changelog.d"), "a.md", "### Added\n\n- frag\n")
        with contextlib.redirect_stdout(io.StringIO()):
            release.stamp("1.0.0", dry=False, fragments=[a])
        self.assertEqual(Path("CHANGELOG.md").read_text(),
                         f"# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - {today()}\n\n### Added\n\n- frag\n")

    def test_stamp_keeps_the_fresh_unreleased_directly_above_the_version(self):
        self.write(LOG)
        a = frag(Path("changelog.d"), "a.md", "### Added\n\n- frag\n")
        with contextlib.redirect_stdout(io.StringIO()):
            release.stamp("9.9.9", dry=False, fragments=[a])
        self.assertIn("## [Unreleased]\n\n## [9.9.9] - ", Path("CHANGELOG.md").read_text())

    def test_stamp_dry_run_touches_nothing(self):
        self.write(LOG)
        a = frag(Path("changelog.d"), "a-frag.md", "### Changed\n\n- frag\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            release.stamp("0.0.2", dry=True, fragments=[a])
        self.assertEqual(Path("CHANGELOG.md").read_text(), LOG)
        self.assertTrue(a.exists())
        self.assertIn("changelog.d/a-frag.md", out.getvalue())
        self.assertIn("Changed", out.getvalue())

    def test_stamp_with_fragments_refuses_an_unreleased_that_is_not_its_own_line(self):
        self.write("# Changelog\n\n## [Unreleased] - soon\n\n### Added\n\n- x\n")
        a = frag(Path("changelog.d"), "a.md", "### Added\n\n- frag\n")
        msg = self.refuses(release.stamp, "1.0.0", dry=False, fragments=[a])
        self.assertIn("exactly '## [Unreleased]'", msg)
        self.assertTrue(Path("CHANGELOG.md").read_text().startswith("# Changelog\n\n## [Unreleased] - soon\n"))


# ---- the preview ------------------------------------------------------------------


class Preview(Scratch):
    def setUp(self):
        super().setUp()
        self.chdir()

    def test_preview_collates_into_unreleased_ahead_of_its_body(self):
        Path("CHANGELOG.md").write_text(LEGACY_LOG)
        d = Path("changelog.d")
        frag(d, "step-10.md", "### Fixed\n\n- ten\n")
        frag(d, "step-9.md", "### Added\n\n- nine\n")
        self.assertEqual(release.preview(release.fragment_paths(d)), (
            "## [Unreleased]\n\n### Added\n\n- nine\n\n### Fixed\n\n- ten\n\n"
            "### Added\n\n- old-add\n\n### Fixed\n\n- old-fix\n"
        ))
        self.assertEqual(Path("CHANGELOG.md").read_text(), LEGACY_LOG)

    def test_preview_reads_as_the_stamp_writes(self):
        """One merge for both: the preview's [Unreleased] body is the stamped version's body."""
        Path("CHANGELOG.md").write_text(LOG)
        d = Path("changelog.d")
        frag(d, "step-9.md", "### Fixed\n\n- nine\n\n```\n### not a section\n```\n")
        frag(d, "step-1000.md", "### Added\n\n- k\n")
        paths = release.fragment_paths(d)
        previewed = release.preview_text(paths)
        with contextlib.redirect_stdout(io.StringIO()):
            release.stamp("0.0.2", dry=False, fragments=paths)
        self.assertEqual(Path("CHANGELOG.md").read_text(), old_stamp(previewed, "0.0.2"))

    def test_preview_with_no_fragments_is_the_unreleased_section_as_it_is(self):
        Path("CHANGELOG.md").write_text(LOG)
        self.assertEqual(release.preview([]), "## [Unreleased]\n")
        self.assertEqual(release.preview_text([]), LOG)

    def test_preview_refuses_a_bad_fragment(self):
        Path("CHANGELOG.md").write_text(LOG)
        a = frag(Path("changelog.d"), "a.md", "loose text\n")
        self.assertIn("a.md:1:", self.refuses(release.preview, [a]))


class LivePreview(unittest.TestCase):
    def test_preview_of_this_repo_holds_every_live_fragment(self):
        """The live tree, read as `--preview` reads it, from the repo root."""
        paths = release.fragment_paths(ROOT / "changelog.d")
        with contextlib.chdir(ROOT):
            out = release.preview(paths)
        self.assertTrue(out.startswith("## [Unreleased]\n"))
        for p in paths:
            for name, body in release.parse_fragment(p):
                for entry in body.split("\n- "):
                    self.assertIn(entry.removeprefix("- "), out, p.name)
                self.assertIn(f"### {name}\n", out, p.name)

    def test_preview_needs_no_uv_no_git_and_writes_nothing(self):
        """Not a git repo, a dirty draft, a PATH with neither uv nor git on it."""
        with tempfile.TemporaryDirectory(prefix="sv-fragments-") as tmp:
            r = Path(tmp) / "plain"
            r.mkdir()
            (r / "CHANGELOG.md").write_text(LOG)
            frag(r / "changelog.d", "README.md", "How to.\n")
            frag(r / "changelog.d", "step-10.md", "### Fixed\n\n- ten\n")
            frag(r / "changelog.d", "step-9.md", "### Fixed\n\n- nine\n")
            empty = Path(tmp) / "empty-bin"
            empty.mkdir()
            before = {p: p.read_bytes() for p in r.rglob("*") if p.is_file()}
            out = subprocess.run([sys.executable, "-B", str(SCRIPT), "--preview"], cwd=r,
                                 env={"PATH": str(empty), "HOME": tmp}, capture_output=True, text=True, check=False)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(out.stdout, "## [Unreleased]\n\n### Fixed\n\n- nine\n- ten\n")
            self.assertEqual({p: p.read_bytes() for p in r.rglob("*") if p.is_file()}, before)


# ---- end to end: the script in test_release's scratch repo ---------------------------


@unittest.skipUnless(shutil.which("uv"), UV_SKIP)
class FragmentRelease(ReleaseRepo):
    """The real release.py, the real uv, offline, in a scratch repo holding a
    CHANGELOG with an empty [Unreleased] and two fragments."""

    #: What a release commits with no fragments (test_release's real run).
    FILES_COMMITTED = {"pyproject.toml", "uv.lock", "CHANGELOG.md", ".claude-plugin/plugin.json",
                       "src/sessionview/__init__.py"}

    def setUp(self):
        super().setUp()
        self.d = Path(self.root) / "changelog.d"
        self.write("CHANGELOG.md", LOG)
        frag(self.d, "README.md", "How to write a fragment.\n")
        frag(self.d, "step-9.md", "### Fixed\n\n- nine\n")
        frag(self.d, "step-10.md", "### Added\n\n- ten\n\n### Fixed\n\n- ten-fix\n")
        self.commit_all("fragments")

    def snapshot(self):
        """test_release's snapshot, plus the bytes of every file under
        changelog.d/, an ignored one included: porcelain does not show it."""
        files = {}
        for top, dirs, names in os.walk(self.d):
            for n in names:
                p = Path(top) / n
                files[p.relative_to(self.root).as_posix()] = p.read_bytes()
        return super().snapshot(), files

    def changed(self):
        return set(self.git("show", "--name-status", "--format=", "HEAD").splitlines())

    def test_release_collects_deletes_and_commits_the_deletions(self):
        out = self.release("9.9.9")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn(
            f"## [Unreleased]\n\n## [9.9.9] - {today()}\n\n"
            "### Added\n\n- ten\n\n### Fixed\n\n- nine\n- ten-fix\n\n## [0.0.1] - 2026-01-02\n",
            read(self.root, "CHANGELOG.md"))
        self.assertEqual(sorted(p.name for p in self.d.iterdir()), ["README.md"])
        self.assertEqual(self.git("ls-files", "changelog.d"), "changelog.d/README.md")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("log", "-1", "--format=%s"), "chore: release v9.9.9")
        self.assertEqual(self.git("rev-parse", "v9.9.9^{}"), self.git("rev-parse", "HEAD"))

    def test_release_commits_todays_files_plus_the_deletions(self):
        """The release commit's file set: the files it always commits, by name,
        and the git rm of each fragment. Nothing else rides along."""
        out = self.release("9.9.9")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(self.changed(), {f"M\t{f}" for f in self.FILES_COMMITTED}
                         | {"D\tchangelog.d/step-10.md", "D\tchangelog.d/step-9.md"})

    def test_release_orders_past_999_by_number(self):
        frag(self.d, "step-1000.md", "### Fixed\n\n- thousand\n")
        frag(self.d, "step-999.md", "### Fixed\n\n- ninety-nine\n")
        self.commit_all("two more")
        out = self.release("patch")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("### Fixed\n\n- nine\n- ten-fix\n- ninety-nine\n- thousand\n", read(self.root, "CHANGELOG.md"))

    def test_release_dry_run_lists_the_fragments_and_touches_nothing(self):
        before = self.snapshot()
        out = self.release("9.9.9", "--dry-run")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("changelog.d/step-9.md", out.stdout)
        self.assertIn("changelog.d/step-10.md", out.stdout)
        self.assertIn("$ git rm -q -- changelog.d/step-9.md changelog.d/step-10.md", out.stdout)
        self.assertLess(out.stdout.index("step-9.md"), out.stdout.index("step-10.md"))
        self.assertEqual(self.snapshot(), before)

    def test_release_without_changelog_d_is_the_old_stamp_byte_for_byte(self):
        self.git("rm", "-q", "-r", "changelog.d")
        self.git("commit", "-q", "-m", "no fragments")
        out = self.release("9.9.9")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(read(self.root, "CHANGELOG.md"), old_stamp(LOG, "9.9.9"))
        self.assertEqual(self.changed(), {f"M\t{f}" for f in self.FILES_COMMITTED})

    def test_release_with_only_the_readme_is_the_old_stamp_byte_for_byte(self):
        self.git("rm", "-q", "changelog.d/step-9.md", "changelog.d/step-10.md")
        self.git("commit", "-q", "-m", "readme only")
        out = self.release("9.9.9")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(read(self.root, "CHANGELOG.md"), old_stamp(LOG, "9.9.9"))
        self.assertEqual(self.git("ls-files", "changelog.d"), "changelog.d/README.md")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_release_refuses_a_bad_fragment_before_it_bumps(self):
        frag(self.d, "step-11.md", "loose\n\n### Fixed\n\n- x\n")
        self.commit_all("bad fragment")
        for args in (["patch"], ["patch", "--dry-run"]):
            with self.subTest(args=args):
                out = self.refused(args, "step-11.md:1:")
                self.assertIn("outside a ### section", out.stderr)
                self.assertNotIn("uv version", out.stdout, "refused AFTER uv ran")

    def test_release_refuses_a_fragment_git_ignores_before_it_bumps(self):
        """A *.md hidden by .git/info/exclude passes the clean-tree check; the
        two-way check refuses it before anything is written."""
        exclude = Path(self.root) / ".git" / "info" / "exclude"
        exclude.parent.mkdir(exist_ok=True)
        exclude.write_text("changelog.d/hidden.md\n")
        frag(self.d, "hidden.md", "### Fixed\n\n- h\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        for args in (["patch"], ["patch", "--dry-run"]):
            with self.subTest(args=args):
                out = self.refused(args, "changelog.d/hidden.md")
                self.assertIn("does not track", out.stderr)
                self.assertNotIn("uv version", out.stdout, "refused AFTER uv ran")

    def test_release_refuses_a_tracked_stray_before_it_bumps(self):
        """A tracked file the collector would not read refuses, named."""
        for rel in ("changelog.d/x.markdown", "changelog.d/sub/x.md", "changelog.d/sub/README.md",
                    "changelog.d/notes.txt"):
            with self.subTest(rel=rel):
                p = Path(self.root) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("### Fixed\n\n- s\n")
                self.commit_all(f"stray {rel}")
                for args in (["patch"], ["patch", "--dry-run"]):
                    out = self.refused(args, rel)
                    self.assertIn("not a fragment the release reads", out.stderr)
                    self.assertIn("changelog.d/<slug>.md", out.stderr)
                    self.assertNotIn("uv version", out.stdout, "refused AFTER uv ran")
                self.git("rm", "-q", "-r", "--", rel)
                self.git("commit", "-q", "-m", f"unstray {rel}")

    def test_release_passes_an_ignored_file_that_is_not_a_fragment(self):
        """Finder's .DS_Store: ignored, not *.md, so neither side of the check sees it."""
        exclude = Path(self.root) / ".git" / "info" / "exclude"
        exclude.parent.mkdir(exist_ok=True)
        exclude.write_text(".DS_Store\n")
        (self.d / ".DS_Store").write_bytes(b"\0\1")
        out = self.release("9.9.9")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(self.git("cat-file", "-t", "v9.9.9"), "tag")

    def test_release_refuses_an_untracked_fragment_as_a_dirty_tree(self):
        frag(self.d, "step-14.md", "### Fixed\n\n- n\n")
        self.refused(["9.9.9"], "working tree is not clean")

    def test_check_left_refuses_a_fragment_still_tracked(self):
        """The post-rm self-check reads git: a tracked fragment left behind refuses."""
        with contextlib.chdir(self.root), mock.patch.dict(os.environ, self.env, clear=True):
            with self.assertRaises(SystemExit) as e:
                release.check_left()
            self.assertIn("changelog.d/step-10.md", str(e.exception.code))
            self.assertIn("changelog.d/step-9.md", str(e.exception.code))
            self.git("rm", "-q", "changelog.d/step-9.md", "changelog.d/step-10.md")
            release.check_left()  # only README.md left: passes

    def test_check_left_reads_git_not_the_glob(self):
        """A tracked file the glob never chose (a nested one) still fails it."""
        frag(self.d / "sub", "x.md", "### Fixed\n\n- x\n")
        self.git("add", "-A")
        self.git("rm", "-q", "changelog.d/step-9.md", "changelog.d/step-10.md")
        with contextlib.chdir(self.root), mock.patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(release.fragment_paths(), [])
            with self.assertRaises(SystemExit) as e:
                release.check_left()
        self.assertIn("changelog.d/sub/x.md", str(e.exception.code))

    def test_preview_in_a_repo_leaves_git_as_it_was(self):
        before = self.snapshot()
        out = self.release("--preview")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, "## [Unreleased]\n\n### Added\n\n- ten\n\n### Fixed\n\n- nine\n- ten-fix\n")
        self.assertEqual(self.snapshot(), before)


assert "CHANGELOG.md" in FILES  # the scratch repo carries the CHANGELOG this file rewrites


if __name__ == "__main__":
    unittest.main()
