"""bin/tmux-sidebar asks only the tmux servers a seat names, never the socket dir.

Picking a store in the sidebar took 3-4 s, then ~2 s more for the menu to
close. The socket dir held 622 files for 3 live servers - test harnesses had
left the rest - and every render forked `tmux -L NAME list-panes` once per
FILE: 3.4-4.0 s a render.
Which servers are live is sessiontools' answer (ST-111 knocks first), and it
reaches the sidebar as each seat's `tmux_socket` in `session list --json`.
So a render touches the viewed server and the servers seats name, and no
others: dead socket files cost it nothing, however many there are.

Render draws `tmux-sidebar --once` on two private servers in one scratch
TMUX_TMPDIR, beside 40 dead socket files, with a `tmux` shim on PATH that
logs every call and hands it to the real tmux.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import unittest

from tests import support

SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")
DEAD = 40


class Render(unittest.TestCase):

    def setUp(self):
        if not support.have_tmux():
            self.skipTest(support.TMUX_SKIP)
        real_tmux = shutil.which("tmux")
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self._pt = support.private_tmux("walk")
        self.pt = self._pt.__enter__()
        self.store = support.PrivateTmux("walkstore", self.pt.tmpdir)  # a second server, same dir
        self.addCleanup(self.store.tmux, "kill-server")
        for t, n in ((self.pt, "alpha"), (self.store, "beta")):
            r = t.tmux("new-session", "-d", "-s", n, "-n", f"{n}-win")
            self.assertEqual(r.returncode, 0, r.stderr)
        sockdir = os.path.join(self.pt.tmpdir, f"tmux-{os.getuid()}")
        for i in range(DEAD):       # bound, never listened on, closed: a refused connect
            s = socket.socket(socket.AF_UNIX)
            s.bind(os.path.join(sockdir, f"sv-test-dead-{i}"))
            s.close()
        self.bin = os.path.join(self.home, "bin")
        os.makedirs(self.bin)
        self.log = os.path.join(self.home, "tmux.log")
        shim = os.path.join(self.bin, "tmux")
        with open(shim, "w") as f:
            f.write(f'#!/bin/sh\nprintf "%s\\n" "$*" >>{self.log!r}\nexec {real_tmux!r} "$@"\n')
        os.chmod(shim, 0o755)
        pane = lambda t: t.tmux("list-panes", "-a", "-F", "#{pane_id}").stdout.split()[0]
        rows = [{"name": "pat", "agent": "pat", "status": "idle", "idle_s": 0,
                 "tmux_socket": self.pt.sock, "tmux_pane": pane(self.pt)},
                {"name": "cleo", "agent": "cleo", "status": "idle", "idle_s": 0,
                 "tmux_socket": self.store.sock, "tmux_pane": pane(self.store)}]
        with open(os.path.join(self.home, "agents.json"), "w") as f:
            json.dump(rows, f)
        p = os.path.join(self.bin, "session")
        with open(p, "w") as f:
            f.write(f"#!/bin/sh\ncat {os.path.join(self.home, 'agents.json')!r}\n")
        os.chmod(p, 0o755)
        self.env = self.pt.env(env)
        self.env["PATH"] = self.bin + os.pathsep + self.env.get("PATH", "")
        self.env["SESSIONVIEW_STATE"] = os.path.join(self.home, "state")
        self.env["SESSIONVIEW_VIEW_SOCK"] = self.pt.sock
        self.env["SIDEBAR_WIDTH"] = "40"
        self.env["SESSIONVIEW_CONFIG"] = os.path.join(self.home, "sessionview-config.json")
        with open(self.env["SESSIONVIEW_CONFIG"], "w") as f:
            json.dump({"agent_format": " {glyph} {agent}"}, f)

    def tearDown(self):
        self._pt.__exit__(None, None, None)
        self._scratch.__exit__(None, None, None)

    def calls(self):
        r = subprocess.run([sys.executable, "-B", SIDEBAR, "--once"], env=self.env,
                           capture_output=True, text=True, timeout=60, cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("cleo", r.stdout)
        with open(self.log) as f:
            return [line.split() for line in f.read().splitlines()]

    def test_dead_socket_files_are_never_asked(self):
        asked = [c[1] for c in self.calls() if len(c) > 1 and c[0] == "-L"]
        self.assertFalse([s for s in asked if s.startswith("sv-test-dead-")],
                         "a render forked tmux for a socket file no seat names")

    def test_a_seats_server_is_asked_once_a_render(self):
        store = [c for c in self.calls() if c[:2] == ["-L", self.store.sock]]
        self.assertEqual([c[2] for c in store], ["list-panes"], store)


if __name__ == "__main__":
    unittest.main()
