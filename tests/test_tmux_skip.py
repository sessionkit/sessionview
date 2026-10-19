"""Without tmux, a test that needs it is a LOUD skip naming tmux, never an error.

tmux is a documented prerequisite (brew install tmux). A strict shape without it
once gave 77 errors, every one `FileNotFoundError: ... 'tmux'`, most raised by
private_tmux's own cleanup running a kill-server that could not exist (SV-172).
"""
import os
import re
import unittest
from unittest import mock

from tests import support

TESTS = os.path.dirname(os.path.abspath(__file__))


class TmuxSkip(unittest.TestCase):
    def test_the_reason_names_tmux_and_how_to_get_it(self):
        self.assertIn("needs tmux", support.TMUX_SKIP)
        self.assertIn("brew install tmux", support.TMUX_SKIP)

    def test_require_tmux_skips_when_tmux_is_absent(self):
        with mock.patch.object(support, "have_tmux", return_value=False):
            with self.assertRaises(unittest.SkipTest) as cm:
                support.require_tmux()
        self.assertEqual(str(cm.exception), support.TMUX_SKIP)

    def test_a_private_tmux_without_tmux_skips_and_cleans_up_quietly(self):
        with mock.patch.object(support, "have_tmux", return_value=False):
            with support.private_tmux("skip") as pt:
                d = pt.tmpdir
                with self.assertRaises(unittest.SkipTest):
                    pt.tmux("list-sessions")
            # The cleanup ran no tmux (none to run) and still removed the dir.
            self.assertFalse(os.path.exists(d))

    def test_every_tmux_skip_uses_the_one_reason(self):
        # A quiet or ad hoc reason ("no tmux on PATH") hides the prerequisite.
        ad_hoc = re.compile(r"""skip\w*\([^)]*["'][^"']*tmux[^"']*["']""", re.I)
        hits = []
        for name in sorted(os.listdir(TESTS)):
            if not name.endswith(".py") or name == os.path.basename(__file__):
                continue
            with open(os.path.join(TESTS, name), encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    if ad_hoc.search(line):
                        hits.append(f"{name}:{n}")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
