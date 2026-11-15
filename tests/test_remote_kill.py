"""Kill on a remote attach tab never acts locally.

A click on a remote agent row opens a LOCAL tab whose pane runs
`ssh -t HOST ... tmux attach` (remote_attach in bin/tmux-sidebar). The agent
pane menu's Kill item is tmux's `kill-pane`, which acts on the pane it was
opened on: on that tab, the local ssh client. That closes the tab and leaves
the agent running on its host. So on a remote attach tab Kill refuses, with a
message on the bar naming the host; on any other pane it is unchanged.

What is checked, on private tmux servers only (support.private_tmux), with a
PATH-first shim directory that records every `tmux`, `ssh` and `kill` call:

- remote_attach, run for real from the sidebar, marks the tab's pane with the
  host (a pane option), on a new session and on a new window alike, and the
  sidebar runs no kill of any kind while doing it.
- real clicks: Option + right-click, and a plain right-click (the ssh pane's
  program has no mouse mode here), on the remote tab open the menu; choosing
  Kill (its key, X) leaves the local pane alive, puts the message on the
  bar, and records zero `kill` calls.
- a local agent pane: the same click and key still kill it.

The tmux shim maps the sidebar's `-L default` onto the private socket, under
a scratch TMUX_TMPDIR, so no real server is ever touched. The ssh shim stands
in for the attached client (a long sleep); `kill` is recorded and never run.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
import unittest

from tests import support

SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")
CONF = os.path.join(support.REPO, "tmux", "agent-menu.conf")
HOST = "devbox"
OPTION = "@sessionview_remote_host"
AGENT = "✳ worker.sv-test"

TMUX_SHIM = r'''#!/bin/sh
printf 'tmux %s\n' "$*" >> "$SV_SHIM_LOG"
n=$#; i=0; prev=
while [ "$i" -lt "$n" ]; do
  a=$1; shift; i=$((i + 1))
  if [ "$prev" = "-L" ] && [ "$a" = "default" ]; then a=$SV_SOCK; fi
  set -- "$@" "$a"; prev=$a
done
exec "$SV_REAL_TMUX" "$@"
'''

SSH_SHIM = r'''#!/bin/sh
printf 'ssh %s\n' "$*" >> "$SV_SHIM_LOG"
for a in "$@"; do
  [ "$a" = "-t" ] && exec sleep 600
done
exit 0
'''

KILL_SHIM = r'''#!/bin/sh
printf 'kill %s\n' "$*" >> "$SV_SHIM_LOG"
exit 0
'''

HARNESS = textwrap.dedent('''
    import importlib.machinery, importlib.util, sys
    loader = importlib.machinery.SourceFileLoader("sidebar", sys.argv[1])
    spec = importlib.util.spec_from_loader("sidebar", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    for host, session, pane in zip(*[iter(sys.argv[2:])] * 3):
        m.remote_attach(host, session, pane)
''')


class RemoteKill(unittest.TestCase):

    W, H = 100, 30
    AT = (20, 10)   # x, y of every click, 1-based: inside the pane

    def setUp(self):
        support.require_tmux()
        self._scratch = support.scratch_env()
        self.env, self.home = self._scratch.__enter__()
        self._servers = []
        self.pt = self._server("rk")
        shims = os.path.join(self.home, "shims")
        os.mkdir(shims)
        for name, body in (("tmux", TMUX_SHIM), ("ssh", SSH_SHIM), ("kill", KILL_SHIM)):
            p = os.path.join(shims, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, 0o755)
        self.log = os.path.join(self.home, "shim.log")
        open(self.log, "w").close()
        real = shutil.which("tmux")
        self.assertTrue(real)
        self.shim_env = dict(self.pt.env(self.env), PATH=shims + os.pathsep + self.env["PATH"],
                             SV_SHIM_LOG=self.log, SV_SOCK=self.pt.sock, SV_REAL_TMUX=real)
        # the user's own tmux, with the agent pane menu on
        self.t(self.pt, "-f", "/dev/null", "new-session", "-d", "-s", "home",
               "-x", str(self.W), "-y", str(self.H), "exec sleep 600")
        self.t(self.pt, "set", "-g", "mouse", "on")
        self.t(self.pt, "set", "-g", "display-time", "10000")
        r = self.pt.tmux("source-file", CONF, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def tearDown(self):
        for cm in reversed(self._servers):
            cm.__exit__(None, None, None)
        self._scratch.__exit__(None, None, None)

    def _server(self, tag):
        cm = support.private_tmux(tag)
        pt = cm.__enter__()
        self._servers.append(cm)
        return pt

    def t(self, pt, *args):
        r = pt.tmux(*args, env=self.env)
        self.assertEqual(r.returncode, 0, f"tmux {' '.join(args)}: {r.stderr}")
        return r.stdout

    def wait(self, what, pred, secs=15):
        end = time.time() + secs
        while True:
            got = pred()
            if got:
                return got
            if time.time() > end:
                self.fail(f"timed out waiting for {what}")
            time.sleep(0.1)

    def shim_log(self):
        with open(self.log) as f:
            return f.read().splitlines()

    def attach(self, *triples):
        """Run the sidebar's remote_attach(HOST, SESSION, PANE) for each triple,
        in one process, with the shims first on PATH."""
        argv = [a for t in triples for a in t]
        r = subprocess.run([sys.executable, "-B", "-c", HARNESS, SIDEBAR, *argv],
                           env=self.shim_env, capture_output=True, text=True, timeout=60,
                           cwd=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)

    def panes(self, session):
        r = self.pt.tmux("list-panes", "-s", "-t", "=" + session, "-F",
                         "#{pane_id}\t#{window_name}\t#{" + OPTION + "}", env=self.env)
        return [l.split("\t") for l in r.stdout.splitlines()] if r.returncode == 0 else []

    def alive(self, pane):
        r = self.pt.tmux("display", "-p", "-t", pane, "#{pane_id}", env=self.env)
        return r.returncode == 0 and r.stdout.strip() == pane

    # -- a terminal whose pane runs a tmux client of the user's server --

    def client(self, target):
        client = (f"unset TMUX TMUX_PANE; TMUX_TMPDIR={shlex.quote(self.pt.tmpdir)} "
                  f"tmux -L {shlex.quote(self.pt.sock)} attach -t {shlex.quote(target)}; exec sleep 600")
        self.term = self._server("rkterm")
        self.t(self.term, "-f", "/dev/null", "new-session", "-d", "-s", "t",
               "-x", str(self.W), "-y", str(self.H), client)
        self.wait("the client to attach", lambda: self.t(self.pt, "list-clients").strip())
        self.wait("the client to draw", lambda: "[" in self.screen())

    def screen(self):
        return self.t(self.term, "capture-pane", "-p", "-t", "t")

    def click(self, button):
        x, y = self.AT
        self.t(self.term, "send-keys", "-t", "t", "-l", f"\x1b[<{button};{x};{y}M")

    def choose_kill(self, button):
        """Open the menu with BUTTON (2 plain, 10 Option) and press X, Kill's key."""
        self.click(button)
        self.wait("the menu", lambda: "Kill" in self.screen() and "Respawn" in self.screen())
        self.t(self.term, "send-keys", "-t", "t", "X")

    # -- the tests --

    def test_remote_attach_marks_the_tab_with_its_host(self):
        self.attach((HOST, "work", "%5"), (HOST, "other", ""), (HOST, "work", "%7"))
        rows = self.panes(HOST)
        self.assertEqual(sorted(r[1] for r in rows), ["other", "work"], rows)
        for pane, name, host in rows:
            self.assertEqual(host, HOST, f"pane {pane} ({name}) is not marked")
        # the user's own panes are not
        self.assertEqual([r[2] for r in self.panes("home")], [""])
        log = self.shim_log()
        self.assertTrue(any(l.startswith("ssh ") and " -t " in l for l in log), log)
        self.assertEqual([l for l in log if "kill" in l], [], log)

    def refuses(self, button):
        self.attach((HOST, "work", "%5"))
        (pane, _name, _host), = self.panes(HOST)
        self.client("=" + HOST)
        self.choose_kill(button)
        screen = self.wait("the refusal on the bar, or the pane gone",
                           lambda: (lambda s: ("Not killed" in s or not self.alive(pane)) and s)(self.screen()))
        self.assertTrue(self.alive(pane), "Kill acted on the local attach pane")
        self.assertIn(f"runs on {HOST}", screen)
        log = self.shim_log()
        self.assertEqual([l for l in log if l.startswith("kill")], [], log)
        self.assertEqual([l for l in log if "kill" in l], [], log)

    def test_option_kill_on_a_remote_tab_refuses_and_kills_nothing(self):
        self.refuses(10)

    def test_plain_kill_on_a_remote_tab_refuses_and_kills_nothing(self):
        self.refuses(2)

    def test_kill_on_a_local_agent_pane_still_kills_it(self):
        pane = self.t(self.pt, "new-window", "-t", "home:", "-P", "-F", "#{pane_id}",
                      "exec sleep 600").strip()
        self.t(self.pt, "select-pane", "-t", pane, "-T", AGENT)
        self.client("=home")
        self.choose_kill(10)
        self.wait("the local pane to die", lambda: not self.alive(pane))


if __name__ == "__main__":
    unittest.main()
