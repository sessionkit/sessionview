"""A bare sessionview lands in a session the server already has; it makes
`main` only when the server has none.

`sessionview-frame` once defaulted SESSION to `main` and made it when missing,
so on a server that already held a session (the one with the user's assistant
in it) a first `sessionview` put the user on an empty `main` beside it. The
rule now lives in lib/landing.sh: run outside tmux with no SESSION named, the
frame takes the default seat's session, else the most recently attached, else
the newest, and makes `main` only on an empty server.

Everything runs on PRIVATE tmux servers (support.private_tmux: its own
TMUX_TMPDIR, so even tmux's "default" socket is private) in a scratch HOME.
`session` is a shim written here; with no shim, PATH holds tmux and the system
dirs only.

What is proven:
  (a) sv_landing: no server is "none" (exit 1); one session is that session;
      an attached session beats a never-attached newer one; the most recent
      attach (a switch-client counts) wins; with none attached, the newest;
      a name with spaces comes back whole;
  (b) the seat rung: the default seat's session beats a more recently
      attached one; a seat row on ANOTHER server, a dead pane, bad JSON, no
      `session` and no Python each fall through to the next rung;
  (c) the frame, outside tmux, no SESSION, no --sock: an empty server gets
      `main`; a server holding only `work` lands in `work` and gets no
      `main`; an env SESSION is ignored, as before;
  (d) a SESSION argument keeps the old behaviour exactly: that session,
      and the frame makes it when it is missing.
"""
import json
import os
import subprocess
import time
import unittest

from tests import support
from tests.test_frame_hijack import HijackCase, PtyClient, wait_for

FRAME = os.path.join(support.BIN, "sessionview-frame")
LANDING = os.path.join(support.REPO, "lib", "landing.sh")

SESSION_SHIM = """#!/bin/sh
case "$1 $2" in
  "agent default") echo claude;;
  "list --json") cat "$SV_TEST_SESSION_JSON";;
  *) exit 2;;
esac
"""


class LandingCase(HijackCase):
    """HijackCase's private server and pty clients, plus a `session` shim and
    a way to call sv_landing on a server."""

    def setUp(self):
        super().setUp()
        self.pbin = os.path.join(self.home, "pbin")
        self.json = os.path.join(self.home, "session-list.json")
        # a fresh server for the rule, apart from HijackCase's own (which holds A)
        self.sock = self.pt.sock + "-land"

    def t(self, *args):
        return self.tmux(*args, sock=self.sock)

    def new(self, name, *cmd):
        r = self.t("new-session", "-d", "-s", name, "-x", "160", "-y", "40", *(cmd or ("sleep 3600",)))
        self.assertEqual(r.returncode, 0, r.stderr)

    def shim(self, rows):
        path = os.path.join(self.pbin, "session")
        with open(path, "w") as f:
            f.write(SESSION_SHIM)
        os.chmod(path, 0o755)
        with open(self.json, "w") as f:
            f.write(rows if isinstance(rows, str) else json.dumps(rows))

    def pane(self, name):
        return self.t("display-message", "-p", "-t", f"={name}:", "#{pane_id}").stdout.strip()

    def attach(self, name):
        """A pty `tmux attach` client on this server's NAME (HijackCase.client
        is for its own server only)."""
        c = PtyClient(self.sock, name, self.env(TERM="xterm-256color"))
        self.clients.append(c)
        self.assertTrue(wait_for(lambda: c.tty in self.clients_on(sock=self.sock)), f"client on {name} never attached")
        return c

    def landing(self, **extra):
        """(exit code, SV_LANDING) of sv_landing on self.sock."""
        r = subprocess.run(["sh", "-c", '. "$1"; sv_landing "$2"; echo "$?|$SV_LANDING"', "sh", LANDING, self.sock],
                           env=self.env(SV_TEST_SESSION_JSON=self.json, **extra),
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.stderr, "")
        rc, _, name = r.stdout.rstrip("\n").partition("|")
        return int(rc), name

    def sessions(self, sock):
        r = self.tmux("list-sessions", "-F", "#{session_name}", sock=sock)
        return sorted(r.stdout.split("\n")[:-1]) if r.returncode == 0 else []


class RecencyRungs(LandingCase):
    """(a) rungs 2 and 3, and the empty server."""

    def test_no_server_is_none(self):
        self.assertEqual(self.landing(), (1, ""))

    def test_one_session(self):
        self.new("work")
        self.assertEqual(self.landing(), (0, "work"))

    def test_attached_beats_newer_never_attached(self):
        self.new("old")
        self.attach("old")
        time.sleep(1.1)
        self.new("newer")
        self.assertEqual(self.landing(), (0, "old"))

    def test_most_recent_attach_wins_switch_client_counts(self):
        self.new("a")
        self.new("b")
        c = self.attach("a")
        time.sleep(1.1)
        r = self.t("switch-client", "-c", c.tty, "-t", "=b")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.landing(), (0, "b"))

    def test_none_attached_newest(self):
        self.new("first")
        time.sleep(1.1)
        self.new("second")
        self.assertEqual(self.landing(), (0, "second"))

    def test_same_second_tie_is_deterministic(self):
        # Made in one second (or the later one is newer): either way, "a".
        self.new("b")
        self.new("a")
        self.assertEqual(self.landing(), (0, "a"))

    def test_name_with_spaces_whole(self):
        self.new("my project")
        self.assertEqual(self.landing(), (0, "my project"))


