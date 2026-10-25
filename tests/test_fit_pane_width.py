"""bin/tmux-sidebar: fit() decides from the pane's width as tmux has it, not
from the pty's size (SV-195).

The pty's size reaches the sidebar AFTER tmux has resized its pane. A render
that lands in between reads the old width from the pty in a window that has
already changed. fit() once trusted that: on a terminal resize from 160 to
120 columns it saw cols 34 == the wish, put nothing back, and left the
14-wide pane tmux had made. The next render read cols 14 in the same window,
took it for a border drag, and wrote width 14 to view.json (natural timing,
4 of 30 resizes, SV-195 rca-001).

These tests drive fit() itself with the inputs of that moment: the terminal
size and the one tmux reply are stubbed, and every command fit() would run is
recorded, not run. No tmux server is addressed. The sidebar runs in a
subprocess on a scratch HOME, as tests/test_pinned_agents.py does.

The known risk of reading #{pane_width} is a drag in flight: a fit() that
is running while the border moves must never put the old width back. Two
tests hold that: a drag that tmux has applied before the pty catches up is
adopted, and a fit() that read the pane BEFORE a drag issues no resize, so
a drag that lands after its read is not undone.
"""
import json
import os
import subprocess
import sys
import textwrap
import unittest

from tests import support

SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")

HARNESS = textwrap.dedent('''
    import importlib.machinery, importlib.util, json, os, subprocess, sys
    loader = importlib.machinery.SourceFileLoader("sidebar", sys.argv[1])
    spec = importlib.util.spec_from_loader("sidebar", loader)
    m = importlib.util.module_from_spec(spec)
    a = json.loads(sys.argv[2])
    if "seed" in a:   # the frame's starting record, in the env the sidebar starts with
        os.environ["SESSIONVIEW_FIT_SEED"] = a["seed"]
    loader.exec_module(m)
    seed = dict(m._FIT)
    seed_left = os.environ.get("SESSIONVIEW_FIT_SEED")
    calls = []
    def run(argv, *x, **k):
        calls.append([os.path.basename(argv[0])] + list(argv[1:]))
        return subprocess.CompletedProcess(argv, 0, "", "")
    m.subprocess.run = run
    m.sh = lambda argv: (calls.append(["sh"] + list(argv)) or a["tmux"])
    m.os.get_terminal_size = lambda *x: os.terminal_size((a["cols"], 40))
    os.environ["SESSIONVIEW_FRAME"] = "sv-test-fit:frame-1"
    os.environ["TMUX_PANE"] = "%9"
    m.CFG["width"] = a["width"]
    m.CFG["fit"] = "fixed"
    if "seed" not in a:
        m._FIT.update(win=a["win"], pane=a["known"])
    m.fit()
    print(json.dumps({"calls": calls, "width": m.CFG["width"], "WIDTH": m.WIDTH,
                      "fit": dict(m._FIT), "seed": seed, "seed_left": seed_left}))
''')


class FitReadsThePane(unittest.TestCase):
    def setUp(self):
        self._scratch = support.scratch_env()
        self.env, _ = self._scratch.__enter__()

    def tearDown(self):
        self._scratch.__exit__(None, None, None)

    def fit(self, *, cols, tmux, win=None, known=None, width=34, seed=None):
        """Run one fit(): the pty says COLS, tmux answers TMUX to the
        display-message, and fit() last settled KNOWN in window WIN. With
        SEED, no fit() has run yet: the sidebar starts with
        SESSIONVIEW_FIT_SEED=SEED, as the frame sets it."""
        a = {"cols": cols, "tmux": tmux, "win": win, "known": known, "width": width}
        if seed is not None:
            a["seed"] = seed
        r = subprocess.run([sys.executable, "-B", "-c", HARNESS, SIDEBAR, json.dumps(a)],
                           env=self.env, capture_output=True, text=True, timeout=60,
                           cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout.splitlines()[-1])
        got["resizes"] = [c for c in got["calls"] if c[0] == "tmux" and "resize-pane" in c]
        got["writes"] = [c[1:] for c in got["calls"] if c[0] == "sessionview-config"]
        return got

    def test_the_one_tmux_call_asks_for_the_pane_width(self):
        got = self.fit(cols=34, tmux="160 1 34", win="160", known=34)
        asks = [c for c in got["calls"] if c[0] == "sh"]
        self.assertEqual(len(asks), 1, got["calls"])
        self.assertIn("#{pane_width}", asks[0][-1])

    def test_a_width_resize_read_before_the_pty_catches_up_puts_the_wish_back(self):
        """The window went 160 -> 120 and tmux made the pane 14; the pty
        still says 34. fit() must put 34 back and remember nothing. It
        used to see cols == the wish and leave 14 for the next render to
        adopt (SV-195 rca-001, run-widthtrace-P run 18)."""
        got = self.fit(cols=34, tmux="120 1 14", win="160", known=34)
        self.assertEqual(got["writes"], [], "a terminal resize was remembered as a drag")
        self.assertEqual(got["resizes"], [["tmux", "-L", "sv-test-fit", "resize-pane",
                                           "-t", "%9", "-x", "34"]])
        self.assertEqual((got["width"], got["fit"]["pane"], got["fit"]["win"]), (34, 34, "120"))

    def test_the_next_render_after_the_put_back_adopts_nothing(self):
        """Then the pty catches up with a pane that tmux has already
        moved: whatever cols says, the pane is the wish, so nothing is
        written and nothing is resized."""
        for cols in (14, 34, 54):
            with self.subTest(cols=cols):
                got = self.fit(cols=cols, tmux="120 1 34", win="120", known=34)
                self.assertEqual((got["writes"], got["resizes"]), ([], []))
                self.assertEqual(got["WIDTH"], min(34, cols), "cols no longer clamps the drawing")

    def test_a_drag_tmux_has_applied_is_adopted_before_the_pty_catches_up(self):
        """A drag in flight: tmux moved the border to 50, the pty still says
        34. That is the drag, adopted now; 34 is never put back."""
        got = self.fit(cols=34, tmux="160 1 50", win="160", known=34)
        self.assertEqual(got["resizes"], [], "a drag in flight was undone")
        self.assertEqual(got["writes"], [["set", "width", "50"]])
        self.assertEqual((got["width"], got["fit"]["pane"]), (50, 50))
        self.assertEqual(got["WIDTH"], 34, "cols no longer clamps the drawing")

    def test_a_fit_that_read_the_pane_before_a_drag_resizes_nothing(self):
        """A fit() that read the pane before the drag, in the same window,
        sees the wish and issues no resize-pane, so a drag landing after
        its read cannot be put back by it. The pty may already say 50."""
        for cols in (34, 50):
            with self.subTest(cols=cols):
                got = self.fit(cols=cols, tmux="160 1 34", win="160", known=34)
                self.assertEqual((got["writes"], got["resizes"]), ([], []))

    def test_a_slip_below_min_drag_is_put_back(self):
        got = self.fit(cols=34, tmux="160 1 9", win="160", known=34)
        self.assertEqual(got["writes"], [])
        self.assertEqual([c[-1] for c in got["resizes"]], ["34"])

    def test_no_pane_width_in_the_reply_falls_back_to_the_pty(self):
        """An older reply with no third field (or none at all) behaves as
        before: the pty's cols decide."""
        got = self.fit(cols=50, tmux="160 1", win="160", known=34)
        self.assertEqual(got["writes"], [["set", "width", "50"]])
        got = self.fit(cols=34, tmux="", win="160", known=34)
        self.assertEqual((got["writes"], got["resizes"]), ([], []))


