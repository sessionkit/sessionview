"""The frame takes over the caller's OWN terminal, or nothing (SV-192).

`sessionview-frame` run inside tmux hands its terminal over with
`detach-client -E`. It once found "its" client with an untargeted
`tmux display -p '#{client_tty}'`. From a pane whose session has no client,
tmux answers with the most recently active client on the server, which is
another terminal, and the detach replaced that terminal with a frame. And
`sessionview WORD` for any unknown WORD went straight to that frame.

Every test here runs on a PRIVATE tmux server (support.private_tmux: its own
TMUX_TMPDIR, so even tmux's "default" socket is private) with TMUX and
TMUX_PANE never inherited, and kills every server in that dir afterwards.
The "terminals" are pty-backed `tmux attach` clients made here. PATH is cut
down to tmux plus the system dirs, so a frame that does open finds no agent
or tool to start.

What is proven:
  (a) a caller whose session has no client, or two, or whose window is also
      in another terminal's session (a session group, `link-window`),
      touches no client, even when another client was the most recently
      active one right before;
  (b) a caller with no tty touches nothing (no client, no new server);
  (c) a genuine caller (its tty is its pane's, one client on its session)
      still gets the hand-over, onto ITS client and no other;
  (d) an unknown word is usage and exit 2: no session made, no frame;
  (e) an existing session's name still gets past that gate;
  (f) sessionview-sidebar-toggle, run by path as the front door's
      `sidebar-toggle` route runs it, holds the same line.
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from tests import support

try:
    import fcntl
    import struct
    import termios
except ImportError:  # pragma: no cover - not POSIX
    fcntl = None

SV = os.path.join(support.BIN, "sessionview")
FRAME = os.path.join(support.BIN, "sessionview-frame")
TOGGLE = os.path.join(support.BIN, "sessionview-sidebar-toggle")
WAIT = 15


def wait_for(pred, timeout=WAIT, step=0.1):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return pred()


class PtyClient:
    """`tmux -L SOCK attach -t =SESSION` on a fresh pty: a terminal."""

    def __init__(self, sock, session, env):
        self.master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 160, 0, 0))
        self.tty = os.ttyname(slave)
        self.proc = subprocess.Popen(["tmux", "-L", sock, "attach", "-t", "=" + session],
                                     stdin=slave, stdout=slave, stderr=slave, env=env,
                                     start_new_session=True)
        os.close(slave)
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self):
        while True:
            try:
                if not os.read(self.master, 65536):
                    return
            except OSError:
                return

    def type(self, data):
        os.write(self.master, data)

    def close(self):
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.close(self.master)
        except OSError:
            pass


class HijackCase(unittest.TestCase):
    """A private server with sessions that run `sleep` (a key typed into one
    reaches nothing), pty clients on them, and helpers to run a caller in a
    pane of that server or as a plain non-tty process."""

    def setUp(self):
        support.require_tmux()
        if fcntl is None:
            self.skipTest("SKIPPED: needs a POSIX pty")
        cm = support.private_tmux("hijack")
        self.pt = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        envcm = support.scratch_env()
        self.base, self.home = envcm.__enter__()
        self.addCleanup(envcm.__exit__, None, None, None)
        self.addCleanup(self._kill_private_servers)   # runs before HOME goes
        # PATH: tmux and the system dirs only - no agent, no `session`, no `tm`
        pbin = os.path.join(self.home, "pbin")
        os.makedirs(pbin)
        os.symlink(shutil.which("tmux"), os.path.join(pbin, "tmux"))
        self.base["PATH"] = pbin + ":/usr/bin:/bin:/usr/sbin:/sbin"
        self.frame_sock = self.pt.sock + "-frame"
        self.base["SESSIONVIEW_FRAME_SOCK"] = self.frame_sock
        self.base["SESSIONVIEW_STATE"] = os.path.join(self.home, "state")
        # a frame that does open must not stop to ask about an agent
        r = support.run("sessionview-config", "set", "autostart_agent", "", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.clients = []
        self.addCleanup(lambda: [c.close() for c in self.clients])
        self.out = os.path.join(self.home, "out")
        os.makedirs(self.out)
        self.tmux("-f", "/dev/null", "new-session", "-d", "-s", "A", "-x", "160", "-y", "40", "sleep 3600")
        self.tmux("set", "-g", "exit-empty", "off")

    def _kill_private_servers(self):
        # every server under the PRIVATE TMUX_TMPDIR: the test's, the frame
        # server, and a private "default" if anything made one
        root = self.pt.tmpdir
        for d, _dirs, files in os.walk(root):
            for f in files:
                p = os.path.join(d, f)
                assert p.startswith(root), p
                subprocess.run(["tmux", "-S", p, "kill-server"], env=self.pt.env(),
                               capture_output=True, timeout=30)

    def env(self, **extra):
        e = self.pt.env(self.base)
        e.update(extra)
        return e

    def tmux(self, *args, sock=None):
        r = subprocess.run(["tmux", "-L", sock or self.pt.sock, *args], env=self.env(),
                           capture_output=True, text=True, timeout=30)
        return r

    def socket_path(self, sock=None):
        return os.path.join(self.pt.tmpdir, f"tmux-{os.getuid()}", sock or self.pt.sock)

    def session(self, name, *cmd):
        r = self.tmux("new-session", "-d", "-s", name, "-x", "160", "-y", "40", *(cmd or ("sleep 3600",)))
        self.assertEqual(r.returncode, 0, r.stderr)

    def client(self, session):
        c = PtyClient(self.pt.sock, session, self.env(TERM="xterm-256color"))
        self.clients.append(c)
        self.assertTrue(wait_for(lambda: c.tty in self.clients_on()), f"client on {session} never attached")
        return c

    def clients_on(self, sock=None):
        """{tty: session} of the clients on a server."""
        r = self.tmux("list-clients", "-F", "#{client_tty}\t#{session_name}", sock=sock)
        return dict(l.split("\t", 1) for l in r.stdout.splitlines() if "\t" in l)

    def activity(self, c):
        r = self.tmux("list-clients", "-F", "#{client_tty}\t#{client_activity}")
        rows = dict(l.split("\t") for l in r.stdout.splitlines() if "\t" in l)
        return int(rows.get(c.tty, "0"))

    def make_most_recent(self, recent, *others):
        """Type into RECENT so it is the most recently active client (tmux
        keeps activity in whole seconds, so wait one out first)."""
        time.sleep(1.1)
        recent.type(b"x")
        self.assertTrue(wait_for(lambda: all(self.activity(recent) > self.activity(o) for o in others)),
                        "precondition: the other client is the most recently active")

    def run_in_pane(self, tag, argv, session=None, before=None):
        """Run ARGV as the process in a pane: its stdin/stdout are the pane's
        pty. In a NEW session (no client) unless SESSION names one to add a
        window to. BEFORE(window_id), if given, runs once the window exists
        and before ARGV starts. Returns (rc, stderr)."""
        rc, err = os.path.join(self.out, tag + ".rc"), os.path.join(self.out, tag + ".err")
        runner = os.path.join(self.out, tag + ".sh")
        with open(runner, "w") as f:
            f.write('"$@" 2>"%s"; echo $? >"%s.tmp"; mv "%s.tmp" "%s"; sleep 1\n' % (err, rc, rc, rc))
        cmd = " ".join(["sh", runner] + [f"'{a}'" for a in argv])
        go = os.path.join(self.out, tag + ".go")
        if before:
            cmd = f"while [ ! -e '{go}' ]; do sleep 0.1; done; " + cmd
        fmt = ("-P", "-F", "#{window_id}")
        if session:
            r = self.tmux("new-window", "-d", *fmt, "-t", f"={session}:", cmd)
        else:
            r = self.tmux("new-session", "-d", *fmt, "-s", tag, "-x", "160", "-y", "40", cmd)
        self.assertEqual(r.returncode, 0, r.stderr)
        if before:
            before(r.stdout.strip())
            open(go, "w").close()
        self.assertTrue(wait_for(lambda: os.path.exists(rc)), f"{tag}: the caller never finished")
        with open(rc) as f, open(err) as g:
            return int(f.read().strip()), g.read()

    def pane_of(self, session):
        return self.tmux("display-message", "-p", "-t", f"={session}:", "#{pane_id}").stdout.strip()

    def run_no_tty(self, argv, inside=None):
        """ARGV with stdin and stdout NOT a tty, as a script or an agent's
        shell runs it. INSIDE names a session whose pane TMUX and TMUX_PANE
        point at (an inherited TMUX); None = outside tmux."""
        extra = {}
        if inside:
            sid = self.tmux("display-message", "-p", "-t", f"={inside}:", "#{session_id}").stdout.strip()
            extra = dict(TMUX=f"{self.socket_path()},1,{sid.lstrip('$')}", TMUX_PANE=self.pane_of(inside))
        return subprocess.run(argv, env=self.env(**extra), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30)

    def assert_untouched(self, want):
        """Every client in WANT ({tty: session}) is still on the server, on its
        own session, and no frame server came up."""
        time.sleep(0.5)
        now = self.clients_on()
        for tty, sess in want.items():
            self.assertEqual(now.get(tty), sess, f"client {tty} was moved or detached: {now}")
        self.assertEqual(self.clients_on(sock=self.frame_sock), {}, "a frame took a terminal")


class FrameHijack(HijackCase):

    def test_a_caller_in_a_session_with_no_client_touches_no_client(self):
        # the reported shape: two terminals, the caller's pane in a
        # third session nobody is looking at, B used last
        self.session("B")
        a, b = self.client("A"), self.client("B")
        self.make_most_recent(b, a)
        rc, err = self.run_in_pane("C", [FRAME])
        self.assert_untouched({a.tty: "A", b.tty: "B"})
        self.assertEqual(rc, 2, err)
        self.assertIn("no terminal is attached to this session", err)

    def test_a_caller_in_a_session_open_in_two_terminals_touches_neither(self):
        a = self.client("A")
        b = self.client("A")
        self.make_most_recent(b, a)
        rc, err = self.run_in_pane("two", [FRAME], session="A")
        self.assert_untouched({a.tty: "A", b.tty: "A"})
        self.assertEqual(rc, 2, err)
        self.assertIn("more than one terminal", err)

    def test_a_caller_whose_window_is_in_a_session_group_touches_neither(self):
        # G is grouped with A: the caller's window is in both, a shows A, b
        # shows G and was used last. tmux names G for the pane, and G has
        # one client, b - another terminal. Two terminals show the pane.
        r = self.tmux("new-session", "-d", "-t", "=A", "-s", "G", "-x", "160", "-y", "40")
        self.assertEqual(r.returncode, 0, r.stderr)
        a, b = self.client("A"), self.client("G")
        self.make_most_recent(b, a)
        rc, err = self.run_in_pane("grp", [FRAME], session="A")
        self.assert_untouched({a.tty: "A", b.tty: "G"})
        self.assertEqual(rc, 2, err)
        self.assertIn("more than one terminal", err)

    def test_a_caller_whose_window_is_linked_into_another_session_touches_neither(self):
        self.session("L")
        a, b = self.client("A"), self.client("L")
        self.make_most_recent(b, a)

        def link(wid):
            r = self.tmux("link-window", "-d", "-s", wid, "-t", "=L:9")
            self.assertEqual(r.returncode, 0, r.stderr)
        rc, err = self.run_in_pane("lnk", [FRAME], session="A", before=link)
        self.assert_untouched({a.tty: "A", b.tty: "L"})
        self.assertEqual(rc, 2, err)
        self.assertIn("more than one terminal", err)

    def test_a_caller_with_no_tty_and_an_inherited_tmux_touches_nothing(self):
        self.session("B")
        self.session("C")
        a, b = self.client("A"), self.client("B")
        self.make_most_recent(b, a)
        r = self.run_no_tty([FRAME], inside="C")
        self.assert_untouched({a.tty: "A", b.tty: "B"})
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not a terminal", r.stderr)

    def test_a_caller_with_no_tty_outside_tmux_makes_nothing(self):
        before = sorted(self.pt.sessions())
        r = self.run_no_tty([FRAME, "A", "--sock", self.pt.sock])
        self.assertFalse(os.path.exists(self.socket_path(self.frame_sock)), "a frame server was started")
        self.assertEqual(sorted(self.pt.sessions()), before)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not a terminal", r.stderr)

    def test_a_genuine_caller_hands_over_its_own_terminal_and_no_other(self):
        # the human path survives: the caller's tty is its pane's and one
        # client shows its session - that client becomes the frame, B (used
        # last, on another session) stays where it was
        self.session("B")
        a, b = self.client("A"), self.client("B")
        self.make_most_recent(b, a)
        rc, err = self.run_in_pane("own", [FRAME], session="A")
        self.assertEqual(rc, 0, err)
        landed = wait_for(lambda: a.tty in self.clients_on(sock=self.frame_sock))
        self.assertTrue(landed, f"A's terminal did not become the frame: {self.clients_on(sock=self.frame_sock)}")
        self.assertEqual(self.clients_on().get(b.tty), "B", "B was touched")
        self.assertNotIn(b.tty, self.clients_on(sock=self.frame_sock))
        # the frame's right pane shows the caller's session
        self.assertTrue(wait_for(lambda: "A" in self.clients_on().values()))


class UnknownWord(HijackCase):
    WORD = "sv192-no-such-session"

    def test_an_unknown_word_is_usage_and_makes_nothing(self):
        r = self.run_no_tty([SV, self.WORD, "--sock", self.pt.sock])
        self.assertNotIn(self.WORD, self.pt.sessions(), "the word minted a session")
        self.assertFalse(os.path.exists(self.socket_path(self.frame_sock)), "a frame server was started")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn(f"no command or session named '{self.WORD}'", r.stderr)
        self.assertIn("usage: sessionview", r.stderr)

    def test_an_unknown_word_prints_the_same_usage_as_help(self):
        # SV-190 grew the header that -h prints; SV-192's miss branch kept its
        # own line range and lost the header's tail. One usage, two callers.
        h = self.run_no_tty([SV, "-h"])
        self.assertEqual(h.returncode, 0, h.stderr)
        r = self.run_no_tty([SV, self.WORD, "--sock", self.pt.sock])
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertNotIn(self.WORD, self.pt.sessions(), "the word minted a session")
        self.assertFalse(os.path.exists(self.socket_path(self.frame_sock)), "a frame server was started")
        first, _, usage = r.stderr.partition("\n")
        self.assertIn(f"no command or session named '{self.WORD}'", first)
        self.assertEqual(usage, h.stdout)

    def test_an_unknown_word_inside_tmux_is_checked_on_that_server(self):
        self.session("C")
        a = self.client("A")
        r = self.run_no_tty([SV, self.WORD], inside="C")
        self.assert_untouched({a.tty: "A"})
        self.assertNotIn(self.WORD, self.pt.sessions(), "the word minted a session")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn(f"on tmux server {self.pt.sock}", r.stderr)

    def test_an_unknown_word_outside_tmux_starts_no_default_server(self):
        r = self.run_no_tty([SV, self.WORD])
        self.assertFalse(os.path.exists(self.socket_path("default")), "a default server was started")
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_an_existing_session_gets_past_the_gate(self):
        # past the word gate, the frame's own rules apply: here, no tty
        r = self.run_no_tty([SV, "A", "--sock", self.pt.sock])
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertNotIn("no command or session named", r.stderr)
        self.assertIn("not a terminal", r.stderr)

    def test_an_existing_session_inside_tmux_gets_past_the_gate(self):
        self.session("C")
        r = self.run_no_tty([SV, "A"], inside="C")
        self.assertNotIn("no command or session named", r.stderr)
        self.assertIn("not a terminal", r.stderr)


class ToggleHijack(HijackCase):
    """sessionview-sidebar-toggle with no --tty finds "this client"'s frame and
    breaks its sidebar pane out. The front door's `sidebar-toggle` route
    execs it by path with the user's args, as these tests do."""

    def make_frame_on_b(self):
        """A frame-shaped server: session F, sidebar pane (sleep) on the left
        and, on the right, a client of session B - the inner client whose tty
        the toggle matches. Returns that pane count reader."""
        self.session("B")
        f = self.frame_sock
        r = self.tmux("-f", "/dev/null", "new-session", "-d", "-s", "F", "-x", "160", "-y", "40", "sleep 3600", sock=f)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.tmux("split-window", "-h", "-t", "=F:0", "-e", "TMUX=",
                      f"exec tmux -L {self.pt.sock} attach -t =B", sock=f)
        self.assertEqual(r.returncode, 0, r.stderr)
        ftty = self.tmux("display-message", "-p", "-t", "=F:0.1", "#{pane_tty}", sock=f).stdout.strip()
        self.assertTrue(wait_for(lambda: self.clients_on().get(ftty) == "B"), "the frame's inner client never attached")
        return ftty

    def frame_shape(self):
        # names drift (automatic-rename): count windows and their panes
        r = self.tmux("list-windows", "-t", "=F", "-F", "#{window_index}:#{window_panes}", sock=self.frame_sock)
        return r.stdout.split()

    def hidden_windows(self):
        r = self.tmux("list-windows", "-t", "=F", "-F", "#{window_name}", sock=self.frame_sock)
        return [n for n in r.stdout.split() if n == "sidebar-hidden"]

    def test_toggle_with_no_tty_touches_no_frame(self):
        self.session("C")
        ftty = self.make_frame_on_b()
        shape = self.frame_shape()
        time.sleep(1.1)
        self.tmux("send-keys", "-t", "=F:0.1", "x", sock=self.frame_sock)   # B's client used last
        for args in ([], ["--hide"]):
            r = self.run_no_tty([TOGGLE, *args], inside="C")
            self.assertEqual(self.frame_shape(), shape, f"toggle {args} changed another client's frame")
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("not a terminal", r.stderr)
        self.assertEqual(self.clients_on().get(ftty), "B")

    def test_toggle_from_a_session_with_no_client_touches_no_frame(self):
        ftty = self.make_frame_on_b()
        shape = self.frame_shape()
        time.sleep(1.1)
        self.tmux("send-keys", "-t", "=F:0.1", "x", sock=self.frame_sock)
        rc, err = self.run_in_pane("C", [TOGGLE, "--hide"])
        self.assertEqual(self.frame_shape(), shape, "toggle changed another client's frame")
        self.assertEqual(rc, 2, err)
        self.assertIn("no terminal is attached to this session", err)

    def test_toggle_with_an_explicit_tty_still_works(self):
        # the tab-bar glyph's form (--tty '#{client_tty}', from frame.conf)
        ftty = self.make_frame_on_b()
        r = self.run_no_tty([TOGGLE, "--tty", ftty, "--hide"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.hidden_windows(), ["sidebar-hidden"])


class PopupClient(HijackCase):
    """tmux-sidebar's popup (prefix H) has no pane: its client is the ONE
    client on $TMUX's session, never the most recently active one."""

    HARNESS = (
        "import importlib.machinery, importlib.util, sys\n"
        "loader = importlib.machinery.SourceFileLoader('sidebar', sys.argv[1])\n"
        "spec = importlib.util.spec_from_loader('sidebar', loader)\n"
        "m = importlib.util.module_from_spec(spec); loader.exec_module(m)\n"
        "print(repr(m.popup_client()))\n")

    def popup_client(self, session):
        sid = self.tmux("display-message", "-p", "-t", f"={session}:", "#{session_id}").stdout.strip()
        env = self.env(TMUX=f"{self.socket_path()},1,{sid.lstrip('$')}")
        r = subprocess.run([sys.executable, "-B", "-c", self.HARNESS, os.path.join(support.BIN, "tmux-sidebar")],
                           env=env, capture_output=True, text=True, timeout=30, cwd=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        return eval(r.stdout.strip().splitlines()[-1])

    def test_one_client_on_the_session_is_the_popups(self):
        self.session("B")
        a, b = self.client("A"), self.client("B")
        self.make_most_recent(b, a)
        self.assertEqual(self.popup_client("A"), a.tty)

    def test_two_clients_on_the_session_is_no_client(self):
        a, b = self.client("A"), self.client("A")
        self.make_most_recent(b, a)
        self.assertEqual(self.popup_client("A"), "")


if __name__ == "__main__":
    unittest.main()
