"""bin/tmux-sidebar: seat_word(), the ONE test of a seat's condition.

Claude Code writes status `shell`, not `idle`, for a seat at its prompt
whenever a background shell lives (a listener left running is one), so most
idle seats say `shell`. The session tools' `state` says `idle` for them. The
glyph, the sort, the rollups (project rows and tab-bar glyphs) and the idle
minutes all ask seat_word(), so they cannot disagree: an idle seat draws the
green dot and ranks as idle whatever its raw status.

`waiting` and `blocked` come from `status` first: `state` reads a seat
waiting on a prompt as idle, and drawing that green would hide it. A feed
with no `state` (an older session tools) has its `status` mapped.

Pure tests drive the loaded sidebar module in a subprocess (the `pure()`
harness of tests/test_idle_sidebar.py), in a scratch HOME.
"""
import json
import os
import re
import unittest

from tests import support
from tests.test_idle_sidebar import pure

ANSI = re.compile(r"\x1b\[[0-9;]*m")

#: (status, state, word); None is an absent key.
TRUTH = [
    ("shell", "idle", "idle"),
    ("idle", "idle", "idle"),
    ("busy", "busy", "busy"),
    ("busy", "idle with children", "idle"),
    ("waiting", "idle", "waiting"),
    ("blocked", "idle", "blocked"),
    ("blocked", None, "blocked"),
    ("shell", None, "idle"),
    ("idle", None, "idle"),
    ("busy", None, "busy"),
    ("waiting", None, "waiting"),
    ("xyz", None, "xyz"),
    ("shell", "newword", "newword"),
    (None, None, None),
    ("shell", "", "idle"),           # an empty state is absent, not a word
]


def row(status, state, **extra):
    a = dict(extra)
    if status is not None:
        a["status"] = status
    if state is not None:
        a["state"] = state
    return a


class _Pure(unittest.TestCase):

    def setUp(self):
        self._scratch = support.scratch_env()
        self.env, _ = self._scratch.__enter__()

    def tearDown(self):
        self._scratch.__exit__(None, None, None)

    def run_body(self, seats, body):
        return pure(self.env, f'''
            seats = json.loads({json.dumps(json.dumps(seats))})
            OUT["glyph"] = m.GLYPH
            OUT["rank"] = m.RANK
            {body}
        ''')


class SeatWord(_Pure):

    def test_the_truth_table(self):
        seats = [row(st, sa) for st, sa, _ in TRUTH]
        got = self.run_body(seats, 'OUT["words"] = [m.seat_word(a) for a in seats]')
        for (st, sa, want), word in zip(TRUTH, got["words"]):
            with self.subTest(status=st, state=sa):
                self.assertEqual(word, want)


class Glyph(_Pure):

    def glyphs(self, seats):
        got = self.run_body(seats, 'OUT["g"] = [m.agent_fields(a)["glyph"] for a in seats]')
        return got["g"], got["glyph"]

    def test_an_idle_seat_saying_shell_draws_the_green_dot(self):
        # the bug: it drew the dim grey ring, as if it were not an agent
        g, glyph = self.glyphs([row("shell", "idle"), row("shell", None)])
        self.assertEqual(g, [glyph["idle"], glyph["idle"]])
        self.assertNotIn("○", ANSI.sub("", g[0]))

    def test_waiting_is_not_idle(self):
        # state says idle for a seat waiting on a prompt: it stays the red square
        g, glyph = self.glyphs([row("waiting", "idle"), row("blocked", "idle")])
        self.assertEqual(g, [glyph["waiting"], glyph["blocked"]])
        self.assertEqual(ANSI.sub("", g[0]), "■")

    def test_idle_with_children_is_idle(self):
        g, glyph = self.glyphs([row("busy", "idle with children")])
        self.assertEqual(g, [glyph["idle"]])

    def test_an_older_feed_maps_its_status(self):
        g, glyph = self.glyphs([row(st, None) for st in ("shell", "busy", "waiting")])
        self.assertEqual(g, [glyph["idle"], glyph["busy"], glyph["waiting"]])

    def test_an_unknown_word_is_a_question_mark(self):
        g, _ = self.glyphs([row("xyz", None), row(None, None), row("shell", "newword")])
        self.assertEqual(g, ["?", "?", "?"])

    def test_no_table_keeps_a_shell_entry(self):
        got = self.run_body([], 'OUT["tabs"] = [sorted(m.TAB_CH), sorted(m.TAB_FG)]')
        self.assertNotIn("shell", got["glyph"])
        self.assertNotIn("shell", got["rank"])
        for keys in got["tabs"]:
            self.assertNotIn("shell", keys)


