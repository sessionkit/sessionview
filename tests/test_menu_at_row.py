"""bin/tmux-sidebar: an overlay menu opens beside the row that opened it
(SV-132), so it appears close to what was clicked.

A click or right-click on row N draws the box from row N+1, or ending at row
N-1 when it will not fit below; never off-pane. `s` anchors Switch store at
the store row. A menu opened with no row (a keyboard open) stays centred.

Every tmux call is on a private socket (support.private_tmux: `-L sv-test-*`
under a scratch TMUX_TMPDIR), reused from test_store_view's ViewBase. The
click case runs the real sidebar in a pane on that private server and feeds
it the SGR mouse bytes a click would.
"""
import os
import shlex
import sys
import time
import unittest

from tests import support
from tests.test_store_view import ANSI, SIDEBAR, ViewBase

TOP_L, BOT_L = "╭", "╰"     # the box's first and last rows: ╭ and ╰


def box_span(lines):
    """(first, last) line index of the drawn box, from its corner glyphs."""
    first = next(i for i, l in enumerate(lines) if TOP_L in l)
    last = next(i for i, l in enumerate(lines) if BOT_L in l)
    return first, last


class BoxTop(ViewBase):
    """box_top(): the placement rule itself, for every edge."""

    def test_the_rule(self):
        out = self.harness('''
            OUT["rows"] = [[a, n, h, m.box_top(a, n, h)] for a, n, h in [
                (None, 10, 40), (None, 50, 40),   # no anchor: centred, clamped at 0
                (2, 10, 40),                      # top: starts on the row below
                (20, 10, 40),                     # middle: starts below
                (29, 10, 40),                     # exactly fits below: 30..39
                (30, 10, 40),                     # one short: ends on the row above
                (39, 10, 40),                     # the bottom row: ends on 38
                (5, 10, 12),                      # fits neither side: clamped on-pane
                (3, 50, 40),                      # taller than the pane: from 0
                (60, 10, 40),                     # a stale anchor past the end
            ]]
        ''')
        got = {(a, n, h): t for a, n, h, t in out["rows"]}
        self.assertEqual(got[(None, 10, 40)], 15)
        self.assertEqual(got[(None, 50, 40)], 0)
        self.assertEqual(got[(2, 10, 40)], 3)
        self.assertEqual(got[(20, 10, 40)], 21)
        self.assertEqual(got[(29, 10, 40)], 30)
        self.assertEqual(got[(30, 10, 40)], 20)       # 20..29: ends at N-1
        self.assertEqual(got[(39, 10, 40)], 29)       # 29..38: ends at N-1
        self.assertEqual(got[(5, 10, 12)], 0)         # above would be -5: clamped to 0..9
        self.assertEqual(got[(3, 50, 40)], 0)
        self.assertEqual(got[(60, 10, 40)], 30)       # 30..39, on-pane
        for (a, n, h), t in got.items():
            self.assertGreaterEqual(t, 0)
            if n <= h:
                self.assertLessEqual(t + n, h, f"off-pane: anchor {a}, {n} rows in {h}")


