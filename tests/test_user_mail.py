"""SV-86: the user's own mail (design.md §3, §4, §6 cases 1-8).

bin/sessionview-usermail find-or-creates ONE session on user_mail_socket and
types the user's mail command into it; bin/tmux-sidebar draws the `✉ mail`
row between the brand and the store row, hides that session from the project
rows, and a click runs the tool and then jumps across servers.

Every tmux call is on a private socket (support.private_tmux: `-L sv-test-*`
under a scratch TMUX_TMPDIR). The panes the tool types into run a NON-login
/bin/sh (default-command), so macOS's path_helper never puts a real neomutt
ahead of the shims: a shim's only job is to write one line to a marker file.
"""
import json
import os
import shutil
import sys
import textwrap
import time
import unittest

from tests import support
from tests.test_store_view import ViewBase, project_rows

SHIM = '#!/bin/sh\necho "$(basename "$0") $*" >> {mark}\n'


def quiet_shell(pt, env):
    """Start PT's server under ENV holding one session, `keep`, whose new
    panes are a plain non-login /bin/sh (no profile, no path_helper)."""
    for args in (("new-session", "-d", "-s", "keep"),
                 ("set-option", "-g", "default-shell", "/bin/sh"),
                 ("set-option", "-g", "default-command", "exec /bin/sh")):
        r = pt.tmux(*args, env=env)
        assert r.returncode == 0, r.stderr


