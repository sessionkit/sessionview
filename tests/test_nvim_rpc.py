"""skills/neovim/scripts: every move is a --remote-expr; no keys are sent.

Keys sent over the socket land in nvim's input stream between the user's own
keystrokes. Mid-word in insert mode, a "<C-\\><C-n>:e FILE<CR>" ended insert
mode, hid the user's modified buffer, and the rest of the word ran as
normal-mode commands in the file just opened. So nvim-open asks first (mode,
the current buffer, the target buffer) and acts in the same expression, and
the other moves (look, modified, reload, read, the tree) send no keys at all.

Every nvim here is a throwaway: `nvim --headless --clean -i NONE --listen`
on a short socket in a scratch HOME, with the user's options (hidden,
autowrite, autoread, confirm). Nothing reads $NVIM or touches a real socket.
The test plays the user with --remote-send on that throwaway.
"""
import glob
import os
import shutil
import subprocess
import time
import unittest

from tests import support

SKILL = os.path.join(support.REPO, "skills", "neovim")
SCRIPTS = os.path.join(SKILL, "scripts")

NVIM_SKIP = "SKIPPED: needs nvim, which is not on PATH (brew install neovim)"


def script(name):
    return os.path.join(SCRIPTS, name)


class Nvim:
    """A throwaway headless nvim listening on a short socket under HOME."""

    def __init__(self, env, home):
        self.env = dict(env)
        for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
            self.env[var] = os.path.join(home, var.lower())
            os.makedirs(self.env[var], exist_ok=True)
        self.dir = home
        self.sock = os.path.join(home, "s")   # a unix socket path is capped at ~104 bytes
        self.proc = subprocess.Popen(
            ["nvim", "--headless", "--clean", "-i", "NONE", "--listen", self.sock,
             "-c", "set hidden autowrite autoread confirm"],
            env=self.env, cwd=home, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if os.path.exists(self.sock) and self._expr("1").returncode == 0:
                return
            time.sleep(0.1)
        self.stop()
        raise RuntimeError("throwaway nvim did not listen on " + self.sock)

    def _expr(self, expr):
        return subprocess.run(["nvim", "--server", self.sock, "--remote-expr", expr],
                              env=self.env, capture_output=True, text=True, timeout=30)

    def expr(self, expr):
        r = self._expr(expr)
        if r.returncode != 0:
            raise AssertionError("remote-expr %r failed: %s" % (expr, r.stderr))
        return r.stdout

    def type(self, keys):
        """Play the user typing (this nvim is a throwaway)."""
        r = subprocess.run(["nvim", "--server", self.sock, "--remote-send", keys],
                           env=self.env, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise AssertionError("remote-send failed: " + r.stderr)

    def wait(self, expr, want, timeout=15):
        deadline = time.monotonic() + timeout
        got = None
        while time.monotonic() < deadline:
            got = self.expr(expr)
            if got == want:
                return
            time.sleep(0.05)
        raise AssertionError("%r: want %r, got %r" % (expr, want, got))

    def file(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def edit(self, path):
        """Make PATH the current buffer (setup, not the code under test)."""
        self.expr("execute('edit ' . fnameescape('%s'))" % vstr(path))

    def load(self, path):
        """Load PATH into a buffer without showing it; returns its number."""
        self.expr("execute('badd ' . fnameescape('%s'))" % vstr(path))
        n = self.expr("bufnr('%s')" % vstr(path))
        self.expr("bufload(%s)" % n)
        return n

    def current(self):
        return os.path.realpath(self.expr('expand("%:p")'))

    def run(self, name, *args):
        return subprocess.run(["sh", script(name), self.sock, *args], env=self.env,
                              capture_output=True, text=True, timeout=60, cwd=self.dir)

    def stop(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(timeout=30)


def vstr(s):
    """S as the inside of a Vim single-quoted string."""
    return s.replace("'", "''")


class RpcCase(unittest.TestCase):
    def setUp(self):
        if shutil.which("nvim") is None:
            self.skipTest(NVIM_SKIP)
        cm = support.scratch_env()
        env, home = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self.nv = Nvim(env, home)
        self.addCleanup(self.nv.stop)

    def one_line(self, r):
        lines = r.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, "want one clear line, got: %r" % r.stderr)
        return lines[0]


class OpenLeavesTheUserAlone(RpcCase):
    """nvim-open checks mode and both buffers, in the expression that acts."""

    def test_user_typing_mid_word_is_left_alone(self):
        nv = self.nv
        mine = nv.file("mine.txt", "")
        other = nv.file("other.txt", "one two three\n")
        nv.edit(mine)
        nv.type("ione sen")
        nv.wait("mode(1) . getline(1)", "ione sen")
        r = nv.run("nvim-open", other)
        self.assertNotEqual(r.returncode, 0, "nvim-open acted while the user was typing")
        self.assertIn("insert", self.one_line(r))
        self.assertEqual(nv.expr("mode(1)"), "i")
        self.assertEqual(nv.current(), os.path.realpath(mine))
        nv.type("tence<Esc>")
        nv.wait("mode(1)", "n")
        self.assertEqual(nv.expr("getline(1)"), "one sentence")
        self.assertEqual(nv.current(), os.path.realpath(mine))
        with open(other, encoding="utf-8") as f:
            self.assertEqual(f.read(), "one two three\n")
        n = nv.expr("bufnr('%s')" % vstr(other))
        if n != "-1":
            self.assertEqual(nv.expr("join(getbufline(%s, 1, '$'), '|')" % n), "one two three")

    def test_modified_current_buffer_is_left_alone(self):
        nv = self.nv
        mine = nv.file("mine.txt", "")
        other = nv.file("other.txt", "x\n")
        nv.edit(mine)
        nv.type("ihalf<Esc>")
        nv.wait("mode(1) . &modified", "n1")
        r = nv.run("nvim-open", other)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unsaved", self.one_line(r))
        self.assertEqual(nv.current(), os.path.realpath(mine))
        self.assertEqual(nv.expr("&modified . getline(1)"), "1half")

    def test_modified_target_buffer_is_left_alone(self):
        nv = self.nv
        mine = nv.file("mine.txt", "")
        other = nv.file("other.txt", "disk\n")
        nv.edit(mine)
        n = nv.load(other)
        nv.expr("setbufline(%s, 1, 'unsaved')" % n)
        self.assertEqual(nv.expr("getbufinfo(%s)[0].changed" % n), "1")
        r = nv.run("nvim-open", other)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unsaved", self.one_line(r))
        self.assertEqual(nv.current(), os.path.realpath(mine))
        self.assertEqual(nv.expr("getbufline(%s, 1)[0]" % n), "unsaved")

    def test_clean_open_jumps_to_the_line_with_no_mode_change(self):
        nv = self.nv
        mine = nv.file("mine.txt", "a\n")
        other = nv.file("other.txt", "1\n2\n3\n")
        nv.edit(mine)
        r = nv.run("nvim-open", other, "+2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(nv.current(), os.path.realpath(other))
        self.assertEqual(nv.expr("mode(1) . line('.')"), "n2")
        self.assertTrue(r.stdout.strip().endswith(":2"), r.stdout)

    def test_a_path_with_a_space_a_quote_and_a_lt(self):
        nv = self.nv
        nv.edit(nv.file("mine.txt", ""))
        odd = nv.file("it's <b> c.txt", "odd\n")
        r = nv.run("nvim-open", odd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(nv.current(), os.path.realpath(odd))
        self.assertEqual(nv.expr("mode(1) . getline(1)"), "nodd")

    def test_a_relative_path_is_from_the_callers_directory(self):
        nv = self.nv
        nv.edit(nv.file("mine.txt", ""))
        other = nv.file("other.txt", "rel\n")
        r = nv.run("nvim-open", "other.txt")     # cwd is the scratch dir
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(nv.current(), os.path.realpath(other))


class Modified(RpcCase):
    """nvim-modified SOCK FILE: exit 0 modified, 1 clean, 3 not open, 2 usage."""

    def test_codes(self):
        nv = self.nv
        mine = nv.file("mine.txt", "")
        other = nv.file("other.txt", "x\n")
        absent = nv.file("absent.txt", "y\n")
        nv.edit(mine)
        n = nv.load(other)
        self.assertEqual(nv.run("nvim-modified", other).returncode, 1)
        nv.expr("setbufline(%s, 1, 'changed')" % n)      # not the current buffer
        self.assertEqual(nv.run("nvim-modified", other).returncode, 0)
        self.assertEqual(nv.run("nvim-modified", mine).returncode, 1)
        self.assertEqual(nv.run("nvim-modified", absent).returncode, 3)
        self.assertEqual(nv.run("nvim-modified").returncode, 2)
        self.assertEqual(nv.expr("mode(1)"), "n")
        self.assertEqual(nv.current(), os.path.realpath(mine))

    def test_no_socket_is_2(self):
        r = subprocess.run(["sh", script("nvim-modified"), os.path.join(self.nv.dir, "none"),
                            "/x"], env=self.nv.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2, r.stderr)


class Reload(RpcCase):
    def test_clean_buffer_reloads_after_an_edit_on_disk(self):
        nv = self.nv
        nv.edit(nv.file("mine.txt", ""))
        other = nv.file("other.txt", "old\n")
        n = nv.load(other)
        time.sleep(1.1)                     # a new mtime, whatever the fs resolution
        nv.file("other.txt", "new\n")
        r = nv.run("nvim-reload", other)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(nv.expr("getbufline(%s, 1)[0]" % n), "new")

    def test_modified_buffer_is_refused_and_keeps_its_text(self):
        nv = self.nv
        nv.edit(nv.file("mine.txt", ""))
        other = nv.file("other.txt", "old\n")
        n = nv.load(other)
        nv.expr("setbufline(%s, 1, 'unsaved')" % n)
        time.sleep(1.1)
        nv.file("other.txt", "agent\n")
        r = nv.run("nvim-reload", other)
        self.assertNotEqual(r.returncode, 0)
        line = self.one_line(r)
        self.assertIn("unsaved", line)
        self.assertIn("tell the user", line)
        self.assertEqual(nv.expr("getbufline(%s, 1)[0]" % n), "unsaved")

    def test_not_open_is_3(self):
        nv = self.nv
        r = nv.run("nvim-reload", nv.file("absent.txt", "z\n"))
        self.assertEqual(r.returncode, 3)


class Read(RpcCase):
    def test_returns_the_unsaved_text(self):
        nv = self.nv
        nv.edit(nv.file("mine.txt", ""))
        other = nv.file("other.txt", "disk\nsecond\n")
        n = nv.load(other)
        nv.expr("setbufline(%s, 1, 'unsaved')" % n)
        r = nv.run("nvim-read", other)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "unsaved\nsecond\n")

    def test_not_open_is_3_with_a_line(self):
        nv = self.nv
        r = nv.run("nvim-read", nv.file("absent.txt", "z\n"))
        self.assertEqual(r.returncode, 3)
        self.assertIn("not open", self.one_line(r))


class Look(RpcCase):
    def test_fields(self):
        nv = self.nv
        path = nv.file("look me.txt", "ab\ncdef\n")
        nv.edit(path)
        nv.expr("cursor(2, 3)")
        r = nv.run("nvim-look")
        self.assertEqual(r.returncode, 0, r.stderr)
        mode, modified, line, col, name = r.stdout.rstrip("\n").split("\t", 4)
        self.assertEqual((mode, modified, line, col), ("n", "0", "2", "3"))
        self.assertEqual(os.path.realpath(name), os.path.realpath(path))
        nv.type("ix")
        nv.wait("mode(1)", "i")
        mode, modified = nv.run("nvim-look").stdout.split("\t")[:2]
        self.assertEqual((mode, modified), ("i", "1"))
        self.assertEqual(nv.expr("mode(1)"), "i")


class Tree(RpcCase):
    """Neo-tree is not in --clean: a stub :Neotree records what it was asked."""

    STUB = "execute('command! -nargs=1 Neotree let g:neotree = <q-args>')"

    def test_refused_while_the_user_types(self):
        nv = self.nv
        nv.expr(self.STUB)
        nv.edit(nv.file("mine.txt", ""))
        nv.type("iab")
        nv.wait("mode(1) . getline(1)", "iab")
        for act in ("show", "toggle"):
            with self.subTest(act=act):
                r = nv.run("nvim-tree", act)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("insert", self.one_line(r))
                self.assertEqual(nv.expr("mode(1) . getline(1)"), "iab")
                self.assertEqual(nv.expr("get(g:, 'neotree', '-')"), "-")

    def test_runs_the_command_with_no_keys(self):
        nv = self.nv
        nv.expr(self.STUB)
        nv.edit(nv.file("mine.txt", ""))
        r = nv.run("nvim-tree", "show")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(nv.expr("g:neotree . mode(1)"), "shown")
        r = nv.run("nvim-tree", "toggle")
        self.assertEqual(nv.expr("g:neotree"), "toggle")
        self.assertEqual(r.stdout.strip(), "hidden")   # the stub opens no tree window

    def test_a_missing_neotree_is_an_error_not_keys(self):
        nv = self.nv
        nv.edit(nv.file("mine.txt", ""))
        r = nv.run("nvim-tree", "show")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(nv.expr("mode(1) . getline(1)"), "n")


class Exit2(unittest.TestCase):
    """SKILL.md: "Exit 2 from any of them: usage, or no nvim listening on
    SOCK." Exit 1 means something else in these tools (status hidden, a
    refusal, a clean buffer), so usage must never exit 1. Each case says
    one line on stderr, from the script or from nvim."""

    USAGE = (
        ("nvim-look",),
        ("nvim-modified",), ("nvim-modified", "SOCK"),
        ("nvim-open",), ("nvim-open", "SOCK"), ("nvim-open", "SOCK", "/x", "+ab"),
        ("nvim-read",), ("nvim-read", "SOCK"),
        ("nvim-reload",), ("nvim-reload", "SOCK"),
        ("nvim-tree",), ("nvim-tree", "SOCK", "bogus"),
        ("nvim-sock",), ("nvim-sock", "-L"),
    )

    NO_SERVER = (
        ("nvim-look",),
        ("nvim-modified", "/x"),
        ("nvim-open", "/x"),
        ("nvim-read", "/x"),
        ("nvim-reload", "/x"),
        ("nvim-tree",), ("nvim-tree", "status"), ("nvim-tree", "show"),
        ("nvim-tree", "hide"), ("nvim-tree", "toggle"),
    )

    def setUp(self):
        cm = support.scratch_env()
        self.env, self.home = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self.none = os.path.join(self.home, "none")   # no nvim listens here

    def sh(self, name, *args, env=None):
        return subprocess.run(["sh", script(name), *args], env=env or self.env,
                              capture_output=True, text=True, timeout=30, cwd=self.home)

    def assert_2(self, r):
        self.assertEqual(r.returncode, 2, r.stderr)
        lines = r.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, "want one line on stderr, got: %r" % r.stderr)
        return lines[0]

    def test_usage_is_2_with_a_usage_line(self):
        for case in self.USAGE:
            name, args = case[0], [self.none if a == "SOCK" else a for a in case[1:]]
            with self.subTest(case=" ".join(case)):
                line = self.assert_2(self.sh(name, *args))
                want = "nvim-open:" if "+ab" in args else "usage: " + name
                self.assertTrue(line.startswith(want), line)

    def test_no_nvim_on_sock_is_2(self):
        if shutil.which("nvim") is None:
            self.skipTest(NVIM_SKIP)
        for case in self.NO_SERVER:
            with self.subTest(case=" ".join(case)):
                self.assert_2(self.sh(case[0], self.none, *case[1:]))

    def test_nvim_sock_with_no_tmux_server_is_2(self):
        support.require_tmux()
        with support.private_tmux("nvimsock") as t:   # never started: no server
            r = self.sh("nvim-sock", "-L", t.sock, "%0", env=t.env(self.env))
        self.assertIn("nvim-sock", self.assert_2(r))


class NoKeys(unittest.TestCase):
    """The skill sends no keys and teaches none."""

    def test_no_script_uses_remote_send(self):
        for path in sorted(glob.glob(os.path.join(SCRIPTS, "*"))):
            with self.subTest(script=os.path.basename(path)):
                with open(path, encoding="utf-8") as f:
                    self.assertNotIn("--remote-send", f.read())

    def test_skill_states_the_rules(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as f:
            text = f.read()
        for line in (
                "Default to using your normal tools for editing, not nvim socket tools",
                "Use RPC (nvim --server SOCK --remote-*) to:",
                "Check for modified buffer via socket before editing with your tools",
                "Look: which file is open; where my cursor is",
                "Show: open a file for me; jump to a line",
                "Reload after you edit on disk (:checktime), so I don't save over you",
                "Don't use RPC to:",
                "Type into my buffer: it races my typing, tangles my undo",
                "Edit when the buffer is modified: leave it, tell me"):
            with self.subTest(line=line):
                self.assertTrue(line in text, "SKILL.md lacks the rule line")
        self.assertFalse("<C-\\><C-n>" in text, "SKILL.md still teaches a key prefix")
        for name in ("nvim-look", "nvim-modified", "nvim-reload", "nvim-read"):
            with self.subTest(tool=name):
                self.assertIn("`%s " % name, text)
                self.assertTrue(os.path.exists(script(name)))


if __name__ == "__main__":
    unittest.main()
