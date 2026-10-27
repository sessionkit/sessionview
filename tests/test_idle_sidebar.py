"""bin/tmux-sidebar: the {idle_m} cell, an idle seat's minutes left of {ctx}.

Only an idle seat (status `idle`, or `shell`: at its prompt with a
background shell) shows a time: `idle_s` is the time in the
current state, so a seat busy, waiting or blocked for an hour has a large
`idle_s` too and must show nothing. An idle seat shows dim grey minutes;
orange and bold from agent_idle_orange (45), red and bold from agent_idle_red
(60), and blinks from agent_idle_blink only when that is set (it is 0, off,
by default). The cell is always the same width, so on a 34-column sidebar
the context % stays right-aligned, row under row.

Pure tests drive fmt_idle_cell() / agent_fields() / lay() in a subprocess,
as tests/test_pinned_agents.py does: the sidebar is never imported into
this process, and it reads the template's defaults from a scratch HOME.
Render draws `tmux-sidebar --once` at 34 columns on a private
`tmux -L sv-test-...` socket, with a `session` shim answering the agents.
"""
import json
import os
import re
import subprocess
import sys
import textwrap
import unittest

from tests import support
from tests.test_pinned_agents import HARNESS

SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
BOLD, BLINK = "\x1b[1m", "\x1b[5m"


def pure(env, body):
    """Run BODY against the loaded sidebar module `m`; it fills OUT."""
    r = subprocess.run([sys.executable, "-B", "-c", HARNESS, SIDEBAR, textwrap.dedent(body)],
                       env=env, capture_output=True, text=True, timeout=60, cwd=support.REPO)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout.splitlines()[-1])


class _Pure(unittest.TestCase):

    def setUp(self):
        self._scratch = support.scratch_env()
        self.env, _ = self._scratch.__enter__()

    def tearDown(self):
        self._scratch.__exit__(None, None, None)

    def cells(self, seats, **cfg):
        """{"cells": [the raw {idle_m} of each seat], plus the palette} with
        CFG overridden by **cfg for this run only."""
        return pure(self.env, f'''
            m.CFG.update(json.loads({json.dumps(json.dumps(cfg))}))
            seats = json.loads({json.dumps(json.dumps(seats))})
            OUT["cells"] = [m.agent_fields(a)["idle_m"] for a in seats]
            OUT["dim"], OUT["orange"], OUT["red"] = m.C_DIM, m.C_IDLE_ORANGE, m.C_IDLE_RED
            OUT["width"] = m.IDLE_W
        ''')

    def one(self, minutes, status="idle", **cfg):
        got = self.cells([{"status": status, "idle_s": minutes * 60}], **cfg)
        return got["cells"][0], got


class StateGate(_Pure):

    def test_busy_waiting_blocked_show_nothing_however_long(self):
        # idle_s is time-in-state: a seat busy for three hours has idle_s 10800
        seats = [{"status": st, "idle_s": 10800} for st in ("busy", "waiting", "blocked")]
        seats.append({"idle_s": 10800})                    # no status at all
        got = self.cells(seats)
        self.assertEqual(got["cells"], [" " * got["width"]] * len(seats))

    def test_an_idle_seat_shows_its_minutes(self):
        cell, _ = self.one(34)
        self.assertEqual(ANSI.sub("", cell), " 34m")

    def test_a_shell_seat_is_idle_too(self):
        # Claude Code writes `shell` for a seat at its prompt whenever a
        # background shell lives (a listener left running is one), so most
        # idle seats say `shell`; the session tools' state for it is `idle`.
        cell, got = self.one(34, status="shell")
        self.assertEqual(ANSI.sub("", cell), " 34m")
        cell, got = self.one(61, status="shell")
        self.assertTrue(cell.startswith(got["red"] + BOLD), repr(cell))

    def test_idle_under_a_minute_is_0m(self):
        got = self.cells([{"status": "idle", "idle_s": 59}, {"status": "idle", "idle_s": 0},
                          {"status": "idle"}, {"status": "idle", "idle_s": None}])
        self.assertEqual([ANSI.sub("", c) for c in got["cells"]], ["  0m"] * 4)

    def test_the_cell_is_always_the_same_width(self):
        seats = [{"status": "idle", "idle_s": s} for s in (0, 60, 600, 5940, 59940, 59999 * 60)]
        seats.append({"status": "busy", "idle_s": 99999})
        got = self.cells(seats)
        widths = {len(ANSI.sub("", c)) for c in got["cells"]}
        self.assertEqual(widths, {got["width"]})
        # past 999 minutes it says hours, still in the cell
        self.assertEqual(ANSI.sub("", got["cells"][4]), "999m")
        self.assertEqual(ANSI.sub("", got["cells"][5]), "999h")


