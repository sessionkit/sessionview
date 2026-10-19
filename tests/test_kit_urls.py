"""Guard: a shipped file points at the kit's repos under their current owner.

The kit's repos (sessionview, sessionmail, sessiontools, sessionvoice,
sessionkit, sessionphone) live at github.com/sessionkit/<name>. A URL that
names one of them under the previous owner sends a user to the wrong place,
so it is a hit in any file `git archive HEAD` ships (export-ignore honoured),
except:

- tests/, whose fixtures quote the old form on purpose;
- README.md, which has its own link checks.

The repo name is matched whole: a different repo under the previous owner
(show-me, or sessionview-extra) is not a hit. Both the https form
(github.com/<owner>/<name>) and the ssh form (github.com:<owner>/<name>)
are read. The previous owner's handle is stored rot13 and decoded at run time,
so this file does not trip itself. On a hit the test prints path:count and
never the matched text.
"""
import codecs
import collections
import io
import re
import subprocess
import tarfile
import unittest

from tests import support

#: the previous owner of the kit's repos, rot13
OLD_OWNER = codecs.decode("zonvyrl", "rot13")
NEW_OWNER = "sessionkit"
KIT_REPOS = ("sessionview", "sessionmail", "sessiontools", "sessionvoice",
             "sessionkit", "sessionphone")

OLD_URL_RE = re.compile(
    r"github\.com[/:]%s/(?:%s)\b(?!-)"
    % (re.escape(OLD_OWNER), "|".join(map(re.escape, KIT_REPOS))),
    re.IGNORECASE)

SKIP_DIRS = ("tests/",)
SKIP_FILES = frozenset({"README.md"})


def in_scope(path):
    """True when `path` (an archive member name) is a shipped file this guard reads."""
    return not path.startswith(SKIP_DIRS) and path not in SKIP_FILES


def old_url_hits(text):
    """How many lines of `text` name a kit repo under the previous owner."""
    return sum(1 for line in text.splitlines() if OLD_URL_RE.search(line))


def scan_archive(data):
    """{path: lines hit} over the in-scope files of the tar bytes `data`."""
    found = collections.Counter()
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            if not member.isfile() or not in_scope(member.name):
                continue
            raw = tar.extractfile(member).read()
            if b"\0" in raw[:8192]:
                continue        # a binary (the Dock icon): its bytes are noise
            hits = old_url_hits(raw.decode("utf8", "replace"))
            if hits:
                found[member.name] = hits
    return found


class KitUrls(unittest.TestCase):
    def test_pattern(self):
        old = OLD_OWNER
        for text in ("git clone https://github.com/%s/sessionview ~/Code/sessionview" % old,
                     "not installed (github.com/%s/sessionmail)" % old,
                     "git@github.com:%s/sessiontools.git" % old,
                     "https://github.com/%s/sessionvoice/tree/master" % old,
                     "github.com/%s/sessionkit." % old,
                     "see https://GitHub.com/%s/SessionPhone" % old.upper()):
            with self.subTest(text=text):
                self.assertEqual(old_url_hits(text), 1)
        for text in ("show-me (github.com/%s/show-me) is referenced" % old,
                     "github.com/%s/sessionview-extra" % old,
                     "github.com/%s/sessionviewer" % old,
                     "github.com/%s/session" % old,
                     "git clone https://github.com/%s/sessionview" % NEW_OWNER,
                     "(github.com/%s/sessionmail)" % NEW_OWNER,
                     "github.com/%sx/sessionview" % old,
                     "sessionview and sessionmail, no URL"):
            with self.subTest(text=text):
                self.assertEqual(old_url_hits(text), 0)
        self.assertEqual(old_url_hits(
            "github.com/%s/sessionview\nok\ngithub.com/%s/sessionmail github.com/%s/sessionkit"
            % (old, old, old)), 2)

    def test_scope(self):
        for path in ("bin/sessionview-install", "bin/sessionview-messages", "lib/python.sh",
                     "src/sessionview/__init__.py", "skills/tmux/SKILL.md", "docs/install.md",
                     "config/config.json", "CHANGELOG.md", "pyproject.toml",
                     "docs/README.md", "testsx/tool"):
            with self.subTest(path=path):
                self.assertTrue(in_scope(path))
        for path in ("README.md", "tests/test_docs.py", "tests/support.py"):
            with self.subTest(path=path):
                self.assertFalse(in_scope(path))

    def test_scan_flags_a_planted_url_outside_tests_and_readme(self):
        planted = ("# see github.com/%s/sessionmail\n" % OLD_OWNER).encode()
        names = ("bin/tool", "src/x/y.py", "docs/planted.md", "skills/x/SKILL.md",
                 "README.md", "tests/test_x.py", "macos/icon.icns")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for name in names:
                body = b"\0" + planted if name.endswith(".icns") else planted
                info = tarfile.TarInfo(name)
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
        self.assertEqual(dict(scan_archive(buf.getvalue())),
                         {"bin/tool": 1, "src/x/y.py": 1, "docs/planted.md": 1,
                          "skills/x/SKILL.md": 1})

    def test_exported_files_name_kit_repos_under_current_owner(self):
        try:
            data = subprocess.check_output(
                ["git", "-C", support.REPO, "archive", "HEAD"], stderr=subprocess.DEVNULL)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("not a git checkout: no git archive HEAD")
        found = scan_archive(data)
        report = "\n".join("  %s:%d" % (p, n) for p, n in sorted(found.items()))
        if found:
            self.fail("kit repo URLs under the previous owner in git archive HEAD;"
                      " point them at github.com/%s/<name> (path:count):\n%s"
                      % (NEW_OWNER, report))


if __name__ == "__main__":
    unittest.main()
