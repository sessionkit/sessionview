"""Guard: the shipped code names no person, quotes no one and names no host.

The scan runs over `git archive HEAD`, the tree an export ships (export-ignore
honoured), and reads the CODE paths only: bin/, lib/, plugins/, tmux/,
macos/, skills/*/scripts/, config/neomuttrc and tests/. The docs have their
own checks. A hit is one of:

- a crew or third-party first name, any case (the operator included);
- a capitalised crew name whose lowercase is also a common word or a tool
  (`pip` the installer, `brew doctor`, `.tars`), so only the capitalised form
  is a hit;
- a fleet host name, any case;
- the shape of an attributed quote: `voice` followed by a time or a weekday,
  or a capitalised ruling word.

Keep-list: the package author metadata and CODEOWNERS. Both sit outside the
code paths, and the list says so explicitly, so a path change cannot pull
them in.

Reword a hit to the neutral fact: the operator becomes "the user", an example
agent becomes a placeholder (amy, bob, cleo, pat, zed), and a host becomes the
class of machine. Every word in the pattern is stored rot13 and decoded at run
time, so this file does not trip itself. On a hit the test prints path:count
and never the matched text.
"""
import codecs
import collections
import io
import re
import subprocess
import tarfile
import unittest

from tests import support


def _words(rot):
    return [codecs.decode(w, "rot13") for w in rot.split()]


# first names and hosts: a hit in any case
ANY_CASE = _words("zvxr pben nfgevq oelna wrnaavr fcneebj"       # people
                  " z5 zon zf1 zf2 xc01 snvyzbqr")                 # hosts
# a hit only as written: the lowercase word is a tool or a common word
AS_WRITTEN = _words("Cvc Qbpgbe GNEF EHYRQ EHYVATF")

NEUTRAL_RE = re.compile(
    r"(?i:\b(?:%s)\b)" % "|".join(map(re.escape, ANY_CASE))
    + r"|\b(?:%s)\b" % "|".join(map(re.escape, AS_WRITTEN))
    + r"|\bvoice,?\s+~?(?:[0-9]{1,2}:[0-9]{2}|(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b)")

CODE_DIRS = ("bin/", "lib/", "plugins/", "tmux/", "macos/", "tests/")
CODE_FILES = ("config/neomuttrc",)
SKILL_SCRIPT_RE = re.compile(r"skills/[^/]+/scripts/")
KEEP = frozenset({".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
                  "pyproject.toml", ".github/CODEOWNERS", "CODEOWNERS"})


def in_scope(path):
    """True when `path` (an archive member name) is a code path this guard reads."""
    if path in KEEP:
        return False
    return (path.startswith(CODE_DIRS) or path in CODE_FILES
            or SKILL_SCRIPT_RE.match(path) is not None)


def neutral_hits(text):
    """How many lines of `text` hold a name, a host or a quote's shape."""
    return sum(1 for line in text.splitlines() if NEUTRAL_RE.search(line))


def scan_archive(data):
    """{path: lines hit} over the code paths of the tar bytes `data`."""
    found = collections.Counter()
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            if not member.isfile() or not in_scope(member.name):
                continue
            raw = tar.extractfile(member).read()
            if b"\0" in raw[:8192]:
                continue        # a binary (the Dock icon): its bytes are noise
            hits = neutral_hits(raw.decode("utf8", "replace"))
            if hits:
                found[member.name] = hits
    return found


class CodeNeutral(unittest.TestCase):
    def test_pattern(self):
        operator, host = ANY_CASE[0], ANY_CASE[6]
        crew = AS_WRITTEN[0]
        for text in ("# asked by %s" % operator.capitalize(),
                     "# %s, on the laptop" % operator.upper(),
                     "measured on %s" % host,
                     "%s:sessionview" % host.upper(),
                     "# %s said so" % crew,
                     # built here so no quote's shape is spelled in this file
                     "(%s 12:34 Sun)" % "voice", "%s, Fri: yes" % "voice",
                     "%s ~12:34" % "voice"):
            with self.subTest(text=text):
                self.assertEqual(neutral_hits(text), 1)
        for text in ("uv %s install ." % crew.lower(),
                     "brew %s" % AS_WRITTEN[1].lower(),
                     "voicemode", "voice/tm are read off argv", 'when = "agent.voice"',
                     "summon an agent to voice: mail it",
                     "%sx" % operator, "x%s" % host, "amy bob cleo pat zed"):
            with self.subTest(text=text):
                self.assertEqual(neutral_hits(text), 0)
        self.assertEqual(neutral_hits("%s\nok\n%s %s" % (operator, host, operator)), 2)

    def test_scope(self):
        for path in ("bin/tmux-sidebar", "lib/python.sh", "plugins/session/plugin.toml",
                     "tmux/frame.conf", "macos/SessionView.applescript",
                     "skills/tmux/scripts/tmux-show", "config/neomuttrc",
                     "tests/support.py"):
            with self.subTest(path=path):
                self.assertTrue(in_scope(path))
        for path in ("README.md", "docs/install.md", "config/config.json", "config/README.md",
                     "skills/tmux/SKILL.md", "SPEC.md", "src/sessionview/__init__.py",
                     ".github/CODEOWNERS", ".claude-plugin/plugin.json", "pyproject.toml",
                     "binx/tool"):
            with self.subTest(path=path):
                self.assertFalse(in_scope(path))

    def test_scan_flags_a_planted_name_in_code_only(self):
        planted = ("# planted by %s\n" % ANY_CASE[1].capitalize()).encode()
        names = ("bin/tool", "tests/test_x.py", "skills/x/scripts/y", "config/neomuttrc",
                 "docs/planted.md", "config/config.json", ".github/CODEOWNERS",
                 "macos/icon.icns")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for name in names:
                body = b"\0" + planted if name.endswith(".icns") else planted
                info = tarfile.TarInfo(name)
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
        self.assertEqual(dict(scan_archive(buf.getvalue())),
                         {"bin/tool": 1, "tests/test_x.py": 1, "skills/x/scripts/y": 1,
                          "config/neomuttrc": 1})

    def test_exported_code_is_neutral(self):
        try:
            data = subprocess.check_output(
                ["git", "-C", support.REPO, "archive", "HEAD"], stderr=subprocess.DEVNULL)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("not a git checkout: no git archive HEAD")
        found = scan_archive(data)
        report = "\n".join("  %s:%d" % (p, n) for p, n in sorted(found.items()))
        if found:
            self.fail("names, hosts or quotes in the code of git archive HEAD"
                      " (path:count):\n" + report)


if __name__ == "__main__":
    unittest.main()
