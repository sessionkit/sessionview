"""Guard: the shipped code carries no tracker ID.

A comment in shipped code states the fact, never the ticket it came from: an
ID means nothing to a reader outside the tracker, and the history already
lives in the CHANGELOG and in git. This reads bin/, lib/ and the Makefile,
the same scope as

    git grep -nE '<the pattern>' -- bin/ lib/ Makefile

and fails on any line where the pattern matches: two to five capitals, a dash
and a number. The tests may still name an ID; this file does not need to. The
pattern is built from its parts below and every example ID is joined at run
time, so nothing here spells one.

Reword a hit to the plain fact ("measured", "the frame once put back the
start width"); never just drop the ID and lose the sense. On a hit the test
prints path:line and the line.
"""
import os
import re
import subprocess
import tempfile
import unittest

from tests import support

#: the ID shape: a project code of 2-5 capitals, a dash, a number
ID_RE = re.compile("[A-Z]{2,5}" + "-" + "[0-9]+")

#: the shipped code this guard reads, as git pathspecs
SCOPE = ("bin/", "lib/", "Makefile")


def _id(code, number):
    """An example ID, joined here so this file never spells one."""
    return "-".join((code, str(number)))


def _git(repo, *args):
    """The stdout of `git -C repo args`, or None when git fails or is missing."""
    try:
        return subprocess.check_output(["git", "-C", repo] + list(args),
                                       stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return None


def is_checkout(repo):
    """True when `repo` is the top of its own git checkout.

    A tree unpacked inside some other checkout is not one: git would answer
    for the outer repo, where none of these files is tracked, and the scan
    would read nothing.
    """
    top = _git(repo, "rev-parse", "--show-toplevel")
    return top is not None and (
        os.path.realpath(top.decode("utf8", "replace").strip()) == os.path.realpath(repo))


def tracked_paths(repo):
    """The tracked files in SCOPE, or a walk of them when `repo` is no git checkout."""
    out = _git(repo, "ls-files", "-z", "--", *SCOPE) if is_checkout(repo) else None
    if out is not None:
        return sorted(p for p in out.decode("utf8", "replace").split("\0") if p)
    found = []
    for top in SCOPE:
        full = os.path.join(repo, top)
        if os.path.isfile(full):
            found.append(top)
            continue
        for root, dirs, files in os.walk(full):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                found.append(os.path.relpath(os.path.join(root, name), repo))
    return sorted(found)


def id_hits(text):
    """[(line number, line)] for each line of `text` that holds an ID."""
    return [(n, line) for n, line in enumerate(text.splitlines(), 1) if ID_RE.search(line)]


def scan(repo):
    """[(path, line number, line)] over the shipped code under `repo`."""
    hits = []
    for path in tracked_paths(repo):
        try:
            with open(os.path.join(repo, path), "rb") as fh:
                raw = fh.read()
        except OSError:
            continue        # tracked but gone from the tree: nothing to ship
        if b"\0" in raw[:8192]:
            continue        # a binary: its bytes are noise
        hits.extend((path, n, line) for n, line in id_hits(raw.decode("utf8", "replace")))
    return hits


class CodeNoTrackerIds(unittest.TestCase):
    def test_pattern(self):
        for text in ("# measured (%s)" % _id("AB", 12),
                     "x = 1  # see %s." % _id("ABCDE", 7),
                     "%s, measured" % _id("XY", 1000),
                     "# fixed by %s and %s" % (_id("AB", 1), _id("CD", 2))):
            with self.subTest(text=text):
                self.assertEqual(len(id_hits(text)), 1)
        for text in ("# measured, once", "A-1 is no ID", "utf-8", "x-11",
                     "LC_ALL=C", "[A-Z]{2,5}", "AB-", "-12"):
            with self.subTest(text=text):
                self.assertEqual(id_hits(text), [])
        self.assertEqual(id_hits("ok\n%s\nok\n" % _id("AB", 3)), [(2, _id("AB", 3))])

    def test_scope(self):
        paths = tracked_paths(support.REPO)
        self.assertIn("Makefile", paths)
        self.assertIn("bin/tmux-sidebar", paths)
        self.assertTrue(any(p.startswith("lib/") for p in paths))
        self.assertFalse([p for p in paths if not p.startswith(SCOPE)])

    def _plant(self, root):
        """A small shipped tree under `root`: one ID in bin/, none elsewhere."""
        for path, text in (("bin/tool", "# measured (%s)\n" % _id("AB", 12)),
                           ("lib/x.sh", "# measured\n"), ("Makefile", "test:\n"),
                           ("docs/x.md", "%s is fine in the docs\n" % _id("CD", 3))):
            os.makedirs(os.path.dirname(os.path.join(root, path)) or root, exist_ok=True)
            with open(os.path.join(root, path), "w") as fh:
                fh.write(text)

    def test_scan_reads_a_tree_that_is_no_checkout(self):
        # unpacked inside another checkout (a store, a dotfiles repo) or alone:
        # either way the walk reads it, and git is not asked about the outer repo
        if _git(".", "--version") is None:
            self.skipTest("git is not on PATH")
        with tempfile.TemporaryDirectory() as outer, tempfile.TemporaryDirectory() as alone:
            self.assertIsNotNone(_git(outer, "init", "-q"))
            for case, tree in (("nested", os.path.join(outer, "unpacked")), ("alone", alone)):
                with self.subTest(case=case):
                    self._plant(tree)
                    self.assertFalse(is_checkout(tree))
                    self.assertEqual([(p, n) for p, n, _ in scan(tree)], [("bin/tool", 1)])

    def test_scan_reads_tracked_files_in_a_checkout(self):
        if _git(".", "--version") is None:
            self.skipTest("git is not on PATH")
        with tempfile.TemporaryDirectory() as repo:
            self._plant(repo)
            self.assertIsNotNone(_git(repo, "init", "-q"))
            self.assertIsNotNone(_git(repo, "add", "bin", "lib", "Makefile", "docs"))
            with open(os.path.join(repo, "bin", "untracked"), "w") as fh:
                fh.write("# %s\n" % _id("EF", 4))    # git grep reads tracked files only
            self.assertTrue(is_checkout(repo))
            self.assertEqual([(p, n) for p, n, _ in scan(repo)], [("bin/tool", 1)])

    def test_shipped_code_has_no_tracker_id(self):
        hits = scan(support.REPO)
        if hits:
            self.fail("%d tracker ID line(s) in bin/, lib/ or the Makefile; reword each"
                      " to the plain fact:\n" % len(hits)
                      + "\n".join("  %s:%d: %s" % (p, n, line.strip()) for p, n, line in hits))


if __name__ == "__main__":
    unittest.main()