class Thresholds(_Pure):

    def test_44_is_dim_grey_and_not_bold(self):
        cell, got = self.one(44)
        self.assertTrue(cell.startswith(got["dim"]), repr(cell))
        self.assertNotIn(BOLD, cell)
        self.assertNotIn(got["orange"], cell)

    def test_45_is_orange_and_bold(self):
        cell, got = self.one(45)
        self.assertTrue(cell.startswith(got["orange"] + BOLD), repr(cell))
        self.assertNotIn(got["red"], cell)

    def test_59_is_still_orange(self):
        cell, got = self.one(59)
        self.assertTrue(cell.startswith(got["orange"] + BOLD), repr(cell))

    def test_60_is_red_and_bold(self):
        cell, got = self.one(60)
        self.assertTrue(cell.startswith(got["red"] + BOLD), repr(cell))
        self.assertNotIn(got["orange"], cell)

    def test_bold_is_turned_off_after_the_cell(self):
        # the {ctx} after it must not inherit bold or blink
        for mins in (45, 60):
            cell, _ = self.one(mins, agent_idle_blink=55)
            text = ANSI.sub("", cell)
            with self.subTest(mins=mins):
                self.assertTrue(cell.split(text, 1)[1].startswith("\x1b[22;25m"), repr(cell))

    def test_the_thresholds_are_settings(self):
        cell, got = self.one(20, agent_idle_orange=10, agent_idle_red=30)
        self.assertTrue(cell.startswith(got["orange"]), repr(cell))
        cell, got = self.one(30, agent_idle_orange=10, agent_idle_red=30)
        self.assertTrue(cell.startswith(got["red"]), repr(cell))

    def test_zero_turns_a_colour_off(self):
        cell, got = self.one(500, agent_idle_orange=0, agent_idle_red=0)
        self.assertTrue(cell.startswith(got["dim"]), repr(cell))
        cell, got = self.one(500, agent_idle_red=0)
        self.assertTrue(cell.startswith(got["orange"]), repr(cell))

    def test_a_bad_value_is_the_default_not_a_crash(self):
        cell, got = self.one(45, agent_idle_orange="soon", agent_idle_red=[1])
        self.assertTrue(cell.startswith(got["orange"]), repr(cell))
        cell, got = self.one(60, agent_idle_orange="soon", agent_idle_red="60")
        self.assertTrue(cell.startswith(got["red"]), repr(cell))


class Blink(_Pure):

    def test_off_by_default(self):
        for mins in (54, 55, 59, 60, 300):
            cell, _ = self.one(mins)
            with self.subTest(mins=mins):
                self.assertNotIn(BLINK, cell)

    def test_on_from_agent_idle_blink_when_set(self):
        for mins, blinks in ((44, False), (54, False), (55, True), (59, True), (60, True), (300, True)):
            cell, _ = self.one(mins, agent_idle_blink=55)
            with self.subTest(mins=mins):
                self.assertEqual(BLINK in cell, blinks)

    def test_set_below_orange_the_grey_minutes_blink(self):
        # "blinking from agent_idle_blink": its own threshold, even while grey.
        for kw in ({"agent_idle_blink": 30},
                   {"agent_idle_blink": 30, "agent_idle_orange": 0, "agent_idle_red": 0}):
            for mins, blinks in ((29, False), (30, True), (44, True)):
                cell, p = self.one(mins, **kw)
                with self.subTest(mins=mins, **kw):
                    self.assertEqual(BLINK in cell, blinks)
                    self.assertTrue(cell.startswith(p["dim"]))
                    self.assertNotIn(BOLD, cell)
                    if blinks:      # the blink is turned off after the cell
                        self.assertIn("\x1b[22;25m", cell)

    def test_null_and_false_are_off_too(self):
        for off in (None, False, 0, -5):
            cell, _ = self.one(59, agent_idle_blink=off)
            with self.subTest(blink=off):
                self.assertNotIn(BLINK, cell)

    def test_never_on_a_seat_that_is_not_idle(self):
        cell, _ = self.one(90, status="busy", agent_idle_blink=55)
        self.assertEqual(cell, "    ")