class UserMailTool(unittest.TestCase):
    """§6 cases 1-6 and 8: bin/sessionview-usermail on a private server, with
    a PATH that holds only the shims, tmux, python3 and /usr/bin:/bin - no
    real neomutt can be reached from it."""

    def setUp(self):
        if not support.have_tmux():
            self.skipTest(support.TMUX_SKIP)
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self._pt = support.private_tmux("umail")
        self.pt = self._pt.__enter__()
        self.shims = os.path.join(self.home, "shims")
        self.links = os.path.join(self.home, "links")
        os.makedirs(self.shims)
        os.makedirs(self.links)
        for name, target in (("tmux", shutil.which("tmux")), ("python3", sys.executable)):
            os.symlink(target, os.path.join(self.links, name))
        for d in ("/usr/bin", "/bin"):
            for name in ("neomutt", "mutt"):
                if os.path.exists(os.path.join(d, name)):
                    self.skipTest(f"{d}/{name} exists: the no-binary cases cannot be isolated")
        self.mark = os.path.join(self.home, "typed.log")
        self.cfg = os.path.join(self.home, "sv-config.json")
        self.env = self.pt.env(env)
        self.env["PATH"] = os.pathsep.join((self.shims, self.links, "/usr/bin", "/bin"))
        self.env["SESSIONVIEW_CONFIG"] = self.cfg
        self.config()

    def tearDown(self):
        self._pt.__exit__(None, None, None)
        self._scratch.__exit__(None, None, None)

    # -- helpers -----------------------------------------------------------------
    def config(self, **keys):
        """The scratch home layer: user_mail_socket is the private server."""
        with open(self.cfg, "w") as f:
            json.dump(dict({"user_mail_socket": self.pt.sock}, **keys), f)

    def shim(self, name):
        p = os.path.join(self.shims, name)
        with open(p, "w") as f:
            f.write(SHIM.format(mark=self.mark))
        os.chmod(p, 0o755)
        return p

    def usermail(self, *args):
        return support.run("sessionview-usermail", *args, env=self.env)

    def typed(self, want=1, wait=10.0):
        """The marker's lines, once it holds WANT of them (or WAIT runs out)."""
        end = time.monotonic() + wait
        while True:
            try:
                with open(self.mark) as f:
                    lines = f.read().splitlines()
            except FileNotFoundError:
                lines = []
            if len(lines) >= want or time.monotonic() > end:
                return lines
            time.sleep(0.1)

    # -- §6 case 1 ---------------------------------------------------------------
    def test_1_create(self):
        self.shim("neomutt")
        quiet_shell(self.pt, self.env)
        r = self.usermail()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, f"{self.pt.sock}\tmail\n")
        self.assertEqual(sorted(self.pt.sessions()), ["keep", "mail"])
        self.assertEqual([n for _, n, _ in self.pt.windows("mail")], ["mail"])
        cwd = self.pt.tmux("display-message", "-p", "-t", "=mail:mail", "#{pane_current_path}")
        self.assertEqual(os.path.realpath(cwd.stdout.strip()), os.path.realpath(self.home))
        # typed as is: no -R, no -F, no rc of ours - the user's own config (Q2)
        self.assertEqual(self.typed(), ["neomutt "])

    def test_1b_the_command_is_the_users_verbatim(self):
        self.shim("neomutt")
        self.config(user_mail_command="neomutt -F ~/elsewhere -e 'set x'")
        quiet_shell(self.pt, self.env)
        r = self.usermail()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.typed(), [f"neomutt -F {self.home}/elsewhere -e set x"])

    def test_1c_flags_override_the_config(self):
        self.shim("neomutt")
        quiet_shell(self.pt, self.env)
        self.config(user_mail_socket=f"sv-test-never-{os.getpid()}")
        r = self.usermail("--socket", self.pt.sock, "--session", "inbox")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, f"{self.pt.sock}\tinbox\n")
        self.assertEqual(sorted(self.pt.sessions()), ["inbox", "keep"])
        self.assertEqual([n for _, n, _ in self.pt.windows("inbox")], ["mail"])

    # -- §6 case 2 ---------------------------------------------------------------
    def test_2_idempotent(self):
        self.shim("neomutt")
        quiet_shell(self.pt, self.env)
        self.assertEqual(self.usermail().returncode, 0)
        self.assertEqual(self.typed(), ["neomutt "])
        r = self.usermail()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, f"{self.pt.sock}\tmail\n")
        self.assertEqual(sorted(self.pt.sessions()), ["keep", "mail"])
        self.assertEqual([n for _, n, _ in self.pt.windows("mail")], ["mail"])
        time.sleep(1.0)                         # a second typing would have landed by now
        self.assertEqual(self.typed(want=2, wait=0), ["neomutt "], "the command was typed twice")

    # -- §6 case 3 ---------------------------------------------------------------
    def test_3_an_existing_session_is_kept_as_it_is(self):
        self.shim("neomutt")
        quiet_shell(self.pt, self.env)
        self.pt.tmux("new-session", "-d", "-s", "mail", "-n", "other", env=self.env)
        r = self.usermail()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, f"{self.pt.sock}\tmail\n")
        self.assertEqual([n for _, n, _ in self.pt.windows("mail")], ["other"])
        time.sleep(1.0)
        self.assertEqual(self.typed(wait=0), [], "typed into a session it did not make")

    # -- §6 case 4 ---------------------------------------------------------------
    def test_4_mutt_stands_in_for_a_missing_neomutt(self):
        self.shim("mutt")
        quiet_shell(self.pt, self.env)
        r = self.usermail()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([n for _, n, _ in self.pt.windows("mail")], ["mail"])
        self.assertEqual(self.typed(), ["mutt "])

    def test_4b_neither_is_refused_and_nothing_is_made(self):
        quiet_shell(self.pt, self.env)
        r = self.usermail()
        self.assertEqual(r.returncode, 2)
        self.assertIn("no neomutt or mutt on PATH", r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual(self.pt.sessions(), ["keep"])

    def test_4c_another_command_has_no_fallback(self):
        self.shim("mutt")
        self.config(user_mail_command="svt-no-such-mailer")
        quiet_shell(self.pt, self.env)
        r = self.usermail()
        self.assertEqual(r.returncode, 2)
        self.assertIn("no svt-no-such-mailer on PATH", r.stderr)
        self.assertEqual(self.pt.sessions(), ["keep"])

    # -- §6 case 5 ---------------------------------------------------------------
    def test_5_empty_command_is_refused_and_nothing_is_made(self):
        self.shim("neomutt")
        self.config(user_mail_command="")
        quiet_shell(self.pt, self.env)
        r = self.usermail()
        self.assertEqual(r.returncode, 2)
        self.assertIn("user_mail_command is empty", r.stderr)
        self.assertEqual(self.pt.sessions(), ["keep"])
        self.assertEqual(self.typed(wait=0), [])

    # -- §6 case 6 ---------------------------------------------------------------
    def test_6_server_down_is_refused_and_never_started(self):
        self.shim("neomutt")
        sockfile = os.path.join(self.pt.tmpdir, f"tmux-{os.getuid()}", self.pt.sock)
        self.assertFalse(self.pt.alive())
        r = self.usermail()
        self.assertEqual(r.returncode, 2)
        self.assertIn("server down", r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertFalse(self.pt.alive(), "a server was started")
        self.assertFalse(os.path.exists(sockfile), sockfile)

    # -- §6 case 8 ---------------------------------------------------------------
    def test_8_print_touches_no_tmux(self):
        self.shim("neomutt")
        tmux_log = os.path.join(self.home, "tmux-called")
        with open(os.path.join(self.shims, "tmux"), "w") as f:     # first on PATH
            f.write(f'#!/bin/sh\necho "$*" >> {tmux_log}\nexit 1\n')
        os.chmod(os.path.join(self.shims, "tmux"), 0o755)
        r = self.usermail("--print")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"socket={self.pt.sock} session=mail command=neomutt", r.stdout)
        self.assertFalse(os.path.exists(tmux_log), "--print ran tmux")
        self.assertFalse(self.pt.alive())

    def test_usage(self):
        r = self.usermail("--nope")
        self.assertEqual(r.returncode, 1)
        r = self.usermail("--socket")
        self.assertEqual(r.returncode, 1)


class UserMailRow(ViewBase):
    """§6 case 7: the sidebar's `✉ mail` row - where it is drawn, what it
    hides, when it is selected, and what a click does."""

    TAG = "umrow"

    def setUp(self):
        super().setUp()
        self.place("fx-legacy")
        self.cfg = self.env["SESSIONVIEW_CONFIG"]

    def config(self, **keys):
        with open(self.cfg, "w") as f:
            json.dump(dict({"user_mail_socket": self.pt.sock}, **keys), f)

    def test_7_the_row_sits_between_brand_and_store_and_hides_its_session(self):
        self.config()
        self.sessions("mail", "alpha")
        lines = self.once()
        brand = next(i for i, line in enumerate(lines) if "sessionview" in line)
        mail = next(i for i, line in enumerate(lines) if line.strip() == "✉ mail")
        store = next(i for i, line in enumerate(lines) if line.strip() == "fx-legacy ⋯")
        self.assertEqual((mail, store), (brand + 2, brand + 3), lines)
        self.assertEqual(lines[brand + 1].strip(), "", "the air under the brand is kept")
        self.assertEqual(project_rows(lines, "fx-legacy"), ["alpha"], lines)

    def test_7b_only_that_session_on_that_server_is_hidden(self):
        self.config(user_mail_socket=f"sv-test-elsewhere-{os.getpid()}")
        self.sessions("mail", "alpha")
        lines = self.once()
        self.assertIn("✉ mail", [line.strip() for line in lines])
        self.assertEqual(sorted(project_rows(lines, "fx-legacy")), ["alpha", "mail"])

    def test_7c_no_command_no_row_and_the_session_is_a_project_again(self):
        for cmd in ("", "svt-no-such-mailer"):
            with self.subTest(command=cmd):
                self.config(user_mail_command=cmd)
                self.pt.tmux("kill-server")
                self.sessions("mail", "alpha")
                lines = self.once()
                self.assertNotIn("✉ mail", [line.strip() for line in lines])
                self.assertEqual(sorted(project_rows(lines, "fx-legacy")), ["alpha", "mail"])

    def test_7d_selected_while_the_client_is_on_it(self):
        self.config()
        self.sessions("mail", "alpha")
        body = '''
            m.current_session = lambda: CUR
            lines, targets = m.render_base(40)
            i = next(k for k, t in targets.items() if t[0] == "user-mail")
            OUT["sel"] = lines[i].startswith(m.BG_SEL)
            OUT["val"] = targets[i][1]
        '''
        out = self.harness('CUR = "mail"\n' + textwrap.dedent(body))
        self.assertTrue(out["sel"])
        self.assertEqual(out["val"], [self.pt.sock, "mail"])
        self.assertFalse(self.harness('CUR = "alpha"\n' + textwrap.dedent(body))["sel"])

    CLICK = '''
        calls = []
        m.jump = lambda t: calls.append([t[0], list(t[1])])
        _lines, targets = m.render_base(40)
        val = next(t[1] for t in targets.values() if t[0] == "user-mail")
        m.user_mail_open(val)
        OUT.update(jumps=calls, prompt=m.PROMPT)
    '''

    def test_7e_a_click_finds_or_creates_then_jumps(self):
        mark = os.path.join(self.home, "typed.log")
        mailer = os.path.join(self.fx.bin, "svt-mailer")
        with open(mailer, "w") as f:
            f.write(SHIM.format(mark=mark))
        os.chmod(mailer, 0o755)
        self.config(user_mail_command=mailer)       # absolute: no PATH in the pane is trusted
        quiet_shell(self.pt, self.env)
        out = self.harness(self.CLICK)
        self.assertIsNone(out["prompt"], out["prompt"])
        self.assertEqual(out["jumps"], [["xsession", [self.pt.sock, "mail"]]])
        self.assertEqual(sorted(self.pt.sessions()), ["keep", "mail"])
        self.assertEqual([n for _, n, _ in self.pt.windows("mail")], ["mail"])
        out = self.harness(self.CLICK)              # again: found, not made
        self.assertEqual(out["jumps"], [["xsession", [self.pt.sock, "mail"]]])
        self.assertEqual([n for _, n, _ in self.pt.windows("mail")], ["mail"])

    def test_7f_a_refusal_is_a_note_and_nothing_moves(self):
        self.config(user_mail_socket=f"sv-test-down-{os.getpid()}")
        self.sessions("alpha")
        out = self.harness(self.CLICK)
        self.assertEqual(out["jumps"], [])
        self.assertEqual(out["prompt"]["title"], "mail")
        self.assertIn("server down", out["prompt"]["label"])

    def test_7g_xsession_moves_the_view_then_the_client(self):
        other = f"sv-test-other-{os.getpid()}"
        out = self.harness(f'''
            calls = []
            m.apply_look = lambda s: calls.append(["look", m.SOCK, s])
            m.move_client = lambda s, n: calls.append(["move", s, n])
            m.jump(("xsession", ({other!r}, "mail")))
            OUT.update(calls=calls, sock=m.SOCK)
        ''')
        self.assertEqual(out["sock"], other)
        self.assertEqual(out["calls"], [["look", other, "mail"], ["move", other, "mail"]])


if __name__ == "__main__":
    unittest.main()
