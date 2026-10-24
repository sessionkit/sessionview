"""A frame's first open on a fresh HOME must not remember a width the user
never chose; a border the user drags must still be remembered.

The sidebar's fit() adopts a change in its pane's width inside an unchanged
frame window as a border drag, and writes it to view.json. The frame's own
layout steps (its split, its resize to the configured width) change the pane
inside an unchanged window too, before any client is attached. When the
sidebar happened to render between them, a new user's first open wrote
width=100 (half the 200-wide window the frame starts with) and every later
open came up at 100.

That is a race: on an idle host the sidebar often renders after the frame's
steps and nothing is adopted. So the first-open test does not rely on the
host's timing. It runs a scratch COPY of the checkout whose frame sleeps
before its split and before its resize, which gives the sidebar time to
render in between, every time. The product files are not edited, and the
copy is removed afterwards. The test opens the frame several times, each on
a new HOME.

Each open is a real first open: a fresh HOME with no view.json, a scratch
TMUX_TMPDIR, two PRIVATE tmux servers (`-L sv-test-...`, the frame's and the
inner one), no TMUX or TMUX_PANE, and a 160x45 pseudo-terminal as the
client, the way a terminal window runs it. Teardown kills only those two
servers (by their -L names, under that TMUX_TMPDIR) and the run's own
process group. The default tmux server is never addressed.
"""
import fcntl
import itertools
import json
import os
import pty
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import unittest

from tests import support

COLS, ROWS = 160, 45
DEFAULT_WIDTH = 34            # config/config.json
OPENS = 5                     # first opens per test: the race needs several
FORCE = 1.0                   # seconds the copy's frame sleeps before each step
DRAG_TO = 50
_seq = itertools.count()


def view_width(home):
    """The width view.json holds, or None when there is no file or no key."""
    p = os.path.join(home, ".sessionkit", "view", "settings", "view.json")
    try:
        with open(p) as f:
            return json.load(f).get("width")
    except (OSError, ValueError):
        return None