class Settings(unittest.TestCase):

    def test_the_template_ships_the_keys_and_the_default_row_has_the_cell(self):
        with open(os.path.join(support.CONFIG, "config.json"), encoding="utf-8") as f:
            tpl = json.load(f)
        self.assertEqual(tpl["agent_idle_orange"], 45)
        self.assertEqual(tpl["agent_idle_red"], 60)
        self.assertEqual(tpl["agent_idle_blink"], 0)            # blink off by default
        first = tpl["agent_format"]
        self.assertIn("{idle_m} {ctx}", first.split("\t", 1)[1])  # just left of the context


#: Seats at 34 columns: short names, so every row has room for the right side.
SEATS = [
    {"agent": "amy", "status": "busy",    "idle_s": 7200, "context_model": "claude-opus-4-1",
     "context_pct": 41, "context_used": 82000},
    {"agent": "bob", "status": "idle",    "idle_s": 34 * 60, "context_model": "claude-opus-4-1",
     "context_pct": 7, "context_used": 14000},
    {"agent": "cy",  "status": "idle",    "idle_s": 61 * 60, "context_model": "claude-sonnet-4-5",
     "context_pct": 100, "context_used": 200000},
    {"agent": "di",  "status": "blocked", "idle_s": 5000},
    {"agent": "ed",  "status": "idle",    "idle_s": 50 * 60, "context_model": "claude-opus-4-1",
     "context_pct": 63, "context_used": 126000},
    {"agent": "fay", "status": "shell",   "idle_s": 46 * 60, "context_model": "claude-opus-4-1",
     "context_pct": 9, "context_used": 18000},
]


class Alignment(_Pure):
    """The default agent_format at 34 columns: every row is 34 wide, the
    context % ends in the same column, and the minutes sit left of it."""

    def rows(self, **cfg):
        return pure(self.env, f'''
            m.CFG.update(json.loads({json.dumps(json.dumps(cfg))}))
            seats = json.loads({json.dumps(json.dumps(SEATS))})
            w = max(len(m.short_model(a.get("context_model"))) for a in seats)
            OUT["width"] = m.WIDTH
            OUT["rows"] = [m.lay(m.CFG["agent_format"].format_map(m.agent_fields(a, model_w=w)), m.WIDTH)
                           for a in seats]
        ''')

    def test_rows_line_up_at_34(self):
        got = self.rows()
        self.assertEqual(got["width"], 34)
        plain = [ANSI.sub("", r) for r in got["rows"]]
        for r in plain:
            with self.subTest(row=r):
                self.assertEqual(len(r), 34)
                self.assertEqual(r[-1], " ")                 # the format's trailing space
        # the context is the last word, right-aligned in the same 4 columns
        self.assertEqual([r[-5:-1] for r in plain], [" 41%", "  7%", "100%", "   -", " 63%", "  9%"])
        # the idle cell is the 4 columns before it (one space between)
        self.assertEqual([r[-10:-6] for r in plain], ["    ", " 34m", " 61m", "    ", " 50m", " 46m"])
        self.assertEqual({r[-6] for r in plain}, {" "})

    def test_rows_line_up_with_blink_on(self):
        # blink adds escapes, never columns
        got = self.rows(agent_idle_blink=1)
        self.assertTrue(any(BLINK in r for r in got["rows"]))
        self.assertEqual({len(ANSI.sub("", r)) for r in got["rows"]}, {34})

    def test_a_long_label_gives_way_and_ctx_stays_right_aligned(self):
        # A 30-character label at 34 columns: the agent row is laid with
        # keep_right, so the label is cut with an ellipsis and the model,
        # the minutes and the ctx % stay on the row, in their columns.
        long = dict(SEATS[1], agent="a" * 30)             # bob, idle 34m, 7%
        got = pure(self.env, f'''
            a = json.loads({json.dumps(json.dumps(long))})
            w = len(m.short_model(a.get("context_model")))
            spec = m.CFG["agent_format"].format_map(m.agent_fields(a, model_w=w))
            OUT["row"] = m.lay(spec, m.WIDTH, keep_right=True)
            OUT["short"] = m.lay(m.CFG["agent_format"].format_map(
                m.agent_fields(SEAT_BOB, model_w=w)), m.WIDTH, keep_right=True)
        '''.replace("SEAT_BOB", repr(SEATS[1])))
        row, short = ANSI.sub("", got["row"]), ANSI.sub("", got["short"])
        self.assertEqual(len(row), 34, row)
        self.assertIn("\u2026", row)                         # the label was cut, and says so
        self.assertNotIn("a" * 30, row)
        self.assertEqual(row[-10:], short[-10:])              # " 34m   7% " where bob's is
        self.assertTrue(row.endswith(" 34m   7% "), row)