class AnchoredOverlay(ViewBase):
    """render_base + overlay on a private server: the box lands beside the
    row each menu was opened from, top, middle and bottom."""

    H = 40

    def setUp(self):
        super().setUp()
        self.place("fx-legacy")
        self.sessions("store", "alpha", "beta")

    def draw(self, opener, height=None):
        """Render, run OPENER (python, may use `rows` = {target kind or
        session name: line index} and `base`), overlay, and return
        (plain lines, the box's (first, last), rows, anchor)."""
        height = height or self.H
        out = self.harness(f'''
            base, bt = m.render_base({height})
            rows = {{}}
            for k, (w, v) in sorted(bt.items()):
                rows.setdefault(w, k)
                if w in ("session", "session-dots"):
                    rows.setdefault(v[0] if w == "session-dots" else v, k)
            {opener}
            lines, _t = m.overlay(base, bt)
            OUT["lines"] = [m.ANSI_RE.sub("", l).rstrip() for l in lines]
            OUT["rows"] = rows
            OUT["anchor"] = (m.PROMPT if m.PROMPT is not None else m.MENU).get("anchor")
        ''')
        lines = out["lines"]
        self.assertEqual(len(lines), height)
        return lines, box_span(lines), out["rows"], out["anchor"]

    def test_top_row_starts_below_it(self):
        # the store row's dots, clicked: Switch store, from the row below
        lines, (first, last), rows, anchor = self.draw('''
            m.ANCHOR = rows["store-dots"]
            name, x0 = bt[rows["store-dots"]][1]
            m.store_row_dispatch(0, x0, (name, x0))
        ''')
        n = rows["store-dots"]
        self.assertEqual(anchor, n)
        self.assertEqual(first, n + 1)
        self.assertEqual(lines[n].strip(), "fx-legacy ⋯", "the clicked row stays in view")
        self.assertIn("Switch store", lines[first + 1])

    def test_middle_row_starts_below_it(self):
        # a right-click on a project row: the project menu, from the row below
        lines, (first, last), rows, anchor = self.draw('''
            m.ANCHOR = rows["beta"]
            m.project_menu("beta")
        ''')
        n = rows["beta"]
        self.assertEqual(anchor, n)
        self.assertEqual(first, n + 1)
        self.assertLess(last, self.H)
        self.assertIn("beta", lines[first + 1])

    def test_a_middle_anchor_that_does_not_fit_ends_above_it(self):
        lines, (first, last), _rows, _a = self.draw('''
            m.ANCHOR = 30
            m.project_menu("alpha")
        ''')
        self.assertEqual(last, 29, "ends on the row above the anchor")
        self.assertGreaterEqual(first, 0)

    def test_bottom_row_ends_above_it(self):
        # the projects strip's menu (`new-or-menu`), pushed low by a long
        # project list, so the box cannot fit below it: it ends on the row above
        for i in range(20):
            self.assertEqual(self.pt.tmux("new-session", "-d", "-s", f"p{i:02}").returncode, 0)
        h = self.H
        lines, (first, last), rows, anchor = self.draw('''
            m.ANCHOR = rows["new-or-menu"]
            m.project_menu(m.current_session() or "alpha")
        ''')
        n = rows["new-or-menu"]
        self.assertEqual(anchor, n)
        self.assertGreater(n + 1 + (last - first + 1), h, "precondition: no room below\n" + "\n".join(lines))
        self.assertEqual(last, n - 1)
        self.assertGreaterEqual(first, 0)

    def test_the_last_row_of_the_pane_ends_above_it(self):
        lines, (first, last), _rows, anchor = self.draw(f'''
            m.ANCHOR = {self.H - 1}
            m.project_menu("alpha")
        ''')
        self.assertEqual(last, self.H - 2)
        self.assertGreaterEqual(first, 0)

    def test_agent_menu_is_anchored_too(self):
        # agent_menu builds through build_menu, so it stamps the anchor the same
        # way; a seat record (rec=) needs no live `session list`.
        lines, (first, last), _rows, anchor = self.draw('''
            m.ANCHOR = 7
            m.agent_menu(rec={"name": "cleo", "session_id": "s1", "tmux_pane": ""})
        ''')
        self.assertEqual(anchor, 7)
        self.assertEqual(first, 8)

    def test_a_prompt_from_a_menu_item_keeps_its_anchor(self):
        lines, (first, last), _rows, anchor = self.draw('''
            m.ANCHOR = rows["beta"]
            m.project_menu("beta")
            m.ANCHOR = None                     # the click is over; the item is picked later
            m.menu_pick([l for l, _k, _a in m.MENU["items"]].index("Rename"))
            OUT["prompt"] = m.PROMPT and m.PROMPT["title"]
        ''')
        self.assertEqual(anchor, _rows["beta"])
        self.assertEqual(first, _rows["beta"] + 1)
        self.assertIn("rename", lines[first + 1])

    def test_no_anchor_is_centred(self):
        # a keyboard open: the menu built with no row is centred, as before
        lines, (first, last), _rows, anchor = self.draw('''
            m.project_menu("alpha")
        ''')
        self.assertIsNone(anchor)
        n = last - first + 1
        self.assertEqual(first, (self.H - n) // 2)

    def test_a_keyboard_note_is_centred(self):
        lines, (first, last), _rows, anchor = self.draw('''
            m.KEYS["?"]()
        ''')
        self.assertIsNone(anchor)
        self.assertEqual(first, (self.H - (last - first + 1)) // 2)

    def test_s_anchors_switch_store_at_the_store_row(self):
        lines, (first, last), rows, anchor = self.draw('''
            m.ANCHOR = None                      # a key, not a click
            m.KEYS["s"]()
        ''')
        self.assertEqual(anchor, rows["store-dots"])
        self.assertEqual(first, rows["store-dots"] + 1)
        self.assertIn("Switch store", lines[first + 1])


class ClickInAPane(ViewBase):
    """The mouse loop end to end: the real sidebar in a pane on the private
    server, fed the SGR bytes of a right-click. The box is read back off the
    pane with capture-pane."""

    TAG = "click"
    H = 40

    def setUp(self):
        super().setUp()
        self.place("fx-legacy")
        self.sessions("store", "alpha", "beta")
        launcher = os.path.join(self.home, "run-sidebar")
        keep = {k: v for k, v in self.env.items() if k not in ("TMUX", "TMUX_PANE")}
        with open(launcher, "w") as f:
            f.write("#!/bin/sh\n")
            for k, v in sorted(keep.items()):
                f.write(f"export {k}={shlex.quote(v)}\n")
            f.write(f"exec {shlex.quote(sys.executable)} -B {shlex.quote(SIDEBAR)}\n")
        os.chmod(launcher, 0o755)
        r = self.pt.tmux("new-session", "-d", "-s", "sb", "-x", "40", "-y", str(self.H), launcher)
        self.assertEqual(r.returncode, 0, r.stderr)

    def screen(self):
        r = self.pt.tmux("capture-pane", "-p", "-t", "=sb:")
        return [ANSI.sub("", l).rstrip() for l in r.stdout.splitlines()]

    def wait(self, pred, secs=20):
        end = time.time() + secs
        while time.time() < end:
            lines = self.screen()
            if pred(lines):
                return lines
            time.sleep(0.2)
        self.fail("timed out; the pane shows:\n" + "\n".join(self.screen()))

    def right_click(self, row):
        # SGR mouse: ESC [ < button ; x ; y M, 1-based; button 2 = right
        seq = f"\x1b[<2;3;{row + 1}M"
        r = self.pt.tmux("send-keys", "-t", "=sb:", "-l", seq)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_right_click_a_project_row_opens_below_it(self):
        lines = self.wait(lambda ls: any("beta" in l.split() for l in ls))
        n = next(i for i, l in enumerate(lines) if "beta" in l.split())
        self.right_click(n)
        lines = self.wait(lambda ls: any(TOP_L in l for l in ls))
        first, last = box_span(lines)
        size = last - first + 1
        self.assertNotEqual(n + 1, (self.H - size) // 2, "precondition: anchored differs from centred")
        self.assertEqual(first, n + 1, "\n".join(lines))
        self.assertLess(last, self.H)
        self.assertIn("beta", lines[first + 1])


if __name__ == "__main__":
    unittest.main()