def forced_copy(dst):
    """Copy the checkout to DST with the frame sleeping FORCE seconds just
    before its split-window and just before its first resize of the sidebar.
    Returns DST. Fails the test if either line is gone: the test would then
    no longer hold the order open, and must be updated with the frame."""
    shutil.copytree(support.REPO, dst,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"))
    frame = os.path.join(dst, "bin", "sessionview-frame")
    with open(frame) as f:
        lines = f.read().split("\n")
    out, did = [], []
    for ln in lines:
        if ln.startswith('MAIN="$(o split-window') and "split" not in did:
            out.append(f"sleep {FORCE}"); did.append("split")
        elif ln.startswith('o resize-pane -t "$SIDE"') and "split" in did and "resize" not in did:
            out.append(f"sleep {FORCE}"); did.append("resize")
        out.append(ln)
    if did != ["split", "resize"]:
        raise AssertionError(f"the frame's split/resize lines moved (found {did}): update forced_copy")
    with open(frame, "w") as f:
        f.write("\n".join(out))
    return dst


class FrameOpen:
    """One first open of the frame at ROOT under a pty, on its own HOME and
    its own private servers. `start()`, then `sample()` until settled, then
    `close()` (always). `tmux(*args)` runs one command on the FRAME server."""

    def __init__(self, root):
        self.root = root
        self.base = tempfile.mkdtemp(prefix="sv-test-fw-")
        self.home = os.path.join(self.base, "home")
        os.mkdir(self.home)
        # short: a unix socket path is capped at ~104 bytes (macOS)
        self.tmpdir = tempfile.mkdtemp(prefix="svt-", dir="/tmp" if os.path.isdir("/tmp") else None)
        tag = f"{os.getpid()}-{next(_seq)}"
        self.frame_sock, self.inner_sock = f"sv-test-fw-frame-{tag}", f"sv-test-fw-inner-{tag}"
        # A new user's PATH: tmux and this Python, no session tools.
        sysbin = os.path.join(self.base, "bin")
        os.mkdir(sysbin)
        os.symlink(shutil.which("tmux"), os.path.join(sysbin, "tmux"))   # checked: skipUnless
        os.symlink(sys.executable, os.path.join(sysbin, "python3"))
        self.env = {k: os.environ[k] for k in ("LANG", "LC_ALL", "LC_CTYPE", "TMPDIR") if k in os.environ}
        self.env.update(PATH=f"{sysbin}:/usr/bin:/bin:/usr/sbin:/sbin", HOME=self.home,
                        TMUX_TMPDIR=self.tmpdir, TERM="xterm-256color",
                        SESSIONVIEW_ROOT=root, SESSIONVIEW_PYTHON=sys.executable,
                        SESSIONVIEW_FRAME_SOCK=self.frame_sock,
                        SESSIONVIEW_STATE=os.path.join(self.home, ".local", "state", "sessionview"))
        self.tmux_bin = shutil.which("tmux")
        self.pid = self.master = None
        self.closed = False
        self.out = bytearray()

    def tmux(self, *args, sock=None):
        assert "-S" not in args and "default" not in args, args
        return subprocess.run([self.tmux_bin, "-L", sock or self.frame_sock, *args], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def start(self):
        argv = ["sh", os.path.join(self.root, "bin", "sessionview-frame"), "main",
                "--sock", self.inner_sock]
        self.pid, self.master = pty.fork()
        if self.pid == 0:   # the child: a session of its own, on a 160x45 tty
            try:
                fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
                os.chdir(self.home)
                os.execve("/bin/sh", argv, self.env)
            finally:
                os._exit(127)
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        answered = False
        while True:
            try:
                b = os.read(self.master, 65536)
            except OSError:
                return
            if not b:
                return
            self.out.extend(b)
            if not answered and b"Which" in self.out:   # the autostart question: no agent
                answered = True
                os.write(self.master, b"n\r")

    def frame_session(self):
        r = self.tmux("list-sessions", "-F", "#{session_name}")
        return next((s for s in r.stdout.split() if s.startswith("frame-")), None)

    def wait_session(self, timeout=30):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            s = self.frame_session()
            if s:
                return s
            time.sleep(0.05)
        raise AssertionError("the frame session never appeared; pty said: "
                             + self.out[-400:].decode("utf-8", "replace"))

    def side_pane(self, session):
        return self.tmux("show-options", "-v", "-t", session, "@sessionview_side_pane").stdout.strip()

    def settle(self, after_attach=1.5, timeout=15):
        """Sample view.json's width every 0.1 s until AFTER_ATTACH seconds
        after a client is attached. Returns (every width seen, in order,
        deduplicated; the clients list)."""
        seen, attached_at = [], None
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            w = view_width(self.home)
            if not seen or seen[-1] != w:
                seen.append(w)
            clients = self.tmux("list-clients", "-F", "#{client_width}x#{client_height}").stdout.split()
            if clients and attached_at is None:
                attached_at = time.monotonic()
            if attached_at is not None and time.monotonic() - attached_at >= after_attach:
                return seen, clients
            time.sleep(0.1)
        raise AssertionError(f"no client attached to the frame in {timeout}s (widths seen {seen})")

    def close(self):
        # ONLY this open's own: its two private servers, then its own process group.
        # Once: the test closes each open as it goes, and a cleanup closes it again
        # when an assertion stopped the test first.
        if self.closed:
            return
        self.closed = True
        for sock in (self.frame_sock, self.inner_sock):
            self.tmux("kill-server", sock=sock)
        if self.pid:
            try:
                os.killpg(self.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass   # macOS: EPERM when only a zombie leader is left in the group
            for _ in range(40):
                if os.waitpid(self.pid, os.WNOHANG)[0]:
                    break
                time.sleep(0.05)
            else:
                try:
                    os.killpg(self.pid, signal.SIGKILL)
                    os.waitpid(self.pid, 0)
                except (ProcessLookupError, PermissionError, ChildProcessError):
                    pass
        if self.master is not None:
            os.close(self.master)
        shutil.rmtree(self.base, ignore_errors=True)
        shutil.rmtree(self.tmpdir, ignore_errors=True)


@unittest.skipUnless(support.have_tmux(), support.TMUX_SKIP)
class FirstOpenWidth(unittest.TestCase):
    def open(self, root):
        fo = FrameOpen(root)
        self.addCleanup(fo.close)
        fo.start()
        return fo

    def test_first_opens_keep_the_default_width(self):
        """The frame's own split and resize, before a client attaches, are
        not a drag: OPENS first opens, each on a fresh HOME, leave view.json
        without a width (or at the default) in every sample, and the sidebar
        at the default width."""
        copy = tempfile.mkdtemp(prefix="sv-test-fw-root-")
        self.addCleanup(shutil.rmtree, copy, True)
        root = forced_copy(os.path.join(copy, "root"))
        results = []
        for i in range(OPENS):
            fo = self.open(root)
            session = fo.wait_session()
            seen, clients = fo.settle()
            side = fo.side_pane(session)
            pane = fo.tmux("display-message", "-p", "-t", side, "#{pane_width}").stdout.strip()
            results.append({"open": i + 1, "widths_seen": seen, "sidebar": pane, "clients": clients})
            fo.close()
        bad = [r for r in results
               if not set(r["widths_seen"]) <= {None, DEFAULT_WIDTH} or r["sidebar"] != str(DEFAULT_WIDTH)]
        self.assertEqual(bad, [], f"{len(bad)} of {OPENS} first opens remembered a width the user "
                                  f"never chose, or left the sidebar off {DEFAULT_WIDTH}: {results}")

    def test_a_user_drag_is_remembered(self):
        """A border drag (the sidebar pane resized while a client is attached
        and the window stays the same) is still the new width, in view.json."""
        fo = self.open(support.REPO)
        session = fo.wait_session()
        fo.settle()
        side = fo.side_pane(session)
        fo.tmux("resize-pane", "-t", side, "-x", str(DRAG_TO))
        end = time.monotonic() + 10
        while time.monotonic() < end and view_width(fo.home) != DRAG_TO:
            time.sleep(0.1)
        self.assertEqual(view_width(fo.home), DRAG_TO, "the drag was not remembered")
        pane = fo.tmux("display-message", "-p", "-t", side, "#{pane_width}").stdout.strip()
        self.assertEqual(pane, str(DRAG_TO), "the sidebar did not keep the dragged width")


if __name__ == "__main__":
    unittest.main()