class SeatRung(LandingCase):
    """(b) rung 1, and every way it falls through."""

    def setUp(self):
        super().setUp()
        self.new("seat")
        self.new("other")
        self.attach("other")        # the recency rungs would pick "other"

    def rows(self, pane=None, sock=None, agent="claude"):
        return [{"agent": "codex", "tmux_socket": self.sock, "tmux_pane": self.pane("other")},
                {"agent": agent, "tmux_socket": sock or self.sock, "tmux_pane": pane or self.pane("seat")}]

    def test_seat_beats_last_attached(self):
        self.shim(self.rows())
        self.assertEqual(self.landing(), (0, "seat"))

    def test_seat_on_another_server_falls_through(self):
        self.shim(self.rows(sock="some-other-server"))
        self.assertEqual(self.landing(), (0, "other"))

    def test_seat_not_the_default_agent_falls_through(self):
        self.shim(self.rows(agent="codex"))
        self.assertEqual(self.landing(), (0, "other"))

    def test_dead_pane_falls_through(self):
        self.shim(self.rows(pane="%9999"))
        self.assertEqual(self.landing(), (0, "other"))

    def test_seat_outside_tmux_falls_through(self):
        rows = self.rows()
        rows[1]["tmux_pane"] = ""
        rows[1]["tmux_socket"] = ""
        self.shim(rows)
        self.assertEqual(self.landing(), (0, "other"))

    def test_bad_json_falls_through(self):
        self.shim("not json {")
        self.assertEqual(self.landing(), (0, "other"))

    def test_no_session_tool_falls_through(self):
        self.assertFalse(os.path.exists(os.path.join(self.pbin, "session")))
        self.assertEqual(self.landing(), (0, "other"))

    def test_no_python_falls_through(self):
        self.shim(self.rows())
        self.assertEqual(self.landing(SESSIONVIEW_PYTHON=""), (0, "other"))


class FrameLanding(LandingCase):
    """(c) and (d): the frame itself, run outside tmux in a pane of the
    driver server (HijackCase's), attaching on the private `default`."""

    TARGET = "default"

    def frame(self, tag, *args, **env):
        """Start the frame with ARGS outside tmux; return the command its right
        pane runs, once it has one."""
        envs = " ".join(f"{k}='{v}'" for k, v in env.items())
        cmd = f"env -u TMUX -u TMUX_PANE {envs} '{FRAME}' " + " ".join(f"'{a}'" for a in args)
        r = self.tmux("new-session", "-d", "-s", tag, "-x", "160", "-y", "40", cmd)
        self.assertEqual(r.returncode, 0, r.stderr)

        def right():
            r = self.tmux("list-panes", "-a", "-F", "#{pane_start_command}", sock=self.frame_sock)
            rows = [l for l in r.stdout.splitlines() if " attach -t " in l]
            return rows[0] if rows else ""
        got = wait_for(right)
        self.assertTrue(got, f"{tag}: the frame never made its right pane")
        return got

    def test_empty_server_makes_main(self):
        self.assertEqual(self.sessions(self.TARGET), [])
        right = self.frame("bare")
        self.assertIn('attach -t \\"=main\\"', right)
        self.assertEqual(self.sessions(self.TARGET), ["main"])

    def test_work_only_lands_in_work_no_main(self):
        self.tmux("new-session", "-d", "-s", "work", "sleep 3600", sock=self.TARGET)
        right = self.frame("bare")
        self.assertIn('attach -t \\"=work\\"', right)
        self.assertEqual(self.sessions(self.TARGET), ["work"])

    def test_env_session_still_ignored(self):
        self.tmux("new-session", "-d", "-s", "work", "sleep 3600", sock=self.TARGET)
        right = self.frame("envs", SESSION="ghost")
        self.assertIn('attach -t \\"=work\\"', right)
        self.assertEqual(self.sessions(self.TARGET), ["work"])

    def test_named_session_exactly_as_before(self):
        self.tmux("new-session", "-d", "-s", "work", "sleep 3600", sock=self.TARGET)
        self.tmux("new-session", "-d", "-s", "zed", "sleep 3600", sock=self.TARGET)
        right = self.frame("named", "zed")
        self.assertIn('attach -t \\"=zed\\"', right)
        self.assertEqual(self.sessions(self.TARGET), ["work", "zed"])

    def test_named_missing_session_is_made_as_before(self):
        self.tmux("new-session", "-d", "-s", "work", "sleep 3600", sock=self.TARGET)
        right = self.frame("named", "fresh")
        self.assertIn('attach -t \\"=fresh\\"', right)
        self.assertEqual(self.sessions(self.TARGET), ["fresh", "work"])


if __name__ == "__main__":
    unittest.main()
