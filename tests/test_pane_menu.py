"""The frame's own tmux server, with pane_menu on: an Option + right-click on
the pane that holds your tmux client goes through to it (lib/pane-menu.sh),
and every other frame pane keeps the binding the frame's server had.

Everything runs on PRIVATE tmux servers (support.private_tmux: its own
TMUX_TMPDIR and an `sv-test-*` socket) in a scratch HOME.

What is proven:
  (T4) sv_frame_option_forward, sourced in `sh` as the frame does: it wraps
       the stock binding, and the else-branch is byte-identical to it; every
       other binding, in every table, is still stock; a second call changes
       nothing; a key with no binding gets the else-branch `send-keys -M`
       (what tmux does with an unbound mouse key); a user's own binding is
       kept, a command sequence and a multi-line block included, and a `\\;`
       inside a quoted string survives; `-r` is kept.
  (T5) the real frame, launched outside tmux in a pane of a driver server:
       with pane_menu false both right-click keys stay at a baseline server's
       on both servers; with it true the inner server has both sessionview
       bindings and the frame's server has the wrapper.
"""
import os
import re
import subprocess
import unittest

from tests import support
from tests.test_frame_hijack import HijackCase, wait_for

LIB = os.path.join(support.REPO, "lib", "pane-menu.sh")
FRAME = os.path.join(support.BIN, "sessionview-frame")

OPTION, PLAIN = "M-MouseDown3Pane", "MouseDown3Pane"
#: how list-keys prints the wrapper's pass-through
WRAP = ('if-shell -F -t = "#{==:#{pane_current_command},tmux}" '
        '{ select-pane -t = ; send-keys -M } ')


def command_of(line, key=OPTION):
    """(flags, command) of one `list-keys -T root KEY` line."""
    m = re.match(r"^bind-key\s+((?:-r\s+)?)-T root\s+" + re.escape(key) + r" (.*)$", line)
    assert m, line
    return m.group(1).strip(), m.group(2)


def else_branch(cmd):
    """The else-branch of the wrapper, as list-keys prints it."""
    assert cmd.startswith(WRAP + "{ ") and cmd.endswith(" }"), cmd
    return cmd[len(WRAP) + 2:-2]