class Sort(_Pure):

    def ranks(self, seats):
        got = self.run_body(seats, 'OUT["k"] = [m.sort_key(a, ("rank",))[0] for a in seats]')
        return got["k"]

    def test_a_shell_seat_ties_with_an_idle_seat_after_busy(self):
        k = self.ranks([row("shell", "idle"), row("idle", "idle"), row("busy", "busy"),
                        row("shell", None)])
        self.assertEqual(k, [2, 2, 1, 2])

    def test_waiting_ranks_first_even_when_state_says_idle(self):
        self.assertEqual(self.ranks([row("waiting", "idle"), row("blocked", None)]), [0, 0])

    def test_idle_with_children_ranks_as_idle(self):
        self.assertEqual(self.ranks([row("busy", "idle with children")]), [2])

    def test_an_unknown_word_sorts_last(self):
        self.assertEqual(self.ranks([row("xyz", None), row(None, None)]), [9, 9])

    def test_shell_seats_sort_among_the_idle_by_idle_time(self):
        seats = [row("shell", "idle", agent="old", idle_s=900),
                 row("idle", "idle", agent="new", idle_s=5),
                 row("busy", "busy", agent="work", idle_s=0),
                 row("shell", "idle", agent="mid", idle_s=60)]
        got = self.run_body(seats, '''
            OUT["names"] = [a["agent"] for a in sorted(seats, key=lambda a: m.sort_key(a, ("rank", "idle_s")))]
        ''')
        self.assertEqual(got["names"], ["work", "new", "mid", "old"])


class IdleCell(_Pure):

    def cells(self, seats):
        got = self.run_body(seats, '''
            OUT["c"] = [m.fmt_idle_cell(a) for a in seats]
            OUT["w"] = m.IDLE_W
        ''')
        return [ANSI.sub("", c) for c in got["c"]], got["w"]

    def test_the_cell_asks_the_same_word(self):
        seats = [row("shell", "idle", idle_s=34 * 60),
                 row("busy", "idle with children", idle_s=7 * 60),
                 row("waiting", "idle", idle_s=34 * 60),
                 row("busy", "busy", idle_s=34 * 60),
                 row("shell", None, idle_s=34 * 60)]
        c, w = self.cells(seats)
        self.assertEqual(c, [" 34m", "  7m", " " * w, " " * w, " 34m"])


class Rollup(_Pure):

    def test_a_window_with_one_shell_seat_writes_the_green_tab_glyph(self):
        got = pure(self.env, '''
            calls = []
            m.subprocess.run = lambda argv, *k, **kw: calls.append(argv)
            m.sh = lambda *k, **kw: ""
            m.WRITE_TABS = True
            m.CFG["tab_glyphs"] = True
            seat = {"status": "shell", "state": "idle"}
            m.tab_glyphs({"proj:1": [m.seat_word(seat)]}, [("", "proj", "", "", "", "", "1")])
            OUT["calls"] = [list(c) for c in calls]
            OUT["ch"], OUT["fg"] = m.TAB_CH["idle"], m.TAB_FG["idle"]
        ''')
        values = [c[-1] for c in got["calls"]]
        self.assertIn(got["ch"], values)
        self.assertIn(got["fg"], values)
        self.assertNotIn("○", values)

    def test_a_word_with_no_tab_glyph_writes_none(self):
        # a newer session tools' state word the sidebar does not know
        got = pure(self.env, '''
            calls = []
            m.subprocess.run = lambda argv, *k, **kw: calls.append(argv)
            m.sh = lambda *k, **kw: ""
            m.WRITE_TABS = True
            m.CFG["tab_glyphs"] = True
            m.tab_glyphs({"proj:1": ["newword"]}, [("", "proj", "", "", "", "", "1")])
            OUT["calls"] = [list(c) for c in calls]
        ''')
        self.assertEqual(got["calls"], [])

    def test_waiting_beats_idle_in_a_project_row(self):
        seats = [row("waiting", "idle"), row("shell", "idle"), row("busy", "busy")]
        got = self.run_body(seats, 'OUT["r"] = m.rollup([m.seat_word(a) for a in seats])')
        self.assertEqual(got["r"], "waiting")

    def test_idle_seats_saying_shell_roll_up_to_idle(self):
        seats = [row("shell", "idle"), row("shell", "idle")]
        got = self.run_body(seats, 'OUT["r"] = m.rollup([m.seat_word(a) for a in seats])')
        self.assertEqual(got["r"], "idle")


