"""What `git archive` ships is the release: the tarball a stranger downloads.
SPINE.md is the crew's internal planning slate and must stay out of it, by
its `export-ignore` line in .gitattributes. changelog.d/ is the other way: it
ships, so the pre-publish scan reads the entries still pending there, and a
release commit holds only its README.md. SESSIONVIEW_ARCHIVE_REF points the
check at another commit (default HEAD), so the guard can be shown failing on
a commit from before that line."""
import os
import subprocess
import unittest

from tests import support

REF = os.environ.get("SESSIONVIEW_ARCHIVE_REF") or "HEAD"

#: Files that exist in the repo but must never reach the release archive.
NOT_SHIPPED = ("SPINE.md",)

#: Files that must reach it: an export-ignore on changelog.d/ would hide the
#: pending entries from the scan.
SHIPPED = ("changelog.d/README.md",)


def _git(*args):
    return subprocess.run(["git", "-C", support.REPO, *args],
                          capture_output=True, check=False)


@unittest.skipUnless(_git("rev-parse", "--git-dir").returncode == 0,
                     "not a git checkout (an unpacked archive has no history)")
class ReleaseArchive(unittest.TestCase):
    def setUp(self):
        # `git archive` honours the .gitattributes of the tree it archives,
        # so the check is of the commit, not of the working tree.
        archive = _git("archive", "--format=tar", REF)
        self.assertEqual(archive.returncode, 0, archive.stderr.decode(errors="replace"))
        listing = subprocess.run(["tar", "-tf", "-"], input=archive.stdout,
                                 capture_output=True, check=True)
        self.names = set(listing.stdout.decode().splitlines())

    def test_internal_notes_are_not_shipped(self):
        for name in NOT_SHIPPED:
            with self.subTest(name=name):
                # assertFalse, not assertNotIn: a failure names the file,
                # not every path in the archive.
                self.assertFalse(name in self.names,
                                 f"{name} is in `git archive {REF}`: is its export-ignore line in .gitattributes?")

    def test_changelog_d_is_shipped(self):
        for name in SHIPPED:
            with self.subTest(name=name):
                self.assertTrue(name in self.names,
                                f"{name} is not in `git archive {REF}`: is changelog.d/ export-ignored in .gitattributes?")

    def test_the_archive_is_not_empty(self):
        # A guard that lists nothing would pass vacuously.
        self.assertIn("README.md", self.names)


if __name__ == "__main__":
    unittest.main()
