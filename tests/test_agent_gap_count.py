"""bin/tmux-sidebar: `agent_gap` rows are counted when the agent list is laid out.

With `agent_gap` > 0 every shown agent is followed by that many blank rows.
The layout must count them, both in the size of the agents block (which sets
how high the block starts) and in the per-agent cost that decides how many
agents fit. Otherwise the loop believes more agents fit than do, the last
rows are cut at the pane bottom, and no `+N more` is drawn for them.

Render draws `tmux-sidebar --once` on a private `tmux -L sv-test-...`
socket, in a scratch HOME, with a `session` shim answering the agents.
"""
import json
import os
import re
import subprocess
import sys
import unittest

from tests import support

SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
HEADING = "all · grouped"
MORE = re.compile(r"^\s*\+(\d+) more\s*$")
SESSIONS = ("alpha", "bravo", "charlie")


def label(i):
    return f"gapagent{i:02d}"


class AgentGapCount(unittest.TestCase):

    def setUp(self):
        if not support.have_tmux():
            self.skipTest(support.TMUX_SKIP)
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self._pt = support.private_tmux("agentgap")
        self.pt = self._pt.__enter__()
        self.bin = os.path.join(self.home, "bin")
        os.makedirs(self.bin)
        self.env = self.pt.env(env)
        self.env["PATH"] = self.bin + os.pathsep + self.env.get("PATH", "")
        self.env["SESSIONVIEW_STATE"] = os.path.join(self.home, "state")
        self.env["SESSIONVIEW_VIEW_SOCK"] = self.pt.sock
        self.env["SIDEBAR_WIDTH"] = "60"
        self.env["SESSIONVIEW_CONFIG"] = os.path.join(self.home, "sessionview-config.json")
        for n in SESSIONS:
            r = self.pt.tmux("new-session", "-d", "-s", n)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.panes = dict(line.split() for line in self.pt.tmux(
            "list-panes", "-a", "-F", "#{session_name} #{pane_id}").stdout.splitlines())
        p = os.path.join(self.bin, "session")
        with open(p, "w") as f:
            f.write(f"#!/bin/sh\ncat {os.path.join(self.home, 'agents.json')!r}\n")
        os.chmod(p, 0o755)

    def tearDown(self):
        self._pt.__exit__(None, None, None)
        self._scratch.__exit__(None, None, None)

    def agents(self, n):
        rows = [{"agent": label(i), "name": label(i), "status": "idle", "idle_s": i,
                 "tmux_pane": self.panes[SESSIONS[i % len(SESSIONS)]]}
                for i in range(1, n + 1)]
        with open(os.path.join(self.home, "agents.json"), "w") as f:
            json.dump(rows, f)

    def once(self, height, **cfg):
        """The drawn frame's lines, ANSI stripped, at HEIGHT rows."""
        cfg.setdefault("agent_format", " {glyph} {label}")
        cfg.setdefault("agent_format2", "   second line")     # no label: one hit per agent
        with open(self.env["SESSIONVIEW_CONFIG"], "w") as f:
            json.dump(cfg, f)
        env = dict(self.env, SIDEBAR_HEIGHT=str(height))
        r = subprocess.run([sys.executable, "-B", SIDEBAR, "--once"], env=env,
                           capture_output=True, text=True, timeout=60, cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = [ANSI.sub("", line).rstrip() for line in r.stdout.splitlines()]
        self.assertEqual(len(lines), height, r.stdout)
        return lines

    def drawn(self, lines):
        """Labels of the agent rows drawn under the agents heading, in order."""
        i = next(k for k, line in enumerate(lines) if HEADING in line)
        return [w for line in lines[i + 1:] for w in line.split() if w.startswith("gapagent")]

    GAP = dict(agent_two_line=True, agent_gap=1)

    def test_twelve_two_line_agents_with_a_gap_all_show(self):
        self.agents(12)
        lines = self.once(65, **self.GAP)
        self.assertEqual(sorted(self.drawn(lines)), [label(i) for i in range(1, 13)],
                         "\n".join(lines))
        self.assertFalse(any(MORE.match(line) for line in lines), "\n".join(lines))
        # the block sits under the projects: every project row is above the heading
        head = next(k for k, line in enumerate(lines) if HEADING in line)
        for name in SESSIONS:
            rows = [k for k, line in enumerate(lines) if name in line.split()]
            self.assertTrue(rows, f"{name} not drawn:\n" + "\n".join(lines))
            self.assertLess(max(rows), head, "\n".join(lines))

    def assert_more_counts_the_hidden(self, n, **cfg):
        self.agents(n)
        lines = self.once(65, **cfg)
        shown = self.drawn(lines)
        self.assertLess(len(shown), n, "\n".join(lines))
        body = [line for line in lines[:-1] if line.strip()]    # the last row is the + strip
        m = MORE.match(body[-1])
        self.assertIsNotNone(m, "last agent-area row is not '+N more':\n" + "\n".join(lines))
        self.assertEqual(int(m.group(1)), n - len(shown), "\n".join(lines))
        self.assertEqual(shown, [label(i) for i in range(1, len(shown) + 1)])

    def test_twenty_five_agents_end_in_more_counting_the_hidden(self):
        self.assert_more_counts_the_hidden(25, **self.GAP)

    def test_wider_gap_one_line_agents_end_in_more(self):
        self.assert_more_counts_the_hidden(40, agent_gap=2)

    def test_negative_gap_counts_as_none(self):
        # a negative agent_gap draws no blank rows, so it must cost none either
        self.assert_more_counts_the_hidden(70, agent_gap=-1)

    def test_no_gap_is_unchanged(self):
        # agent_gap 0: the count was always right; it still is
        self.assert_more_counts_the_hidden(40, agent_two_line=True)


if __name__ == "__main__":
    unittest.main()