class Helper(unittest.TestCase):
    """T4: the helper on one private server, started -f /dev/null so stock is
    the baseline, with a second stock server to compare against."""

    def setUp(self):
        support.require_tmux()
        self._scratch = support.scratch_env()
        self.env, self.home = self._scratch.__enter__()
        self.addCleanup(self._scratch.__exit__, None, None, None)
        self.pt = self._server("frame")
        self.ref = self._server("ref")

    def _server(self, tag):
        cm = support.private_tmux(tag)
        pt = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        r = pt.tmux("-f", "/dev/null", "new-session", "-d", "-s", "f", "exec sleep 600", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return pt

    def t(self, pt, *args):
        r = pt.tmux(*args, env=self.env)
        self.assertEqual(r.returncode, 0, f"tmux {' '.join(args)}: {r.stderr}")
        return r.stdout

    def key(self, pt=None, key=OPTION):
        return self.t(pt or self.pt, "list-keys", "-T", "root", key).rstrip("\n")

    def forward(self):
        """sv_frame_option_forward on the server, from `sh`, as the frame
        sources it (TMUX_BIN unset: the tmux on PATH)."""
        r = subprocess.run(["sh", "-c", '. "$1"; sv_frame_option_forward "$2"', "sh", LIB, self.pt.sock],
                           env=self.pt.env(self.env), capture_output=True, text=True, timeout=30)
        return r

    def user_binding(self, text):
        """Source TEXT, a user's ~/.tmux.conf line, into the server; return
        the binding as list-keys prints it."""
        conf = os.path.join(self.home, "user.conf")
        with open(conf, "w") as f:
            f.write(text + "\n")
        self.t(self.pt, "source-file", conf)
        return self.key()

    def assertWraps(self, before):
        r = self.forward()
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        flags, cmd = command_of(self.key())
        self.assertEqual(flags, command_of(before)[0])
        return else_branch(cmd)

    def test_stock_is_wrapped_and_kept_byte_for_byte(self):
        before = self.key()
        self.assertEqual(before, self.key(self.ref))
        self.assertIn("display-menu", before)
        got = self.assertWraps(before)
        self.assertEqual(got, command_of(before)[1])

    def test_every_other_binding_is_stock(self):
        self.assertEqual(self.forward().returncode, 0)

        def tables(pt):
            return sorted(set(re.findall(r"^bind-key\s+(?:-r\s+)?-T (\S+)", self.t(pt, "list-keys"), re.M)))

        def rest(pt, table):
            return [l for l in self.t(pt, "list-keys", "-T", table).splitlines()
                    if not re.search(r" -T root\s+M-MouseDown3Pane ", l)]

        names = tables(self.ref)
        self.assertEqual(tables(self.pt), names)
        for table in names:
            self.assertEqual(rest(self.pt, table), rest(self.ref, table), f"table {table}")
        self.assertNotEqual(self.key(), self.key(self.ref))

    def test_a_second_call_changes_nothing(self):
        self.assertEqual(self.forward().returncode, 0)
        once = self.key()
        r = self.forward()
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(self.key(), once)
        self.assertEqual(once.count("pane_current_command"), 1)

    def test_a_key_with_no_binding_still_sends_the_click(self):
        self.t(self.pt, "unbind-key", "-T", "root", OPTION)
        self.assertNotEqual(self.pt.tmux("list-keys", "-T", "root", OPTION, env=self.env).returncode, 0)
        r = self.forward()
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        flags, cmd = command_of(self.key())
        self.assertEqual(flags, "")
        self.assertEqual(else_branch(cmd), "send-keys -M")
        self.assertEqual(cmd, WRAP + "{ send-keys -M }")

    def test_a_users_own_binding_is_kept(self):
        before = self.user_binding("bind-key -n M-MouseDown3Pane display-message 'mine'")
        self.assertEqual(self.assertWraps(before), command_of(before)[1])

    def test_a_users_command_sequence_wraps(self):
        before = self.user_binding("bind-key -n M-MouseDown3Pane { display-message one ; set -g @sv_t 2 }")
        printed = command_of(before)[1]
        self.assertIn(" \\; ", printed)
        self.assertEqual(self.assertWraps(before), printed.replace(" \\; ", " ; "))

    def test_a_users_multi_line_block_wraps(self):
        before = self.user_binding("bind-key -n M-MouseDown3Pane {\n  display-message one\n"
                                   "  set -g @sv_t 2\n  set -g @sv_u 3\n}")
        printed = command_of(before)[1]
        self.assertEqual(printed.count(" \\; "), 2, printed)
        self.assertEqual(self.assertWraps(before),
                         "display-message one ; set-option -g @sv_t 2 ; set-option -g @sv_u 3")

    def test_a_quoted_backslash_semicolon_survives(self):
        before = self.user_binding("bind-key -n M-MouseDown3Pane { display-message 'a\\;b' ; set -g @sv_t 2 }")
        printed = command_of(before)[1]
        self.assertIn("\\\\;", printed)
        got = self.assertWraps(before)
        self.assertEqual(got, printed.replace(" \\; ", " ; "))
        self.assertIn("\\\\;", got)
        self.assertEqual(got.count(" ; "), 1, got)

    def test_repeat_flag_is_kept(self):
        before = self.user_binding("bind-key -r -n M-MouseDown3Pane display-message mine")
        self.assertEqual(command_of(before)[0], "-r")
        self.assertEqual(self.assertWraps(before), "display-message mine")


class FrameLaunch(HijackCase):
    """T5: the real frame, outside tmux, in a pane of the driver server, with
    a private inner server and a private frame server, in a scratch HOME (no
    ~/.tmux.conf, so tmux's own bindings are the baseline)."""

    def setUp(self):
        super().setUp()
        self.inner = self.pt.sock + "-inner"
        self.base_sock = self.pt.sock + "-base"
        # a baseline started the way the frame starts both its servers: no -f
        r = self.tmux("new-session", "-d", "-s", "b", "sleep 3600", sock=self.base_sock)
        self.assertEqual(r.returncode, 0, r.stderr)

    def keys(self, sock):
        out = {}
        for key in (PLAIN, OPTION):
            r = self.tmux("list-keys", "-T", "root", key, sock=sock)
            self.assertEqual(r.returncode, 0, r.stderr)
            out[key] = r.stdout.rstrip("\n")
        return out

    def launch(self, pane_menu):
        r = support.run("sessionview-config", "set", "pane_menu", pane_menu, env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        cmd = f"env -u TMUX -u TMUX_PANE '{FRAME}' main --sock '{self.inner}'"
        r = self.tmux("new-session", "-d", "-s", "fr", "-x", "160", "-y", "40", cmd)
        self.assertEqual(r.returncode, 0, r.stderr)

        def right():
            r = self.tmux("list-panes", "-a", "-F", "#{pane_start_command}", sock=self.frame_sock)
            return [l for l in r.stdout.splitlines() if " attach -t " in l]
        self.assertTrue(wait_for(right), "the frame never made its client pane")

    def test_off_leaves_both_servers_at_baseline(self):
        self.launch("false")
        base = self.keys(self.base_sock)
        self.assertIn("display-menu", base[OPTION])
        self.assertEqual(self.keys(self.frame_sock), base)
        self.assertEqual(self.keys(self.inner), base)

    def test_on_binds_the_inner_menu_and_the_frame_wrapper(self):
        self.launch("true")
        base = self.keys(self.base_sock)
        inner = self.keys(self.inner)
        for key in (PLAIN, OPTION):
            self.assertIn("Speak →", inner[key], key)
            self.assertNotEqual(inner[key], base[key], key)
        frame = self.keys(self.frame_sock)
        self.assertEqual(frame[PLAIN], base[PLAIN])
        flags, cmd = command_of(frame[OPTION])
        self.assertEqual(else_branch(cmd), command_of(base[OPTION])[1])


if __name__ == "__main__":
    unittest.main()
