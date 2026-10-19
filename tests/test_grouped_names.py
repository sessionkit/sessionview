"""bin/tmux-sidebar: grouped rows drop the `<group>+` the header shows (SV-128).

In grouped mode a seat's name is drawn without the `<group>+` at its start,
and a group's rows are ordered by task id, which keeps a task's seats
together. So under the
`sessionview` header, `sessionview+sv-92.worker` draws `sv-92.worker`, and a
group's rows sort by that short name: no-task seats first (super first), then
task id in natural order (sv-92 before sv-104), foreman before workers.
Ungrouped, pinned, legacy and other projects' names are drawn in full.

Pure tests drive short_name() / name_key() / order_agents() in a subprocess,
as tests/test_pinned_agents.py does: the sidebar is never imported into this
process. Render draws `tmux-sidebar --once` on a private `tmux -L sv-test-...`
socket, with a `session` shim answering the agents. No voice.
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


def pure(env, body):
    """Run BODY against the loaded sidebar module `m`; it fills OUT."""
    r = subprocess.run([sys.executable, "-B", "-c", HARNESS, SIDEBAR, textwrap.dedent(body)],
                       env=env, capture_output=True, text=True, timeout=60, cwd=support.REPO)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout.splitlines()[-1])


#: One project group's seats, as `session list --json` gives them: `agent` is
#: the role, `name` the seat. Listed in an order the status sort scrambles.
SEATS = [
    {"agent": "worker",   "name": "sessionview+sv-104.worker", "status": "busy",    "idle_s": 0},
    {"agent": "foreman",  "name": "sessionview+sv-92.foreman", "status": "idle",    "idle_s": 900},
    {"agent": "engineer", "name": "sessionview+engineer",      "status": "blocked", "idle_s": 3},
    {"agent": "worker",   "name": "sessionview+sv-92.worker",  "status": "busy",    "idle_s": 40},
    {"agent": "foreman",  "name": "sessionview+sv-104.foreman", "status": "shell",  "idle_s": 1},
    {"agent": "super",    "name": "sessionview+super",         "status": "idle",    "idle_s": 5000},
]
SHORT_ORDER = ["super", "engineer", "sv-92.foreman", "sv-92.worker",
               "sv-104.foreman", "sv-104.worker"]


class ShortName(unittest.TestCase):

    def setUp(self):
        self._scratch = support.scratch_env()
        self.env, _ = self._scratch.__enter__()

    def tearDown(self):
        self._scratch.__exit__(None, None, None)

    def short(self, cases):
        got = pure(self.env, f'''
            cases = json.loads({json.dumps(json.dumps(cases))})
            OUT["got"] = [m.short_name(n, m.PIN_GROUP if g == "PIN" else g) for n, g in cases]
        ''')
        return got["got"]

    def test_own_group_prefix_is_dropped(self):
        self.assertEqual(self.short([
            ["sessionview+super", "sessionview"],
            ["sessionview+sv-128.foreman.19166daf", "sessionview"],
        ]), ["super", "sv-128.foreman.19166daf"])

    def test_remote_header_strips_its_session_part(self):
        # Q1: a remote group `host:session` compares against the
        # session part, so `hosta:sessionview` strips `sessionview+`
        self.assertEqual(self.short([
            ["sessionview+super", "hosta:sessionview"],
            ["sessionview+sv-92.worker.aaaaaaaa", "hostb.lan:sessionview"],
        ]), ["super", "sv-92.worker.aaaaaaaa"])

    def test_everything_else_is_unchanged(self):
        cases = [
            ["sessionview+super", None],              # ungrouped
            ["sessionview+super", "PIN"],             # the pinned block
            ["voicemode+super", "sessionview"],       # another project's seat
            ["foreman.SV-92", "sessionview"],         # legacy grammar
            ["foreman.SV-92", "foreman"],             # no `+`: never a prefix
            ["voicemode+super", "hosta:sessionview"],    # remote: session part differs
            ["hosta+super", "hosta:sessionview"],           # remote: the host is never the prefix
            ["sessionview+super", "hosta:"],             # remote with no session part
            ["sessionview", "sessionview"],           # a row named exactly the session
            ["sessionview", "hosta:sessionview"],
            ["sessionview+", "sessionview"],          # nothing after the `+`
            ["Sessionview+super", "sessionview"],     # case counts
            ["sessionviewer+super", "sessionview"],   # prefix of the word only
            ["", "sessionview"],
        ]
        self.assertEqual(self.short(cases), [n for n, _ in cases])

    def test_a_non_string_group_is_unchanged(self):
        # group_by=<field> on an int field (pid, idle_s) gives int groups;
        # they never raise and never strip
        got = pure(self.env, '''
            OUT["got"] = [m.short_name("sessionview+super", g) for g in (4242, 0.5, True)]
            OUT["key"] = m.name_key({"agent": "super", "name": "sessionview+super"}, 4242)
        ''')
        self.assertEqual(got["got"], ["sessionview+super"] * 3)
        self.assertEqual(got["key"], [1])


class GroupedOrder(unittest.TestCase):

    def setUp(self):
        self._scratch = support.scratch_env()
        self.env, _ = self._scratch.__enter__()

    def tearDown(self):
        self._scratch.__exit__(None, None, None)

    def order(self, rows, pinned=(), grouped=True, within=True, keys=("rank", "idle_s")):
        """Names order_agents() puts ROWS in, grouped by `g`, with the
        render_base within-key; also checks ROWS is untouched."""
        got = pure(self.env, f'''
            rows = json.loads({json.dumps(json.dumps(rows))})
            before = json.dumps(rows)
            grp = lambda a: a["g"]
            out = m.order_agents(rows, {list(pinned)!r}, {list(keys)!r},
                                 grp if {grouped!r} else None,
                                 {{"pin": 0, "sessionview": 1, "voicemode": 2}} if {grouped!r} else None,
                                 (lambda a: m.name_key(a, grp(a))) if {within!r} else None)
            OUT["names"] = [a["name"] for a in out]
            OUT["pure"] = json.dumps(rows) == before
        ''')
        self.assertTrue(got["pure"], "order_agents changed its input")
        return got["names"]

    def rows(self, g="sessionview", seats=SEATS):
        return [dict(r, g=g) for r in seats]

    def test_group_sorts_by_short_name_whatever_the_status(self):
        out = self.order(self.rows())
        self.assertEqual(out, ["sessionview+" + s for s in SHORT_ORDER])

    def test_natural_task_order_not_lexical(self):
        seats = [{"agent": "worker", "name": f"sessionview+sv-{n}.worker", "status": "idle", "idle_s": 0}
                 for n in (104, 9, 92, 1000)]
        self.assertEqual(self.order(self.rows(seats=seats)),
                         [f"sessionview+sv-{n}.worker" for n in (9, 92, 104, 1000)])

    def test_session_suffix_and_other_roles(self):
        seats = [
            {"agent": "worker",   "name": "sessionview+sv-92.worker.bbbbbbbb", "status": "busy"},
            {"agent": "reviewer", "name": "sessionview+sv-92.reviewer.cccccccc", "status": "busy"},
            {"agent": "foreman",  "name": "sessionview+sv-92.foreman.aaaaaaaa", "status": "busy"},
            {"agent": "support",  "name": "sessionview+support", "status": "busy"},
            {"agent": "super",    "name": "sessionview+super.dddddddd", "status": "busy"},
        ]
        self.assertEqual(self.order(self.rows(seats=seats)), [
            "sessionview+super.dddddddd", "sessionview+support",
            "sessionview+sv-92.foreman.aaaaaaaa", "sessionview+sv-92.worker.bbbbbbbb",
            "sessionview+sv-92.reviewer.cccccccc"])

    def test_groups_keep_their_order_and_each_sorts_inside(self):
        vm = [{"agent": "worker", "name": "voicemode+vm-3.worker", "status": "busy", "idle_s": 0},
              {"agent": "super", "name": "voicemode+super", "status": "idle", "idle_s": 99}]
        out = self.order(self.rows("voicemode", vm) + self.rows())
        self.assertEqual(out, ["sessionview+" + s for s in SHORT_ORDER]
                         + ["voicemode+super", "voicemode+vm-3.worker"])

    def test_pins_still_lead_in_pin_order(self):
        out = self.order(self.rows(), pinned=["worker", "super"])
        # both worker rows are pinned (pins match `agent`), in CFG sort order,
        # then super; the rest of the group follows by short name
        self.assertEqual(out, ["sessionview+sv-104.worker", "sessionview+sv-92.worker",
                               "sessionview+super", "sessionview+engineer",
                               "sessionview+sv-92.foreman", "sessionview+sv-104.foreman"])

    def test_without_within_order_is_todays(self):
        # the ungrouped path and within=None never see name_key
        for grouped in (True, False):
            with self.subTest(grouped=grouped):
                self.assertEqual(
                    self.order(self.rows(), grouped=grouped, within=False),
                    ["sessionview+engineer", "sessionview+sv-104.worker",
                     "sessionview+sv-92.worker", "sessionview+sv-92.foreman",
                     "sessionview+super", "sessionview+sv-104.foreman"])

    def test_mixed_group_stripped_rows_first_then_todays_order(self):
        # Q2: only rows that were stripped sort by short
        # name; every other row keeps CFG["sort"] (rank, then idle_s) after them
        seats = [
            {"agent": "pat",     "name": "pat",                       "status": "idle",    "idle_s": 5},
            {"agent": "foreman", "name": "foreman.SV-92",             "status": "busy",    "idle_s": 50},
            {"agent": "worker",  "name": "sessionview+sv-104.worker", "status": "busy",    "idle_s": 0},
            {"agent": "super",   "name": "voicemode+super",           "status": "blocked", "idle_s": 1},
            {"agent": "super",   "name": "sessionview+super",         "status": "shell",   "idle_s": 9},
            {"agent": "foreman", "name": "sessionview+sv-92.foreman", "status": "idle",    "idle_s": 3},
            {"agent": "cleo",    "name": "cleo",                      "status": "busy",    "idle_s": 2},
        ]
        self.assertEqual(self.order(self.rows(seats=seats)), [
            "sessionview+super", "sessionview+sv-92.foreman", "sessionview+sv-104.worker",
            "voicemode+super", "cleo", "foreman.SV-92", "pat"])

    def test_remote_group_sorts_by_short_name(self):
        out = self.order(self.rows("hosta:sessionview"))
        self.assertEqual(out, ["sessionview+" + s for s in SHORT_ORDER])

    def test_remote_group_of_another_session_keeps_todays_order(self):
        # nothing strips under `hosta:voicemode`, so the group is CFG["sort"] order
        self.assertEqual(self.order(self.rows("hosta:voicemode")),
                         self.order(self.rows("hosta:voicemode"), within=False))

    def test_a_row_with_no_name_keys_on_its_agent(self):
        # no `name`: name_key falls back to `agent`; unstripped rows keep
        # their CFG["sort"] order (here, input order: one status) after it
        seats = [{"agent": "zed", "status": "busy"}, {"agent": "g+super", "status": "busy"},
                 {"agent": "amy", "status": "busy"}]
        got = pure(self.env, f'''
            rows = json.loads({json.dumps(json.dumps(seats))})
            out = m.order_agents(rows, [], ["rank"], lambda a: "g", {{}},
                                 lambda a: m.name_key(a, "g"))
            OUT["names"] = [a["agent"] for a in out]
        ''')
        self.assertEqual(got["names"], ["g+super", "zed", "amy"])


class Render(unittest.TestCase):
    """`tmux-sidebar --once` on a private socket: the drawn agent rows.

    Two `super` rows (one per session) and two of each task role make every
    `{label}` the seat name (agent_fields falls back to `name` on a clash),
    which is the only way a plus-address reaches the screen."""

    ROWS = [
        dict(r, sess="sessionview") for r in SEATS
    ] + [
        {"agent": "super", "name": "voicemode+super", "status": "busy", "idle_s": 0, "sess": "voicemode"},
        {"agent": "engineer", "name": "voicemode+engineer", "status": "busy", "idle_s": 0,
         "sess": "voicemode"},
    ]
    NAMES = {r["name"] for r in ROWS} | {s for s in SHORT_ORDER} | {"sessionview", "voicemode"}

    def setUp(self):
        if not support.have_tmux():
            self.skipTest(support.TMUX_SKIP)
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self._pt = support.private_tmux("grpname")
        self.pt = self._pt.__enter__()
        self.bin = os.path.join(self.home, "bin")
        os.makedirs(self.bin)
        self.env = self.pt.env(env)
        self.env["PATH"] = self.bin + os.pathsep + self.env.get("PATH", "")
        self.env["SESSIONVIEW_STATE"] = os.path.join(self.home, "state")
        self.env["SESSIONVIEW_VIEW_SOCK"] = self.pt.sock
        self.env["SIDEBAR_WIDTH"] = "60"
        self.env["SESSIONVIEW_CONFIG"] = os.path.join(self.home, "sessionview-config.json")
        for n in ("sessionview", "voicemode"):
            r = self.pt.tmux("new-session", "-d", "-s", n)
            self.assertEqual(r.returncode, 0, r.stderr)
        panes = dict(line.split() for line in self.pt.tmux(
            "list-panes", "-a", "-F", "#{session_name} #{pane_id}").stdout.splitlines())
        rows = [dict({k: v for k, v in r.items() if k != "sess"}, tmux_pane=panes[r["sess"]])
                for r in self.ROWS]
        with open(os.path.join(self.home, "agents.json"), "w") as f:
            json.dump(rows, f)
        p = os.path.join(self.bin, "session")
        with open(p, "w") as f:
            f.write(f"#!/bin/sh\ncat {os.path.join(self.home, 'agents.json')!r}\n")
        os.chmod(p, 0o755)

    def tearDown(self):
        self._pt.__exit__(None, None, None)
        self._scratch.__exit__(None, None, None)

    def once(self, **cfg):
        cfg.setdefault("agent_format", " {glyph} {label}")
        with open(self.env["SESSIONVIEW_CONFIG"], "w") as f:
            json.dump(cfg, f)
        r = subprocess.run([sys.executable, "-B", SIDEBAR, "--once"], env=self.env,
                           capture_output=True, text=True, timeout=60, cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = [ANSI.sub("", line).rstrip() for line in r.stdout.splitlines()]
        # the agents heading; not a bare "grouped": the branch on a session
        # row (feat/SV-128-grouped-name-prefix) carries the word too
        i = next(k for k, line in enumerate(lines) if "all \u00b7 grouped" in line)
        out = []
        for line in lines[i + 1:]:
            words = [w for w in line.split() if w in self.NAMES]
            if words:
                out.append(words[0])
        return out

    def test_grouped_draws_the_short_name_in_short_name_order(self):
        got = self.once(group_by="session")
        self.assertEqual(got, ["sessionview"] + SHORT_ORDER + ["voicemode", "super", "engineer"])

    def test_ungrouped_draws_the_full_name_in_todays_order(self):
        got = self.once()
        self.assertEqual(sorted(got), sorted(r["name"] for r in self.ROWS))
        self.assertNotIn("super", got)
        # today's order: rank (blocked, busy, idle, shell), then idle_s
        self.assertEqual(got[0], "sessionview+engineer")
        self.assertEqual(got[-1], "sessionview+sv-104.foreman")

    def test_selected_row_draws_the_short_name_before_its_dots(self):
        # the selected row rebuilds its label with the `⋯` menu dots after it;
        # that copy is taken after the strip, so the dots follow the short name
        self.env["SIDEBAR_SELECT_AGENT"] = "super"     # both supers selected
        got = self.once(group_by="session")
        self.assertEqual(got, ["sessionview"] + SHORT_ORDER + ["voicemode", "super", "engineer"])
        r = subprocess.run([sys.executable, "-B", SIDEBAR, "--once"], env=self.env,
                           capture_output=True, text=True, timeout=60, cwd=support.REPO)
        lines = [ANSI.sub("", line) for line in r.stdout.splitlines()]
        i = next(k for k, line in enumerate(lines) if "all · grouped" in line)
        dotted = [line.split() for line in lines[i + 1:] if "⋯" in line]   # agent rows only
        self.assertEqual(len(dotted), 2, r.stdout)
        for words in dotted:
            self.assertIn("super", words)
            self.assertNotIn("sessionview+super", words)
            self.assertNotIn("voicemode+super", words)
            self.assertEqual(words[words.index("super") + 1], "⋯")

    def test_grouped_by_an_int_field_draws_full_names(self):
        # group_by=pid drew at dcc3bac; the strip must not make it raise
        path = os.path.join(self.home, "agents.json")
        with open(path) as f:
            rows = json.load(f)
        for i, r in enumerate(rows):
            r["pid"] = 1000 + i % 2
        with open(path, "w") as f:
            json.dump(rows, f)
        got = self.once(group_by="pid")
        self.assertEqual(sorted(got), sorted(r["name"] for r in self.ROWS))

    def test_pinned_row_keeps_its_full_name(self):
        got = self.once(group_by="session", pinned_agents=["super"])
        # the pinned block (headerless) leads with both supers in full
        self.assertEqual(got[:3], ["voicemode+super", "sessionview+super", "sessionview"])
        self.assertEqual(got[3:], ["engineer", "sv-92.foreman", "sv-92.worker",
                                   "sv-104.foreman", "sv-104.worker", "voicemode", "engineer"])


if __name__ == "__main__":
    unittest.main()
