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

A drag must also survive the terminal being resized afterwards. The frame
once held two resize hooks (client-attached, client-resized) that put back
the width read at frame START. A height-only resize leaves the frame window's
width alone, so fit() read the hook's resize as a drag and remembered the
frame-start width over the user's. fit() is now the one writer of the
sidebar width; the resize tests below drive the pty's size and hold it to
that.
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


SIDEBAR_IMPORT = "import json, os, re, select, shlex, shutil, signal, subprocess, sys, termios, threading, time, tomllib, tty, unicodedata"


def held_copy(dst, hold):
    """Copy the checkout to DST with the sidebar held, before any of its
    Python runs, for as long as the file HOLD exists. That is a slow first
    render, made certain: no fit() runs before the attach, or before a drag
    made while it is held. Returns DST. Fails the test if the anchor line
    is gone."""
    shutil.copytree(support.REPO, dst,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"))
    sb = os.path.join(dst, "bin", "tmux-sidebar")
    with open(sb) as f:
        s = f.read()
    if s.count(SIDEBAR_IMPORT + "\n") != 1:
        raise AssertionError("the sidebar's import line moved: update held_copy")
    gate = f"import os as _o, time as _t\nwhile _o.path.exists({hold!r}):\n    _t.sleep(0.05)\n"
    with open(sb, "w") as f:
        f.write(s.replace(SIDEBAR_IMPORT + "\n", gate + SIDEBAR_IMPORT + "\n"))
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

    def resize(self, cols, rows, timeout=10):
        """Set the pty to COLS x ROWS (the kernel sends the client SIGWINCH)
        and wait until the frame's client reports that size."""
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        want, end = f"{cols}x{rows}", time.monotonic() + timeout
        while time.monotonic() < end:
            if want in self.tmux("list-clients", "-F", "#{client_width}x#{client_height}").stdout.split():
                return
            time.sleep(0.05)
        raise AssertionError(f"the frame's client never reached {want}")

    def watch(self, side, seconds=1.5):
        """Sample (sidebar pane width, view.json width) every 0.1 s for
        SECONDS. Returns every pair seen, in order, deduplicated."""
        seen, end = [], time.monotonic() + seconds
        while time.monotonic() < end:
            pair = (self.tmux("display-message", "-p", "-t", side, "#{pane_width}").stdout.strip(),
                    view_width(self.home))
            if not seen or seen[-1] != pair:
                seen.append(pair)
            time.sleep(0.1)
        return seen

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

    def drag(self, fo, side):
        """Drag the border to DRAG_TO and wait until it is remembered."""
        fo.tmux("resize-pane", "-t", side, "-x", str(DRAG_TO))
        end = time.monotonic() + 10
        while time.monotonic() < end and view_width(fo.home) != DRAG_TO:
            time.sleep(0.1)
        self.assertEqual(view_width(fo.home), DRAG_TO, "the drag was not remembered")

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
        self.drag(fo, side)
        pane = fo.tmux("display-message", "-p", "-t", side, "#{pane_width}").stdout.strip()
        self.assertEqual(pane, str(DRAG_TO), "the sidebar did not keep the dragged width")

    def test_a_height_only_resize_keeps_the_drag(self):
        """After a drag, a terminal resize that changes only the HEIGHT
        leaves the sidebar, and view.json, at the dragged width. The frame's
        old client-resized hook put the frame-start width back here, and
        fit() remembered it as a drag (SV-195)."""
        fo = self.open(support.REPO)
        session = fo.wait_session()
        fo.settle()
        side = fo.side_pane(session)
        self.drag(fo, side)
        want = (str(DRAG_TO), DRAG_TO)
        for rows in (30, ROWS):
            fo.resize(COLS, rows)
            seen = fo.watch(side)
            self.assertEqual(seen, [want], f"after the height went to {rows}, the sidebar and "
                                           f"view.json were not held at {DRAG_TO}: {seen}")

    def test_a_width_resize_keeps_the_drag(self):
        """After a drag, terminal WIDTH changes put the dragged width back:
        fit() alone holds it, with no hook to help, and remembers nothing
        new."""
        fo = self.open(support.REPO)
        session = fo.wait_session()
        fo.settle()
        side = fo.side_pane(session)
        self.drag(fo, side)
        for cols in (120, COLS):
            fo.resize(cols, ROWS)
            seen = fo.watch(side)
            self.assertEqual(seen[-1], (str(DRAG_TO), DRAG_TO),
                             f"after the width went to {cols}, the sidebar and view.json "
                             f"did not settle at {DRAG_TO}: {seen}")
            self.assertEqual({v for _, v in seen}, {DRAG_TO},
                             f"after the width went to {cols}, view.json left {DRAG_TO}: {seen}")

    def test_a_slow_first_render_shows_the_wish_and_keeps_an_early_drag(self):
        """The sidebar's first render is slow (held here until a file is
        removed), so no fit() runs before the client attaches or before the
        drag. Right after the attach the frame's window is the terminal's
        width and the sidebar pane is the wish: the window was once born 200
        wide, the attach scaled the pane to 14, and it stayed there until the
        sidebar drew. A drag made in that time is kept when the sidebar
        starts: it was once put back, because the first fit() had nothing to
        judge it against, or a window width from before the attach."""
        copy = tempfile.mkdtemp(prefix="sv-test-fw-root-")
        self.addCleanup(shutil.rmtree, copy, True)
        hold = os.path.join(copy, "hold")
        open(hold, "w").close()
        self.addCleanup(lambda: os.path.exists(hold) and os.remove(hold))
        fo = self.open(held_copy(os.path.join(copy, "root"), hold))
        session = fo.wait_session()
        end = time.monotonic() + 30
        while time.monotonic() < end and not fo.tmux("list-clients").stdout.strip():
            time.sleep(0.05)
        self.assertTrue(fo.tmux("list-clients").stdout.strip(), "no client attached")
        side = fo.side_pane(session)
        seen, end = [], time.monotonic() + 1.0
        while time.monotonic() < end:
            pair = fo.tmux("display-message", "-p", "-t", side,
                           "#{window_width} #{pane_width}").stdout.strip()
            if not seen or seen[-1] != pair:
                seen.append(pair)
            time.sleep(0.1)
        self.assertEqual(seen, [f"{COLS} {DEFAULT_WIDTH}"],
                         "after the attach, with no sidebar render, the window was not the "
                         f"terminal's width or the sidebar not {DEFAULT_WIDTH}: {seen}")
        fo.tmux("resize-pane", "-t", side, "-x", str(DRAG_TO))
        time.sleep(0.3)
        os.remove(hold)
        end = time.monotonic() + 15
        while time.monotonic() < end and view_width(fo.home) != DRAG_TO:
            time.sleep(0.1)
        seen = fo.watch(side)
        self.assertEqual(seen, [(str(DRAG_TO), DRAG_TO)],
                         f"a drag made before the sidebar's first render was not kept: {seen}")


if __name__ == "__main__":
    unittest.main()
