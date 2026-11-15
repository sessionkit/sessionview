"""bin/tmux-sidebar: the `hide` setting matches the seat's word.

A hide list names what the user sees: the sidebar's words (idle, busy,
waiting, blocked), from seat_word(), the same test the glyph, the sort and
the rollups use. Most idle seats say status `shell`, so `hide: ["idle"]`
must hide them too.

A seat's raw status still matches, so a list written before the words
(`hide: ["shell"]`) hides exactly what it hid: the change only adds.

Local rows and a remote host's rows go through the same helper, so they
cannot disagree. The pure tests call the helper; the render tests run
render_base() on a private tmux and read the agent rows it draws.
"""
import json
import os
import unittest

from tests import support
from tests.test_idle_sidebar import pure
from tests.test_seat_word import row

#: agent name -> (status, state) of each seat, local and remote alike.
SEATS = {
    "calm": ("shell", "idle"),        # drawn idle, raw status `shell`
    "plain": ("idle", "idle"),        # drawn idle, raw status `idle`
    "wait": ("waiting", "idle"),      # drawn waiting
    "work": ("busy", "busy"),         # drawn busy
}
LOCAL = {"a" + n: v for n, v in SEATS.items()}
REMOTE = {"r" + n: v for n, v in SEATS.items()}
NAMES = set(LOCAL) | set(REMOTE)


class Helper(unittest.TestCase):
    """seat_hidden(a, hide), pure."""

    def setUp(self):
        self._scratch = support.scratch_env()
        self.env, _ = self._scratch.__enter__()

    def tearDown(self):
        self._scratch.__exit__(None, None, None)

    def hidden(self, hide):
        seats = {n: row(*v) for n, v in SEATS.items()}
        got = pure(self.env, f'''
            seats = json.loads({json.dumps(json.dumps(seats))})
            hide = set(json.loads({json.dumps(json.dumps(hide))}))
            OUT["hidden"] = sorted(n for n, a in seats.items() if m.seat_hidden(a, hide))
        ''')
        return got["hidden"]

    def test_idle_hides_every_seat_drawn_idle(self):
        self.assertEqual(self.hidden(["idle"]), ["calm", "plain"])

    def test_shell_still_hides_what_it_hid(self):
        self.assertEqual(self.hidden(["shell"]), ["calm"])

    def test_waiting_hides_a_waiting_seat_whatever_its_state(self):
        self.assertEqual(self.hidden(["waiting"]), ["wait"])

    def test_busy_hides_the_busy_seat_only(self):
        self.assertEqual(self.hidden(["busy"]), ["work"])

    def test_an_empty_list_hides_nothing(self):
        self.assertEqual(self.hidden([]), [])

    def test_a_seat_with_no_status_or_state_is_not_hidden_by_none(self):
        got = pure(self.env, '''
            OUT["h"] = m.seat_hidden({}, {"idle", "shell"})
        ''')
        self.assertFalse(got["h"])


class Render(unittest.TestCase):
    """render_base() on a private tmux: which agent rows it draws, local
    (from the `session` shim) and remote (a host in REMOTE), for a hide
    list."""

    def setUp(self):
        if not support.have_tmux():
            self.skipTest(support.TMUX_SKIP)
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self._pt = support.private_tmux("hideword")
        self.pt = self._pt.__enter__()
        self.env = self.pt.env(env)
        bin_ = os.path.join(self.home, "bin")
        os.makedirs(bin_)
        self.env["PATH"] = bin_ + os.pathsep + self.env.get("PATH", "")
        self.env["SESSIONVIEW_STATE"] = os.path.join(self.home, "state")
        self.env["SESSIONVIEW_VIEW_SOCK"] = self.pt.sock
        self.env["SIDEBAR_WIDTH"] = "40"
        r = self.pt.tmux("new-session", "-d", "-s", "proj", "-c", self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        pane = self.pt.tmux("list-panes", "-a", "-F", "#{pane_id}").stdout.split()[0]
        rows = [row(st, sa, agent=n, name=n, idle_s=60, tmux_pane=pane)
                for n, (st, sa) in LOCAL.items()]
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

    def drawn(self, hide):
        """The agent names render_base draws with CFG `hide` = HIDE."""
        names = list(REMOTE)
        remote = {
            "agents": [row(*REMOTE[n], agent=n, name=n, idle_s=60, tmux_pane=f"%r{i}")
                       for i, n in enumerate(names)],
            "sessions": [["far-proj", "1", "0"]],
            "p2s": {f"%r{i}": "far-proj" for i in range(len(names))},
            "p2w": {f"%r{i}": "w" for i in range(len(names))},
            "ok": True, "err": ""}
        got = pure(self.env, f"""
            import time
            remote = json.loads({json.dumps(json.dumps(remote))})
            remote["t"] = time.time()
            m.CFG["remotes"] = ["far"]
            m.REMOTE["far"] = remote
            m.CFG["hide"] = json.loads({json.dumps(json.dumps(hide))})
            m.CFG["agent_format"] = " {{glyph}} {{agent}}"
            m.FILTER = "all"
            lines, _ = m.render_base(80)
            OUT["lines"] = [m.ANSI_RE.sub("", l) for l in lines]
        """)
        return sorted({w for l in got["lines"] for w in l.split() if w in NAMES})

    @staticmethod
    def both(*names):
        return sorted(p + n for n in names for p in ("a", "r"))

    def test_nothing_hidden_draws_every_seat(self):
        self.assertEqual(self.drawn([]), sorted(NAMES))

    def test_idle_hides_every_seat_drawn_idle_local_and_remote(self):
        self.assertEqual(self.drawn(["idle"]), self.both("wait", "work"))

    def test_shell_still_hides_exactly_what_it_hid(self):
        self.assertEqual(self.drawn(["shell"]), self.both("plain", "wait", "work"))

    def test_waiting_hides_the_waiting_seat(self):
        self.assertEqual(self.drawn(["waiting"]), self.both("calm", "plain", "work"))

    def test_a_busy_seat_is_not_hidden_by_idle(self):
        drawn = self.drawn(["idle"])
        self.assertIn("awork", drawn)
        self.assertIn("rwork", drawn)


if __name__ == "__main__":
    unittest.main()