class Render(unittest.TestCase):
    """`tmux-sidebar --once` at 34 columns on a private socket."""

    def setUp(self):
        if not support.have_tmux():
            self.skipTest(support.TMUX_SKIP)
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self._pt = support.private_tmux("idle")
        self.pt = self._pt.__enter__()
        self.bin = os.path.join(self.home, "bin")
        os.makedirs(self.bin)
        self.env = self.pt.env(env)
        self.env["PATH"] = self.bin + os.pathsep + self.env.get("PATH", "")
        self.env["SESSIONVIEW_STATE"] = os.path.join(self.home, "state")
        self.env["SESSIONVIEW_VIEW_SOCK"] = self.pt.sock
        self.env["SIDEBAR_WIDTH"] = "34"
        self.env["SESSIONVIEW_CONFIG"] = os.path.join(self.home, "sessionview-config.json")
        r = self.pt.tmux("new-session", "-d", "-s", "alpha")
        self.assertEqual(r.returncode, 0, r.stderr)
        pane = self.pt.tmux("list-panes", "-a", "-F", "#{pane_id}").stdout.split()[0]
        with open(os.path.join(self.home, "agents.json"), "w") as f:
            json.dump([dict(a, name=a["agent"], tmux_pane=pane) for a in SEATS], f)
        p = os.path.join(self.bin, "session")
        with open(p, "w") as f:
            f.write(f"#!/bin/sh\ncat {os.path.join(self.home, 'agents.json')!r}\n")
        os.chmod(p, 0o755)

    def tearDown(self):
        self._pt.__exit__(None, None, None)
        self._scratch.__exit__(None, None, None)

    def test_default_rows_keep_ctx_right_aligned(self):
        with open(self.env["SESSIONVIEW_CONFIG"], "w") as f:
            json.dump({}, f)                                  # the template's defaults
        r = subprocess.run([sys.executable, "-B", SIDEBAR, "--once"], env=self.env,
                           capture_output=True, text=True, timeout=60, cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = {}
        for line in r.stdout.splitlines():
            plain = ANSI.sub("", line)
            words = plain.split()
            if len(words) > 1 and words[1] in {a["agent"] for a in SEATS}:
                rows[words[1]] = plain
        self.assertEqual(sorted(rows), sorted(a["agent"] for a in SEATS), r.stdout)
        ends = {name: row.rstrip() for name, row in rows.items()}
        # ctx % (or `-`) ends in the same column on every row
        self.assertEqual(len({len(e) for e in ends.values()}), 1, ends)
        self.assertTrue(ends["bob"].endswith(" 34m   7%"), ends["bob"])
        self.assertTrue(ends["cy"].endswith(" 61m 100%"), ends["cy"])
        self.assertTrue(ends["amy"].endswith("      41%"), ends["amy"])   # busy: no time
        self.assertTrue(ends["di"].endswith("        -"), ends["di"])      # blocked: no time
        self.assertTrue(ends["fay"].endswith(" 46m   9%"), ends["fay"])   # shell: idle at its prompt

    def test_a_long_named_agent_keeps_its_ctx(self):
        # the call site: the drawn agent row is laid with keep_right
        long = "a" * 30
        with open(os.path.join(self.home, "agents.json")) as f:
            seats = json.load(f)
        seats.append(dict(seats[1], agent=long, name=long))       # bob's numbers
        with open(os.path.join(self.home, "agents.json"), "w") as f:
            json.dump(seats, f)
        with open(self.env["SESSIONVIEW_CONFIG"], "w") as f:
            json.dump({}, f)
        r = subprocess.run([sys.executable, "-B", SIDEBAR, "--once"], env=self.env,
                           capture_output=True, text=True, timeout=60, cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        plain = [ANSI.sub("", line) for line in r.stdout.splitlines()]
        cut = [p for p in plain if "aaaa" in p]
        bob = [p for p in plain if " bob " in p]
        self.assertEqual(len(cut), 1, r.stdout)
        self.assertEqual(len(bob), 1, r.stdout)
        self.assertIn("\u2026", cut[0])
        self.assertTrue(cut[0].rstrip().endswith(" 34m   7%"), cut[0])
        self.assertEqual(len(cut[0].rstrip()), len(bob[0].rstrip()), (cut[0], bob[0]))


if __name__ == "__main__":
    unittest.main()