class Render(unittest.TestCase):
    """render_base() itself, on a private tmux: the project rows it draws and
    the tab glyphs it writes. The pure tests above call seat_word() by hand;
    these hold the call sites in render_base that feed the rollups (local
    sessions, local windows, a remote host's sessions)."""

    #: tmux session -> (status, state) of the one seat in it.
    SEATS = {"calm": ("shell", "idle"), "loud": ("waiting", "idle")}
    #: a remote host's sessions, the same way.
    REMOTE = {"rcalm": ("shell", "idle"), "rloud": ("waiting", "idle")}

    def setUp(self):
        if not support.have_tmux():
            self.skipTest(support.TMUX_SKIP)
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self._pt = support.private_tmux("seatword")
        self.pt = self._pt.__enter__()
        self.env = self.pt.env(env)
        bin_ = os.path.join(self.home, "bin")
        os.makedirs(bin_)
        self.env["PATH"] = bin_ + os.pathsep + self.env.get("PATH", "")
        self.env["SESSIONVIEW_STATE"] = os.path.join(self.home, "state")
        self.env["SESSIONVIEW_VIEW_SOCK"] = self.pt.sock
        self.env["SIDEBAR_WIDTH"] = "40"
        for n in self.SEATS:
            r = self.pt.tmux("new-session", "-d", "-s", n, "-c", self.home)
            self.assertEqual(r.returncode, 0, r.stderr)
        panes = dict(line.split() for line in self.pt.tmux(
            "list-panes", "-a", "-F", "#{session_name} #{pane_id}").stdout.splitlines())
        rows = [row(st, sa, agent=n, name=n, idle_s=60, tmux_pane=panes[n])
                for n, (st, sa) in self.SEATS.items()]
        agents = os.path.join(self.home, "agents.json")
        with open(agents, "w") as f:
            json.dump(rows, f)
        shim = os.path.join(bin_, "session")
        with open(shim, "w") as f:
            f.write(f"#!/bin/sh\ncat {agents!r}\n")
        os.chmod(shim, 0o755)

    def tearDown(self):
        self._pt.__exit__(None, None, None)
        self._scratch.__exit__(None, None, None)

    def render(self):
        names = list(self.REMOTE)
        remote = {
            "agents": [row(*self.REMOTE[n], agent="r" + n, name="r" + n, idle_s=60,
                           tmux_pane=f"%r{i}") for i, n in enumerate(names)],
            "sessions": [[n, "1", "0"] for n in names],
            "p2s": {f"%r{i}": n for i, n in enumerate(names)},
            "p2w": {f"%r{i}": "w" for i, n in enumerate(names)},
            "ok": True, "err": ""}
        return pure(self.env, f"""
            import time
            remote = json.loads({json.dumps(json.dumps(remote))})
            remote["t"] = time.time()
            m.CFG["remotes"] = ["far"]
            m.REMOTE["far"] = remote
            m.WRITE_TABS = True
            m.CFG["tab_glyphs"] = True
            lines, _ = m.render_base(60)
            OUT["lines"] = [m.ANSI_RE.sub("", l).rstrip() for l in lines]
            OUT["idle"], OUT["waiting"] = m.TAB_CH["idle"], m.TAB_CH["waiting"]
            OUT["idle_fg"] = m.TAB_FG["idle"]
        """)

    def project_glyph(self, lines, name):
        """The glyph column of NAME's project row (` G name ...`), from the
        rows above the agents heading only: an agent row can carry the same
        name. A blank glyph is returned as " "."""
        end = next(i for i, l in enumerate(lines) if "all \u00b7 " in l)
        hit = [l[1] for l in lines[:end] if l[3:].split()[:1] == [name]]
        self.assertTrue(hit, f"no project row {name!r} in {lines[:end]!r}")
        return hit[0]

    def tab(self, sess, opt):
        return self.pt.tmux("show-options", "-w", "-v", "-t", f"{sess}:0", opt).stdout.strip()

    def test_project_rows_and_tab_glyphs_ask_the_seat_word(self):
        got = self.render()
        lines = got["lines"]
        # local project rows: a seat saying `shell` rolls up green, not the ring
        self.assertEqual(self.project_glyph(lines, "calm"), got["idle"])
        self.assertEqual(self.project_glyph(lines, "loud"), got["waiting"])
        # a remote host's project rows: the same word
        self.assertEqual(self.project_glyph(lines, "rcalm"), got["idle"])
        self.assertEqual(self.project_glyph(lines, "rloud"), got["waiting"])
        # the tab-bar glyph render_base writes on each window
        self.assertEqual(self.tab("calm", "@sessionview_glyph"), got["idle"])
        self.assertEqual(self.tab("calm", "@sessionview_glyph_fg"), got["idle_fg"])
        self.assertEqual(self.tab("loud", "@sessionview_glyph"), got["waiting"])


if __name__ == "__main__":
    unittest.main()
