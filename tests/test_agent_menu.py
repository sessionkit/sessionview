"""tmux/agent-menu.conf: with pane_menu on, both right-clicks open the agent
pane menu, and a plain right-click opens it on an agent's pane even when the
program there has mouse mode on (Claude Code does).

What is checked, on private tmux servers only (support.private_tmux: its own
TMUX_TMPDIR and an `sv-test-*` socket, a scratch HOME, `-f /dev/null` so a
stock server is the baseline):

- the bindings (T1): both keys are bound, from ONE menu; the plain key's
  test asks "is this an agent's pane?" before it looks at mouse mode; the conf
  leaves no SESSIONVIEW_* variable behind; every other binding is stock.
- the condition (T2): the plain key's test, READ BACK from list-keys, for
  each kind of pane: an agent's or not, mouse mode on or off, copy mode,
  other modes.
- real clicks (T3): the SGR bytes a terminal sends, written into a pane that
  runs a tmux CLIENT of the server under test, so they take tmux's real
  mouse path. A "mouse-mode" pane runs a program that turns on all-motion +
  SGR mouse mode, as Claude Code does; `cat -v` then shows any click that
  reaches it as ^[[<b;x;yM.

A full click (press + release) closes a display-menu, in stock tmux too, so
a click that should open the menu sends the press only.
"""
import os
import re
import shlex
import time
import unittest

from tests import support

CONF = os.path.join(support.REPO, "tmux", "agent-menu.conf")

#: a pane title carrying an agent address, in each of the two forms
AGENT = "✳ worker.sv-test"
AGENT_NAMED = "✳ helper:12ab34cd"
NOT_AGENT = "zsh"

#: all-motion + SGR mouse mode, the modes Claude Code turns on
MOUSE_PROG = r"printf '\033[?1003h\033[?1006h'; exec cat -v"
PLAIN_PROG = "exec cat -v"

PLAIN, OPTION = "MouseDown3Pane", "M-MouseDown3Pane"
FORWARD = "{ select-pane -t = ; send-keys -M }"


def bound_command(line, key):
    """The command of one `list-keys -T root KEY` line."""
    m = re.match(r"^bind-key\s+(?:-r\s+)?-T root\s+" + re.escape(key) + r"\s+(.*)$", line)
    assert m, line
    return m.group(1)


def split_plain(cmd):
    """(condition, else-branch) of the plain key's bound command:
    if-shell -F -t = "COND" { select-pane -t = ; send-keys -M } { MENU }"""
    m = re.match(r'^if-shell -F -t = "([^"]*)" ' + re.escape(FORWARD) + r" \{ (.*) \}$", cmd)
    assert m, cmd
    return m.group(1), m.group(2)


