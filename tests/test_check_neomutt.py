"""`sessionview install --check` passes when neomutt is the only gap.

neomutt serves the `messages` tab alone, and sessionview makes that tab only
when sessionmail, which is optional, is installed. So a missing neomutt is a
WARN that names the tab and sessionmail, and the check still ends `ready`
with exit 0. It once said MISSING and `not ready` (exit 1), and a stranger
whose install never asked for neomutt read a failed install.

Each case runs the check on a PATH that holds stand-ins for every other
requirement (tmux 3.7, the suite's Python, `session`, a notmuch that indexes
Type and Project), then /usr/bin and /bin for the shell's own tools. neomutt
is on that PATH only when a case puts a stand-in there.
"""
import os
import re
import shutil
import subprocess
import sys
import unittest

from tests import support

INSTALLER = os.path.join(support.BIN, "sessionview-install")

NOTMUCH = """#!/bin/sh
# `notmuch config get index.header.X` answers X: both headers indexed.
[ "$1 $2" = "config get" ] && echo "${3#index.header.}"
exit 0
"""


def shim(bindir, name, text):
    p = os.path.join(bindir, name)
    with open(p, "w") as f:
        f.write(text)
    os.chmod(p, 0o755)


class CheckWithoutNeomutt(unittest.TestCase):
    def setUp(self):
        ctx = support.scratch_env()
        self.env, self.home = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        self.home = os.path.realpath(self.home)
        self.env["PREFIX"] = os.path.join(self.home, ".local")
        self.shims = os.path.join(self.home, "shims")
        os.makedirs(self.shims)
        shim(self.shims, "tmux", "#!/bin/sh\necho 'tmux 3.7'\n")
        shim(self.shims, "session", "#!/bin/sh\nexit 0\n")
        shim(self.shims, "notmuch", NOTMUCH)
        os.symlink(sys.executable, os.path.join(self.shims, "python3"))
        self.env["PATH"] = os.pathsep.join([self.shims, "/usr/bin", "/bin"])
        # The probe would find the suite's Python on PATH anyway; say it outright.
        self.env["SESSIONVIEW_PYTHON"] = sys.executable
        for tool in ("neomutt", "tmux", "notmuch", "session"):
            found = shutil.which(tool, path=self.env["PATH"])
            want = None if tool == "neomutt" else os.path.join(self.shims, tool)
            self.assertEqual(found, want, f"{tool} on the scratch PATH")

    def check(self):
        return subprocess.run([INSTALLER, "--check"], env=self.env, cwd=support.REPO,
                              capture_output=True, text=True, timeout=60)

    def line(self, r, name):
        """The one requirement line about NAME, as (verdict, text)."""
        hits = [m.groups() for m in re.finditer(r"(?m)^  (\S+) +(%s\b.*)$" % re.escape(name),
                                                r.stdout)]
        self.assertEqual(len(hits), 1, r.stdout)
        return hits[0]

    def test_only_neomutt_missing_is_a_warn_and_ready(self):
        r = self.check()
        verdict, text = self.line(r, "neomutt")
        self.assertEqual(verdict, "WARN", r.stdout)
        self.assertIn("messages tab", text)
        self.assertIn("sessionmail", text)
        self.assertIn("brew install neomutt", text)
        self.assertNotIn("MISSING", r.stdout)
        self.assertNotIn("not ready", r.stdout)
        self.assertIn("ready: open a NEW terminal", r.stdout)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_neomutt_with_notmuch_passes(self):
        shim(self.shims, "neomutt", "#!/bin/sh\nprintf 'NeoMutt 20250905\\n+notmuch\\n'\n")
        r = self.check()
        self.assertEqual(self.line(r, "neomutt"), ("PASS", "neomutt 20250905 with notmuch"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_real_gap_still_fails(self):
        # The same scratch PATH can fail: without tmux it says MISSING, not ready.
        os.remove(os.path.join(self.shims, "tmux"))
        r = self.check()
        self.assertEqual(self.line(r, "tmux")[0], "MISSING", r.stdout)
        self.assertEqual(self.line(r, "neomutt")[0], "WARN", r.stdout)
        self.assertIn("not ready", r.stdout)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
