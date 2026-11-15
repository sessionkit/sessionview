"""Remote tabs: a click with no session refuses, and an ended session's tab
is flagged.

The sidebar keeps one LOCAL session per remote host on the default server,
one window per remote session, each running `ssh -t HOST tmux attach -t
=SESSION`. Two paths are pinned here:

- A remote seat whose pane maps to no session on its host (a stale pane id,
  a pane on another tmux server there, a partial poll) has an empty session.
  The attach once went out anyway, as `tmux attach -t =` - a bare `=` is
  tmux's mouse-target token, so the attach failed, the new tab closed and
  the user landed on some other tab. It must refuse with a note instead,
  open no tab and run no ssh.
- A remote host runs `detach-on-destroy off`, so when a remote session
  ends, the client in our tab is moved to another session there and the
  tab keeps the old name. Each clean poll flags such a tab; a live tab, a
  tab that is not an attach, and any failed or empty poll touch nothing.

Nothing real is touched. Both servers are PRIVATE (`sv-test-*` sockets
under a scratch TMUX_TMPDIR). A `tmux` shim on PATH maps the sidebar's
`-L default` to the private local socket; an `ssh` shim drops the options
and the host and runs the remote command locally, against a second private
server that plays the remote host. A `session` shim answers `session list`.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from tests import support
from tests.test_frame_hijack import wait_for

SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")
HOST = "devbox"

# The sidebar module, loaded as the suite loads it elsewhere, then one act:
# click HOST SESSION PANE (a remote seat row's jump), attach HOST SESSION
# (remote_attach, as a remote session row's click), poll HOST (one
# fetch_remote). It prints what the act left behind: the note, the poll.
HARNESS = textwrap.dedent('''
    import importlib.machinery, importlib.util, json, sys
    loader = importlib.machinery.SourceFileLoader("sidebar", sys.argv[1])
    spec = importlib.util.spec_from_loader("sidebar", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    act, host = sys.argv[2], sys.argv[3]
    if act == "click":
        m.jump(("ragent", {"_host": host, "_session": sys.argv[4], "tmux_pane": sys.argv[5]}))
    elif act == "attach":
        m.remote_attach(host, sys.argv[4])
    elif act == "poll":
        m.CFG["remote_connect"] = "auto"
        m.fetch_remote(host)
    R = m.REMOTE.get(host) or {}
    print(json.dumps({"prompt": m.PROMPT, "ok": R.get("ok"), "sessions": R.get("sessions")}))
''')

TMUX_SHIM = '''#!/bin/sh
# tmux for the suite: every call lands on a PRIVATE server. The remote side
# (SV_SHIM_REMOTE set by the ssh shim) is its own socket; locally `-L default`
# and a bare call both mean the private local socket.
real={real}
if [ -n "${{SV_SHIM_REMOTE:-}}" ]; then exec "$real" -L {rsock} "$@"; fi
if [ "${{1:-}}" = "-L" ]; then
    s=$2; shift 2
    [ "$s" = default ] && s={lsock}
    exec "$real" -L "$s" "$@"
fi
exec "$real" -L {lsock} "$@"
'''

SSH_SHIM = '''#!/bin/sh
# ssh for the suite: logs its argv, drops the options and the host, and runs
# the command here, as the remote host would. `-O check` (the control-master
# probe) says a master is up. A DOWN file is a failed connection; an EMPTY
# file is a poll that answered with no sessions at all.
printf '%s\\n' "$*" >> {log}
while [ $# -gt 0 ]; do
    case $1 in
        -O) exit 0 ;;
        -o) shift 2 ;;
        -*) shift ;;
        *) shift; break ;;
    esac
done
if [ -e {down} ]; then
    echo "ssh: connect to host port 22: Connection refused" >&2
    exit 255
fi
if [ -e {empty} ]; then
    printf '[]\\n---PANES\\n\\n---SESS\\n'
    exit 0
fi
unset TMUX TMUX_PANE
SV_SHIM_REMOTE=1; export SV_SHIM_REMOTE
exec sh -c "$*"
'''

SESSION_SHIM = '''#!/bin/sh
# session for the suite: no seats anywhere.
echo '[]'
'''


class RemoteTabs(unittest.TestCase):
    """A local and a 'remote' private tmux server, and the three shims."""

    def setUp(self):
        support.require_tmux()
        self.real_tmux = shutil.which("tmux")
        # Short: a unix socket path is capped at ~104 bytes.
        self.tmpdir = tempfile.mkdtemp(prefix="svt-", dir="/tmp" if os.path.isdir("/tmp") else None)
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.lsock = f"sv-test-rtl-{os.getpid()}"
        self.rsock = f"sv-test-rtr-{os.getpid()}"
        for s in (self.lsock, self.rsock):
            self.addCleanup(self.kill, s)
        self.shims = os.path.join(self.tmpdir, "bin")
        os.mkdir(self.shims)
        self.log = os.path.join(self.tmpdir, "ssh.log")
        self.down = os.path.join(self.tmpdir, "DOWN")
        self.empty = os.path.join(self.tmpdir, "EMPTY")
        q = lambda p: "'" + p + "'"
        self.shim("tmux", TMUX_SHIM.format(real=q(self.real_tmux), lsock=self.lsock, rsock=self.rsock))
        self.shim("ssh", SSH_SHIM.format(log=q(self.log), down=q(self.down), empty=q(self.empty)))
        self.shim("session", SESSION_SHIM)
        ctx = support.scratch_env()
        self.env, _ = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        self.env["PATH"] = self.shims + os.pathsep + self.env.get("PATH", "")
        self.env["TMUX_TMPDIR"] = self.tmpdir
        self.env["SESSIONVIEW_STATE"] = os.path.join(self.tmpdir, "state")

    def shim(self, name, text):
        p = os.path.join(self.shims, name)
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, 0o755)

    def kill(self, sock):
        subprocess.run([self.real_tmux, "-L", sock, "kill-server"], capture_output=True,
                       env=dict(self.env, TMUX_TMPDIR=self.tmpdir) if hasattr(self, "env") else None)

    def tmux(self, sock, *args):
        assert sock.startswith("sv-test-"), sock
        e = {k: v for k, v in self.env.items() if k not in ("TMUX", "TMUX_PANE")}
        return subprocess.run([self.real_tmux, "-L", sock, *args], capture_output=True,
                              text=True, env=e, timeout=30)

    def sidebar(self, *args):
        r = subprocess.run([sys.executable, "-B", "-c", HARNESS, SIDEBAR, *args], env=self.env,
                           capture_output=True, text=True, timeout=60, cwd=self.tmpdir)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def ssh_calls(self):
        try:
            with open(self.log) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def tabs(self):
        """{window name: @sessionview_remote_ended} of the local host session."""
        r = self.tmux(self.lsock, "list-windows", "-t", "=" + HOST, "-F",
                      "#{window_name}\t#{@sessionview_remote_ended}")
        if r.returncode != 0:
            return None
        return dict(l.split("\t") for l in r.stdout.splitlines())

    def remote(self, *sessions):
        """The 'remote host': SESSIONS on its private server, with
        detach-on-destroy off, as the real hosts run."""
        first, *rest = sessions
        self.tmux(self.rsock, "new-session", "-d", "-s", first, "-x", "80", "-y", "20")
        self.tmux(self.rsock, "set", "-g", "detach-on-destroy", "off")
        for s in rest:
            self.tmux(self.rsock, "new-session", "-d", "-s", s, "-x", "80", "-y", "20")

    def clients(self):
        """[session] of every client attached to the remote server."""
        r = self.tmux(self.rsock, "list-clients", "-F", "#{client_session}")
        return sorted(r.stdout.splitlines()) if r.returncode == 0 else []


class EmptySessionClick(RemoteTabs):
    """A remote seat whose pane maps to no session refuses on the sidebar."""

    def test_click_with_no_session_refuses_and_opens_nothing(self):
        self.remote("alpha")
        out = self.sidebar("click", HOST, "", "%9")
        # nothing opened: no local host session, no ssh at all
        self.assertIsNone(self.tabs(), "a tab was opened for a seat with no session")
        self.assertEqual(self.ssh_calls(), [], "ssh ran for a seat with no session")
        self.assertEqual(self.clients(), [], "something attached on the remote")
        # the refusal is a note in the sidebar, naming the host and the pane
        p = out["prompt"]
        self.assertIsNotNone(p, "no refusal shown")
        self.assertEqual(p["kind"], "note")
        self.assertIn(HOST, p["label"])
        self.assertIn("%9", p["label"])

    def test_click_with_no_session_leaves_open_tabs_alone(self):
        """With the host session already open, the refusal neither adds a tab
        nor selects one."""
        self.remote("alpha")
        self.sidebar("attach", HOST, "alpha")
        self.assertTrue(wait_for(lambda: self.clients() == ["alpha"]), self.clients())
        before = self.tabs()
        calls = len(self.ssh_calls())
        out = self.sidebar("click", HOST, "", "%9")
        self.assertEqual(self.tabs(), before)
        self.assertEqual(len(self.ssh_calls()), calls, self.ssh_calls()[calls:])
        self.assertEqual(out["prompt"]["kind"], "note")

    def test_click_with_a_session_still_attaches(self):
        self.remote("alpha")
        out = self.sidebar("click", HOST, "alpha", "")
        self.assertIsNone(out["prompt"])
        self.assertEqual(self.tabs(), {"alpha": ""})
        self.assertTrue(wait_for(lambda: self.clients() == ["alpha"]), self.clients())


class EndedSessionTab(RemoteTabs):
    """A tab whose remote session ended is flagged on the next clean poll."""

    def open_two(self):
        self.remote("alpha", "beta")
        self.sidebar("attach", HOST, "alpha")
        self.sidebar("attach", HOST, "beta")
        self.assertTrue(wait_for(lambda: self.clients() == ["alpha", "beta"]), self.clients())
        # a window of the user's own in the host session: not an attach
        self.tmux(self.lsock, "new-window", "-d", "-t", "=" + HOST, "-n", "notes", "sh")
        self.assertEqual(self.tabs(), {"alpha": "", "beta": "", "notes": ""})

    def end_alpha(self):
        """The remote session ends; its client moves to beta (detach-on-destroy
        off) and the local tab keeps the name alpha: the stale tab."""
        self.tmux(self.rsock, "kill-session", "-t", "=alpha")
        self.assertTrue(wait_for(lambda: self.clients() == ["beta", "beta"]), self.clients())
        self.assertIn("alpha", self.tabs())

    def test_poll_flags_the_ended_sessions_tab(self):
        self.open_two()
        self.end_alpha()
        out = self.sidebar("poll", HOST)
        self.assertTrue(out["ok"])
        tabs = self.tabs()
        self.assertNotIn("alpha", tabs, f"the ended session's tab is still named alpha: {tabs}")
        self.assertEqual(tabs.get("alpha (ended)"), "alpha", tabs)
        # the live tab and the user's own window are untouched, and the
        # flagged tab is not closed: its ssh client is still attached
        self.assertEqual(tabs.get("beta"), "", tabs)
        self.assertEqual(tabs.get("notes"), "", tabs)
        self.assertEqual(len(tabs), 3, tabs)
        self.assertEqual(self.clients(), ["beta", "beta"])

    def test_flag_is_written_once(self):
        self.open_two()
        self.end_alpha()
        self.sidebar("poll", HOST)
        first = self.tabs()
        self.sidebar("poll", HOST)
        self.assertEqual(self.tabs(), first)

    def test_live_tabs_are_untouched(self):
        self.open_two()
        self.sidebar("poll", HOST)
        self.assertEqual(self.tabs(), {"alpha": "", "beta": "", "notes": ""})

    def test_a_tab_the_user_renamed_is_judged_by_its_attach(self):
        """The tab is judged by the session its attach names, not by its
        name: a live tab renamed by the user is never flagged."""
        self.open_two()
        self.tmux(self.lsock, "rename-window", "-t", f"={HOST}:beta", "mine")
        self.sidebar("poll", HOST)
        self.assertEqual(self.tabs(), {"alpha": "", "mine": "", "notes": ""})

    def test_a_quoted_name_opened_from_a_seat_is_read(self):
        """A session name that needs quoting, opened by a seat click (whose
        attach first selects the seat's pane), is still read from the attach."""
        self.remote("my work", "beta")
        pane = self.tmux(self.rsock, "display-message", "-p", "-t", "=my work:", "#{pane_id}").stdout.strip()
        self.assertTrue(pane.startswith("%"), pane)
        self.sidebar("click", HOST, "my work", pane)
        self.sidebar("attach", HOST, "beta")
        self.assertTrue(wait_for(lambda: self.clients() == ["beta", "my work"]), self.clients())
        self.assertIn("select-pane -t " + pane, self.ssh_calls()[0])
        self.sidebar("poll", HOST)
        self.assertEqual(self.tabs(), {"my work": "", "beta": ""})
        self.tmux(self.rsock, "kill-session", "-t", "=my work")
        self.assertTrue(wait_for(lambda: self.clients() == ["beta", "beta"]), self.clients())
        self.sidebar("poll", HOST)
        self.assertEqual(self.tabs(), {"my work (ended)": "my work", "beta": ""})

    def test_names_tmux_escapes_are_read_as_named(self):
        """tmux escapes `$` (and `\\`) in a pane's start command; a live tab
        whose session name has them is not flagged, and is once it ends.
        The names are read back from the remote, as a poll reads them: tmux
        stores a typed backslash doubled, and doubles it again in the local
        tab's name, so the tabs are compared by their flags."""
        self.remote("a$b", "c\\$d", "{e};f", "beta")
        odd = [s for s in self.tmux(self.rsock, "list-sessions", "-F", "#{session_name}").stdout.splitlines()
               if s != "beta"]
        self.assertEqual(len(odd), 3, odd)
        self.assertIn("a$b", odd)
        for s in odd + ["beta"]:
            self.sidebar("attach", HOST, s)
        self.assertTrue(wait_for(lambda: len(self.clients()) == len(odd) + 1), self.clients())
        self.sidebar("poll", HOST)
        tabs = self.tabs()
        self.assertEqual(len(tabs), len(odd) + 1, tabs)
        self.assertEqual(set(tabs.values()), {""}, f"a live tab was flagged: {tabs}")
        for s in odd:
            self.tmux(self.rsock, "kill-session", "-t", "=" + s)
        self.assertTrue(wait_for(lambda: self.clients() == ["beta"] * (len(odd) + 1)), self.clients())
        self.sidebar("poll", HOST)
        tabs = self.tabs()
        self.assertEqual(sorted(tabs.values()), sorted(odd + [""]), tabs)
        self.assertEqual(tabs.get("beta"), "", tabs)
        self.assertIn("a$b (ended)", tabs)

    def test_failed_poll_touches_nothing(self):
        self.open_two()
        self.end_alpha()
        open(self.down, "w").close()
        out = self.sidebar("poll", HOST)
        self.assertFalse(out["ok"])
        self.assertEqual(self.tabs(), {"alpha": "", "beta": "", "notes": ""})

    def test_empty_poll_touches_nothing(self):
        self.open_two()
        self.end_alpha()
        open(self.empty, "w").close()
        out = self.sidebar("poll", HOST)
        self.assertEqual(out["sessions"], [])
        self.assertEqual(self.tabs(), {"alpha": "", "beta": "", "notes": ""})


if __name__ == "__main__":
    unittest.main()