class Server(unittest.TestCase):
    """A scratch HOME and private tmux servers, each started `-f /dev/null`."""

    def setUp(self):
        support.require_tmux()
        self._scratch = support.scratch_env()
        self.env, self.home = self._scratch.__enter__()
        self._servers = []

    def tearDown(self):
        for cm in reversed(self._servers):
            cm.__exit__(None, None, None)
        self._scratch.__exit__(None, None, None)

    def server(self, tag, *new_session):
        """A fresh private server, started with NEW_SESSION's arguments."""
        cm = support.private_tmux(tag)
        pt = cm.__enter__()
        self._servers.append(cm)
        r = pt.tmux("-f", "/dev/null", "new-session", "-d", *new_session, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return pt

    def t(self, pt, *args):
        """Run one tmux command on PT; fail on a non-zero exit."""
        r = pt.tmux(*args, env=self.env)
        self.assertEqual(r.returncode, 0, f"tmux {' '.join(args)}: {r.stderr}")
        return r.stdout

    def source(self, pt):
        r = pt.tmux("source-file", CONF, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")

    def keys(self, pt, key):
        return self.t(pt, "list-keys", "-T", "root", key).rstrip("\n")

    def wait(self, what, pred, secs=15):
        """Poll PRED until it returns a true value; fail naming WHAT."""
        end = time.time() + secs
        while True:
            got = pred()
            if got:
                return got
            if time.time() > end:
                self.fail(f"timed out waiting for {what}")
            time.sleep(0.1)


class Bindings(Server):
    """T1: what sourcing the conf binds, read back with list-keys."""

    def setUp(self):
        super().setUp()
        self.pt = self.server("menu", "-s", "s", "exec sleep 600")
        self.ref = self.server("ref", "-s", "s", "exec sleep 600")
        self.source(self.pt)

    def test_both_keys_are_bound_to_one_menu(self):
        cond, menu = split_plain(bound_command(self.keys(self.pt, PLAIN), PLAIN))
        option = bound_command(self.keys(self.pt, OPTION), OPTION)
        self.assertTrue(option.startswith("display-menu "), option)
        self.assertIn("Speak →", option)
        self.assertEqual(option, menu, "the Option menu and the plain menu differ")
        # and neither is tmux's own binding any more
        self.assertNotEqual(self.keys(self.pt, OPTION), self.keys(self.ref, OPTION))
        self.assertNotEqual(self.keys(self.pt, PLAIN), self.keys(self.ref, PLAIN))

    def test_the_agent_test_comes_before_mouse_mode(self):
        cond, menu = split_plain(bound_command(self.keys(self.pt, PLAIN), PLAIN))
        m = re.match(r"^#\{\|\|:#\{&&:#\{!:#\{m/r:(.*?),#\{pane_title\}\}\},#\{mouse_any_flag\}\},", cond)
        self.assertTrue(m, f"the condition does not open with the agent test: {cond}")
        self.assertEqual(cond.count("mouse_any_flag"), 1, cond)
        # one definition of an agent pane: every agent item uses the same regex
        regex = m.group(1)
        self.assertEqual(menu.count("#{m/r:" + regex + ",#{pane_title}}"), 5, regex)
        self.assertEqual(menu.count("#{pane_title}}"), 5)
        # the second clause is the stock one: a mode other than copy/view
        self.assertTrue(cond.endswith(",#{&&:#{pane_in_mode},#{?#{m/r:(copy|view)-mode,#{pane_mode}},0,1}}}"), cond)

    def test_nothing_is_left_in_the_environment(self):
        # the conf's two variables are gone; the server's own environment
        # (the scratch env, SESSIONVIEW_PYTHON among it) is a stock server's
        for flags in ("-g", "-gh"):
            out = self.t(self.pt, "show-environment", flags)
            self.assertNotIn("SESSIONVIEW_AGENT_", out, flags)
            names = lambda o: sorted(re.findall(r"^-?(SESSIONVIEW_\w*)", o, re.M))
            self.assertEqual(names(out), names(self.t(self.ref, "show-environment", flags)), flags)
        opts = sorted(re.findall(r"^(@sessionview\w*)", self.t(self.pt, "show-options", "-g"), re.M))
        self.assertEqual(opts, ["@sessionview_agent_menu_bin", "@sessionview_agent_menu_conf"])

    def test_every_other_binding_is_stock(self):
        def tables(pt):
            out = self.t(pt, "list-keys")
            return sorted(set(re.findall(r"^bind-key\s+(?:-r\s+)?-T (\S+)", out, re.M)))

        def rest(pt, table):
            out = self.t(pt, "list-keys", "-T", table).splitlines()
            return [l for l in out if not re.search(r" (M-)?MouseDown3Pane ", l)]

        names = tables(self.ref)
        self.assertEqual(tables(self.pt), names)
        self.assertIn("copy-mode", names)
        for table in names:
            self.assertEqual(rest(self.pt, table), rest(self.ref, table), f"table {table}")

    def test_sourcing_again_changes_nothing(self):
        # every frame launch sources it again
        before = (self.keys(self.pt, PLAIN), self.keys(self.pt, OPTION))
        self.source(self.pt)
        self.assertEqual((self.keys(self.pt, PLAIN), self.keys(self.pt, OPTION)), before)
        self.assertNotIn("SESSIONVIEW_AGENT_", self.t(self.pt, "show-environment", "-gh"))

    def test_a_broken_menu_fails_loudly_and_keeps_both_keys(self):
        # one flag this tmux does not know, inside the menu: the file fails to
        # source, at load and not at the first click, and both keys keep the
        # binding they had
        with open(CONF) as f:
            text = f.read()
        self.assertIn("{ kill-pane }", text)
        bad = os.path.join(self.home, "bad.conf")
        with open(bad, "w") as f:
            f.write(text.replace("{ kill-pane }", "{ kill-pane -Q }"))
        before = (self.keys(self.ref, PLAIN), self.keys(self.ref, OPTION))
        r = self.ref.tmux("source-file", bad, env=self.env)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotEqual(r.stderr, "")
        self.assertEqual((self.keys(self.ref, PLAIN), self.keys(self.ref, OPTION)), before)


class Condition(Server):
    """T2: the plain key's condition, read back from list-keys, evaluated per
    pane with display -p. 1 = the click goes to the program, 0 = the menu."""

    def setUp(self):
        super().setUp()
        self.pt = self.server("cond", "-s", "s", "-x", "120", "-y", "40", "exec sleep 600")
        self.t(self.pt, "set", "-g", "mouse", "on")
        self.source(self.pt)
        cmd = bound_command(self.keys(self.pt, PLAIN), PLAIN)
        self.cond, _menu = split_plain(cmd)

    def pane(self, title, mouse, mode=None):
        """A pane (its own window) titled TITLE, mouse mode on or off, then
        put in MODE (copy, clock or tree); return its id."""
        prog = MOUSE_PROG if mouse else PLAIN_PROG
        p = self.t(self.pt, "new-window", "-d", "-t", "s:", "-P", "-F", "#{pane_id}", prog).strip()
        want = "1" if mouse else "0"
        self.wait(f"mouse_any_flag={want} on {p}",
                  lambda: self.t(self.pt, "display", "-p", "-t", p, "#{mouse_any_flag}").strip() == want)
        self.t(self.pt, "select-pane", "-t", p, "-T", title)
        if mode:
            self.t(self.pt, {"copy": "copy-mode", "clock": "clock-mode", "tree": "choose-tree"}[mode], "-t", p)
            name = {"copy": "copy-mode", "clock": "clock-mode", "tree": "tree-mode"}[mode]
            self.wait(f"{name} on {p}",
                      lambda: self.t(self.pt, "display", "-p", "-t", p, "#{pane_mode}").strip() == name)
        return p

    def forwards(self, p):
        return self.t(self.pt, "display", "-p", "-t", p, self.cond).strip()

    def test_the_matrix(self):
        rows = [
            # title       mouse  mode     expected   why
            (AGENT,       True,  None,    "0"),      # R2: the bug, fixed
            (AGENT_NAMED, True,  None,    "0"),      # the name:id form counts too
            (AGENT,       False, None,    "0"),
            (AGENT,       False, "copy",  "0"),      # R7
            (AGENT,       True,  "copy",  "0"),      # R7 (Q3: the menu, not nothing)
            (AGENT,       False, "clock", "1"),      # Q2: the mode keeps the click
            (AGENT,       False, "tree",  "1"),      # Q2: choose-tree keeps its menu
            (NOT_AGENT,   True,  None,    "1"),      # R4: the program gets it
            (NOT_AGENT,   False, None,    "0"),      # R4: the plain menu
            (NOT_AGENT,   True,  "copy",  "1"),      # as today
            (NOT_AGENT,   False, "copy",  "0"),      # as today
        ]
        for title, mouse, mode, want in rows:
            with self.subTest(title=title, mouse=mouse, mode=mode):
                p = self.pane(title, mouse, mode)
                self.assertEqual(self.t(self.pt, "display", "-p", "-t", p, "#{pane_title}").strip(), title)
                self.assertEqual(self.forwards(p), want)


class Clicks(Server):
    """T3: real clicks, two levels: a terminal server whose pane runs a tmux
    client attached to the inner server, which sourced the conf."""

    W, H = 100, 30
    AT = (20, 10)   # x, y of every click, 1-based: inside the inner pane

    def start(self, title, mouse=True):
        prog = MOUSE_PROG if mouse else PLAIN_PROG
        self.inner = self.server("inner", "-s", "s", "-x", str(self.W), "-y", str(self.H), prog)
        self.t(self.inner, "set", "-g", "mouse", "on")
        self.t(self.inner, "select-pane", "-t", "s:0", "-T", title)
        self.source(self.inner)
        want = "1" if mouse else "0"
        self.wait("the inner program's mouse mode",
                  lambda: self.t(self.inner, "display", "-p", "-t", "s:0", "#{mouse_any_flag}").strip() == want)
        client = (f"unset TMUX TMUX_PANE; TMUX_TMPDIR={shlex.quote(self.inner.tmpdir)} "
                  f"exec tmux -L {shlex.quote(self.inner.sock)} attach -t =s:0")
        self.term = self.server("term", "-s", "t", "-x", str(self.W), "-y", str(self.H), client)
        self.wait("the client to attach", lambda: self.t(self.inner, "list-clients").strip())
        # the client has drawn the inner server's status line
        self.wait("the client to draw", lambda: "[s]" in self.screen())

    def screen(self):
        return self.t(self.term, "capture-pane", "-p", "-t", "t")

    def send(self, button, release=False):
        x, y = self.AT
        seq = f"\x1b[<{button};{x};{y}{'m' if release else 'M'}"
        self.t(self.term, "send-keys", "-t", "t", "-l", seq)

    def program_got(self, screen=None):
        return re.findall(r"\^\[\[<[0-9;]*[Mm]", screen if screen is not None else self.screen())

    def test_plain_on_an_agent_mouse_mode_pane_opens_the_menu(self):
        self.start(AGENT)
        self.send(2)
        screen = self.wait("the agent menu", lambda: (lambda s: "Speak →" in s and s)(self.screen()))
        self.assertIn("Continue →", screen)
        self.assertEqual(self.program_got(screen), [], "the press reached the program")
        # the release closes the menu, and goes nowhere else: a left click
        # sent after it is the first thing the program sees
        self.send(2, release=True)
        self.wait("the menu to close", lambda: "Speak →" not in self.screen())
        self.send(0)
        got = self.wait("the left click", lambda: self.program_got())
        self.assertEqual(got, [f"^[[<0;{self.AT[0]};{self.AT[1]}M"])

    def test_option_on_an_agent_mouse_mode_pane_opens_the_menu(self):
        self.start(AGENT)
        self.send(10)   # right button + Meta: Option + right-click
        screen = self.wait("the agent menu", lambda: (lambda s: "Speak →" in s and s)(self.screen()))
        self.assertEqual(self.program_got(screen), [])

    def test_option_on_a_named_agent_opens_the_menu(self):
        self.start(AGENT_NAMED)
        self.send(10)
        screen = self.wait("the agent menu", lambda: (lambda s: "Speak →" in s and s)(self.screen()))
        self.assertIn("Speak → helper", screen)

    def test_plain_on_a_non_agent_mouse_mode_pane_reaches_the_program(self):
        self.start(NOT_AGENT)
        self.send(2)
        got = self.wait("the right click in the program", lambda: self.program_got())
        self.assertEqual(got, [f"^[[<2;{self.AT[0]};{self.AT[1]}M"])
        self.assertNotIn("Horizontal Split", self.screen())

    def test_plain_on_a_non_agent_pane_without_mouse_mode_opens_the_plain_menu(self):
        self.start(NOT_AGENT, mouse=False)
        self.send(2)
        screen = self.wait("the menu", lambda: (lambda s: "Horizontal Split" in s and s)(self.screen()))
        self.assertNotIn("Speak →", screen)

    def test_left_click_and_wheel_reach_the_program(self):
        self.start(AGENT)
        x, y = self.AT
        self.send(0)
        self.wait("the left click", lambda: f"^[[<0;{x};{y}M" in self.program_got())
        self.send(64)   # wheel up
        got = self.wait("the wheel", lambda: (lambda g: f"^[[<64;{x};{y}M" in g and g)(self.program_got()))
        self.assertNotIn("Speak →", self.screen())
        self.assertEqual(got, [f"^[[<0;{x};{y}M", f"^[[<64;{x};{y}M"])


if __name__ == "__main__":
    unittest.main()