class FirstFitJudgesAgainstTheFrameSeed(unittest.TestCase):
    """The first fit() after a slow first render. The frame's window is born
    at the terminal's size and the frame hands the sidebar a starting record,
    SESSIONVIEW_FIT_SEED="WIN PANE": the window width it was born at and the
    width it gave the sidebar pane. With no fit() before it, the first fit()
    once had nothing to compare with (_FIT was None, None), so a drag made
    before the first render was put back as a terminal resize (30 of 30 in
    the counted repro). The seed is read once, at start, and never written
    to the pane."""

    setUp = FitReadsThePane.setUp
    tearDown = FitReadsThePane.tearDown
    fit = FitReadsThePane.fit

    def test_a_drag_before_the_first_fit_is_adopted(self):
        """Same window as the frame was born at, the pane moved: a drag."""
        got = self.fit(cols=34, tmux="160 1 50", seed="160 34")
        self.assertEqual(got["seed"], {"win": "160", "pane": 34})
        self.assertEqual(got["resizes"], [], "a drag before the first render was put back")
        self.assertEqual(got["writes"], [["set", "width", "50"]])
        self.assertEqual((got["width"], got["fit"]), (50, {"win": "160", "pane": 50}))

    def test_a_changed_window_still_puts_the_wish_back(self):
        """The window is not the one the frame was born at: a terminal
        resize. The wish goes back and nothing is remembered."""
        got = self.fit(cols=34, tmux="120 1 14", seed="160 34")
        self.assertEqual(got["writes"], [], "a terminal resize was remembered as a drag")
        self.assertEqual(got["resizes"], [["tmux", "-L", "sv-test-fit", "resize-pane",
                                           "-t", "%9", "-x", "34"]])
        self.assertEqual(got["fit"], {"win": "120", "pane": 34})

    def test_no_drag_does_nothing(self):
        got = self.fit(cols=34, tmux="160 1 34", seed="160 34")
        self.assertEqual((got["writes"], got["resizes"]), ([], []))

    def test_before_a_client_attaches_nothing_is_adopted(self):
        """The frame's own split and resize change the pane in the same
        window before the attach: put back, never remembered, seed or not."""
        got = self.fit(cols=80, tmux="160 0 80", seed="160 34")
        self.assertEqual(got["writes"], [])
        self.assertEqual([c[-1] for c in got["resizes"]], ["34"])

    def test_the_seed_is_read_once_and_leaves_the_environment(self):
        got = self.fit(cols=34, tmux="160 1 34", seed="160 34")
        self.assertIsNone(got["seed_left"], "the seed stayed in the env for children to inherit")

    def test_a_bad_seed_is_no_seed(self):
        """Anything but two positive numbers: the old start, nothing known,
        so the first attached fit() puts the wish back."""
        for seed in ("", "160", "160 34 1", "abc 34", "160 -3", "0 34", "160 x"):
            with self.subTest(seed=seed):
                got = self.fit(cols=34, tmux="160 1 50", seed=seed)
                self.assertEqual(got["seed"], {"win": None, "pane": None})
                self.assertEqual(got["writes"], [])
                self.assertEqual([c[-1] for c in got["resizes"]], ["34"])


if __name__ == "__main__":
    unittest.main()
