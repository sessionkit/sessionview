"""bin/tmux-sidebar: `pinned_agents` orders the LIVE agents list (SV-108).

ONE list: pinned means pinned everywhere.
A running agent whose name is pinned sorts first, in pin order, whatever its
project, status or idle; the rest keep CFG["sort"]. Grouped, the pinned rows
sit above every group.

PureSort drives order_agents() (the pure sort SV-128 builds on) in a
subprocess, as tests/test_store_view.py does: the sidebar is never imported
into this process. Render draws `tmux-sidebar --once` on a private
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

SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")
ANSI = re.compile(r"\x1b\[[0-9;]*m")

HARNESS = textwrap.dedent('''
    import importlib.machinery, importlib.util, json, sys
    loader = importlib.machinery.SourceFileLoader("sidebar", sys.argv[1])
    spec = importlib.util.spec_from_loader("sidebar", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    OUT = {}
    exec(sys.argv[2])
    print(json.dumps(OUT))
''')

#: Live rows as `session list --json` gives them; `proj` stands in for the group.
ROWS = [
    {"agent": "zed",   "status": "idle",    "idle_s": 5,   "proj": "beta"},
    {"agent": "pat",   "status": "busy",    "idle_s": 0,   "proj": "alpha"},
    {"agent": "amy",   "status": "blocked", "idle_s": 900, "proj": "beta"},
    {"agent": "cleo",  "status": "idle",    "idle_s": 600, "proj": "beta"},
    {"agent": "bob",   "status": "busy",    "idle_s": 30,  "proj": "alpha"},
    {"agent": "shell", "status": "shell",   "idle_s": 1,   "proj": "alpha"},
]


class PureSort(unittest.TestCase):

    def setUp(self):
        self._scratch = support.scratch_env()
        self.env, _ = self._scratch.__enter__()

    def tearDown(self):
        self._scratch.__exit__(None, None, None)

    def order(self, pinned, rows=ROWS, keys=("rank", "idle_s"), grouped=False,
              group_order=None):
        """The agent names order_agents() puts ROWS in; also checks ROWS is
        left untouched (the sort is pure)."""
        body = f'''
            rows = json.loads({json.dumps(json.dumps(rows))})
            before = json.dumps(rows)
            out = m.order_agents(rows, {pinned!r}, {list(keys)!r},
                                 (lambda a: a["proj"]) if {grouped!r} else None,
                                 {group_order!r})
            OUT["names"] = [a["agent"] for a in out]
            OUT["pure"] = json.dumps(rows) == before
        '''
        r = subprocess.run([sys.executable, "-B", "-c", HARNESS, SIDEBAR, textwrap.dedent(body)],
                           env=self.env, capture_output=True, text=True, timeout=60,
                           cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout.splitlines()[-1])
        self.assertTrue(got["pure"], "order_agents changed its input")
        return got["names"]

    # -- flat --

    def test_pinned_lead_in_pin_order_whatever_their_status(self):
        # cleo idle 600s would sort near the bottom; pat busy near the top.
        self.assertEqual(self.order(["cleo", "pat"]),
                         ["cleo", "pat", "amy", "bob", "zed", "shell"])

    def test_pin_order_is_the_list_order_not_the_status_order(self):
        self.assertEqual(self.order(["pat", "cleo"])[:2], ["pat", "cleo"])

    def test_pip_idle_or_busy_still_second(self):
        for st, idle in (("busy", 0), ("idle", 9999), ("blocked", 3), ("shell", 1)):
            rows = [dict(r, status=st, idle_s=idle) if r["agent"] == "pat" else r for r in ROWS]
            with self.subTest(pat=st):
                self.assertEqual(self.order(["cleo", "pat"], rows=rows)[:2], ["cleo", "pat"])

    def test_the_rest_keep_the_configured_sort(self):
        # rank (blocked, busy, idle, shell), then idle_s
        self.assertEqual(self.order(["cleo", "pat"])[2:], ["amy", "bob", "zed", "shell"])
        # and another `sort` is honoured, not hard-wired: by name
        self.assertEqual(self.order(["cleo"], keys=("agent",)),
                         ["cleo", "amy", "bob", "pat", "shell", "zed"])

    def test_empty_pins_leave_todays_order(self):
        today = [a["agent"] for a in sorted(ROWS, key=lambda a: (
            {"blocked": 0, "waiting": 0, "busy": 1, "idle": 2, "shell": 3}[a["status"]], a["idle_s"]))]
        self.assertEqual(self.order([]), today)
        self.assertEqual(self.order(None), today)

    def test_a_pin_with_no_live_row_is_harmless(self):
        self.assertEqual(self.order(["ghost", "cleo"]),
                         ["cleo", "amy", "pat", "bob", "zed", "shell"])

    def test_a_name_pinned_twice_keeps_its_first_place(self):
        self.assertEqual(self.order(["pat", "cleo", "pat"])[:2], ["pat", "cleo"])

    def test_two_rows_of_one_pinned_agent_stay_together_by_sort(self):
        rows = ROWS + [{"agent": "cleo", "status": "busy", "idle_s": 1, "proj": "alpha"}]
        out = self.order(["cleo"], rows=rows)
        self.assertEqual(out[:2], ["cleo", "cleo"])

    # -- grouped --

    def test_grouped_pins_sit_above_every_group_in_pin_order(self):
        # cleo's own group is beta, pat's alpha; both come before alpha's first row
        out = self.order(["cleo", "pat"], grouped=True, group_order={"alpha": 0, "beta": 1})
        self.assertEqual(out, ["cleo", "pat", "bob", "shell", "amy", "zed"])

    def test_grouped_pins_lead_even_when_their_group_is_last(self):
        out = self.order(["zed"], grouped=True, group_order={"alpha": 0, "beta": 1})
        self.assertEqual(out, ["zed", "pat", "bob", "shell", "amy", "cleo"])

    def test_grouped_empty_pins_leave_todays_group_order(self):
        out = self.order([], grouped=True, group_order={"alpha": 0, "beta": 1})
        self.assertEqual(out, ["pat", "bob", "shell", "amy", "zed", "cleo"])

    def test_grouped_unknown_group_goes_last(self):
        rows = ROWS + [{"agent": "kim", "status": "blocked", "idle_s": 0, "proj": "zzz"}]
        out = self.order(["cleo"], rows=rows, grouped=True, group_order={"alpha": 0, "beta": 1})
        self.assertEqual(out[0], "cleo")
        self.assertEqual(out[-1], "kim")


class Render(unittest.TestCase):
    """`tmux-sidebar --once` on a private socket: the drawn agent rows."""

    def setUp(self):
        if not support.have_tmux():
            self.skipTest(support.TMUX_SKIP)
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self._pt = support.private_tmux("pin")
        self.pt = self._pt.__enter__()
        self.bin = os.path.join(self.home, "bin")
        os.makedirs(self.bin)
        self.env = self.pt.env(env)
        self.env["PATH"] = self.bin + os.pathsep + self.env.get("PATH", "")
        self.env["SESSIONVIEW_STATE"] = os.path.join(self.home, "state")
        self.env["SESSIONVIEW_VIEW_SOCK"] = self.pt.sock
        self.env["SIDEBAR_WIDTH"] = "40"
        self.env["SESSIONVIEW_CONFIG"] = os.path.join(self.home, "sessionview-config.json")
        for n in ("alpha", "beta"):
            r = self.pt.tmux("new-session", "-d", "-s", n)
            self.assertEqual(r.returncode, 0, r.stderr)
        panes = dict(line.split() for line in self.pt.tmux(
            "list-panes", "-a", "-F", "#{session_name} #{pane_id}").stdout.splitlines())
        rows = [dict(r, tmux_pane=panes[r.pop("proj")], name=r["agent"])
                for r in (dict(x) for x in ROWS if x["agent"] != "shell")]
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
        with open(self.env["SESSIONVIEW_CONFIG"], "w") as f:
            json.dump(cfg, f)
        r = subprocess.run([sys.executable, "-B", SIDEBAR, "--once"], env=self.env,
                           capture_output=True, text=True, timeout=60, cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        return [ANSI.sub("", line).rstrip() for line in r.stdout.splitlines()]

    def agent_block(self, lines):
        """The rows under the agents heading, up to the bottom strip: each
        line stripped of glyphs to its first word (an agent name or a group)."""
        # the agents heading; not a bare "grouped", which a session row's
        # branch can carry too (feat/SV-128-grouped-name-prefix did)
        i = next(k for k, line in enumerate(lines) if "all \u00b7 grouped" in line)
        out = []
        for line in lines[i + 1:]:
            words = [w for w in line.split() if w.isalnum() and w.isascii()]
            if words:
                out.append(words[0])
        return [w for w in out if w in {"alpha", "beta", "amy", "bob", "cleo", "pat", "zed"}]

    def test_flat(self):
        got = self.agent_block(self.once(pinned_agents=["cleo", "pat"], agent_format=" {glyph} {agent}"))
        self.assertEqual(got, ["cleo", "pat", "amy", "bob", "zed"])

    def test_flat_unpinned_is_todays_order(self):
        got = self.agent_block(self.once(pinned_agents=[], agent_format=" {glyph} {agent}"))
        self.assertEqual(got, ["amy", "pat", "bob", "zed", "cleo"])

    def test_grouped_pins_above_the_first_heading_with_no_heading_of_their_own(self):
        got = self.agent_block(self.once(pinned_agents=["cleo", "pat"], group_by="session",
                                         agent_format=" {glyph} {agent}"))
        self.assertEqual(got, ["cleo", "pat", "alpha", "bob", "beta", "amy", "zed"])


if __name__ == "__main__":
    unittest.main()
