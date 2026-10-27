"""Where the state lives: ~/.sessionkit/view/state by default, beside the
settings, and how a home that used the old dir, ~/.local/state/sessionview,
keeps its state (docs/decisions/state-and-log-home.md, sections 2 to 5).

- The default state dir is made 0700. A fresh home writes nothing under the
  old dir or the older ~/.local/state/herd.
- At the default only, lib/state.sh HARD-LINKS each state file from the old
  dir into the new one (recent.tsv, picker-order, sidebar-mail.txt, and each
  regular file of mutt/ into a fresh mutt/), and never unlinks an old name.
  A running older sidebar at the old dir sees every change, and the other
  way round. The logs and the frame pins stay only in the old dir.
- The link step is idempotent and race-safe: link(2) never replaces a file.
- The sidebar reads through a fallback, so a name the step has not linked
  (not run yet, failed, or the new name already taken) is still read.
- An explicit $SESSIONVIEW_STATE, or one equal to the old dir, is never
  linked from and never read through the fallback.
- Every writer of a linked file writes in place; a grep finds every line
  that names one, and every rename or delete under the state dir.

Each test has its own scratch HOME under $TMPDIR. The shell rule runs through
a real entry point (a bare `sessionview` with no terminal: lib/state.sh, then
it refuses) or sourced on its own; the Python rule through bin/tmux-sidebar
loaded into a child process, its screen never started. The session verb's
real run uses a private tmux socket only."""
import ast
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import textwrap
import tokenize
import unittest

from tests import support
from tests.test_frame_hijack import FRAME, HijackCase, wait_for

SV = os.path.join(support.BIN, "sessionview")
SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")
STATE_SH = os.path.join(support.REPO, "lib", "state.sh")

# The sidebar module's start (paths, dirs, the log), then one action:
# read (print what it resolved and read), flip (the picker flip), mail TEXT,
# remote (fetch_remote, its ssh faked: the evidence JSON), pin (frame_attach's
# pin write, to $SESSIONVIEW_PIN), log (one error line), plugin (a plugin
# action's body file, its command stubbed). It also prints the process umask
# once the module is loaded: the sidebar must leave it as it found it.
HARNESS = textwrap.dedent('''
    import importlib.machinery, importlib.util, json, os, sys, types
    loader = importlib.machinery.SourceFileLoader("sidebar", sys.argv[1])
    spec = importlib.util.spec_from_loader("sidebar", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    act = sys.argv[2]
    if act == "flip":
        m.flip_picker_order()
    elif act == "mail":
        sent = types.SimpleNamespace(returncode=0, stdout="", stderr="")
        m.subprocess.run = lambda *a, **k: sent          # write the body, send nothing
        m.mail("nobody", sys.argv[3])
    elif act == "remote":
        out = types.SimpleNamespace(returncode=0, stderr="",
                                    stdout="[]\\n---PANES\\n---SESS\\ndemo\\t/x/demo\\t1\\n")
        m.subprocess.run = lambda *a, **k: out           # no ssh: a faked answer
        m.CFG["remote_connect"] = "auto"
        m.fetch_remote(sys.argv[3])
    elif act == "pin":
        # frame_attach's tail: the pin is written once the frame pane's tty is known
        m.sh = lambda *a, **k: "/dev/ttys999"
        m.subprocess.run = lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="", stderr="")
        m.frame_pane = lambda *a, **k: "%1"
        m.frame_attach("fsock:fsess", "default", "demo")
    elif act == "log":
        m.log_err("probe", "one error line")
    elif act == "plugin":
        m.subprocess.run = lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="", stderr="")
        m.run_action({"a": {"id": "go", "body": "{input}", "command": ["true"]},
                      "plug": {"id": "x"}, "ctx": {}}, {"input": "typed text"})
    um = os.umask(0); os.umask(um)
    print(json.dumps({"state": m.SESSIONVIEW_STATE, "log": m.SESSIONVIEW_LOG,
                      "recent": m.recent_times(), "order": m.picker_order(), "umask": um}))
''')

LINKED = ("recent.tsv", "picker-order", "sidebar-mail.txt")
MUTT = ("a.rc", "b.rc")
UNLINKED = ("sessionview.log", "sidebar-mouse.log", "frame-123.tty", "frame-456.tty",
            "frame.tty", "sidebar-remote-devbox.json", "plugin-x-go.txt")


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def read(path):
    with open(path) as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def listing(root):
    """{relative path: (inode, mtime_ns, nlink)} of every file under ROOT."""
    out = {}
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            p = os.path.join(d, n)
            st = os.lstat(p)
            out[os.path.relpath(p, root)] = (st.st_ino, st.st_mtime_ns, st.st_nlink)
    return out


class Home(unittest.TestCase):
    """A scratch HOME under $TMPDIR, its four dirs, and ways to start."""

    def setUp(self):
        # Every child starts at umask 022, the default, whatever the runner's
        # is: under a 077 runner every mode test would pass for nothing.
        self.addCleanup(os.umask, os.umask(0o022))
        tmp = tempfile.TemporaryDirectory(prefix="sv-statehome-", ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.home = os.path.realpath(tmp.name)
        self.n = os.path.join(self.home, ".sessionkit", "view", "state")
        self.o = os.path.join(self.home, ".local", "state", "sessionview")
        self.h = os.path.join(self.home, ".local", "state", "herd")
        self.ld = os.path.join(self.home, ".sessionkit", "view", "log")
        self.new_log = os.path.join(self.ld, "sessionview.log")
        self.old_log = os.path.join(self.o, "sessionview.log")
        self.path = os.environ.get("PATH", "")

    def env(self, **extra):
        e = {k: os.environ[k] for k in support.KEEP if k in os.environ}
        e.update(HOME=self.home, GIT_CEILING_DIRECTORIES=self.home, PATH=self.path,
                 SESSIONVIEW_PYTHON=sys.executable)
        e.update(extra)
        return e

    def frame(self, **extra):
        """A bare `sessionview` with no terminal: lib/state.sh runs, then the
        frame refuses and touches nothing else."""
        r = subprocess.run([SV], env=self.env(**extra), cwd=self.home, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not a terminal", r.stderr)
        return r

    def shell(self, script="", **extra):
        """lib/state.sh sourced under sh, then SCRIPT; returns the exported env."""
        r = subprocess.run(["sh", "-c", '. "$1"; ' + script + '\nenv -0', "sh", STATE_SH],
                           env=self.env(**extra), cwd=self.home, capture_output=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return dict(kv.split("=", 1) for kv in r.stdout.decode().split("\0") if "=" in kv)

    def python(self, act="read", *args, **extra):
        """The sidebar module's start, then ACT; returns what it resolved and read."""
        r = subprocess.run([sys.executable, "-B", "-c", HARNESS, SIDEBAR, act, *args],
                           env=self.env(**extra), cwd=self.home, capture_output=True,
                           text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def session_verb(self, name, **extra):
        """The session verb's real run (it appends recent.tsv), on a private
        tmux server with a fixture store."""
        with support.private_tmux("state") as pt:
            fx = support.StoreFixtures(os.path.join(self.home, "fx"), pt)
            env = fx.env(self.env(**extra))
            env.pop("SESSIONVIEW_STATE", None)
            env.update(extra)
            self.assertEqual(pt.tmux("-f", "/dev/null", "new-session", "-d", "-s", "boot", "sleep 3600").returncode, 0)
            r = support.run("sessionview-session", name, "--socket", pt.sock,
                            "--store", fx.path("fx-legacy"), env=env, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)

    def failing_ln(self):
        """Put an `ln` that always fails first on PATH (a filesystem with no
        hard links, or EXDEV)."""
        d = os.path.join(self.home, "fail-bin")
        write(os.path.join(d, "ln"), "#!/bin/sh\necho 'ln: Operation not permitted' >&2\nexit 1\n")
        os.chmod(os.path.join(d, "ln"), 0o755)
        self.path = d + os.pathsep + self.path

    def seed_old(self):
        """An upgrade home: the old dir holds the link set, mutt/, the logs,
        two frame pins, a herd-era pin and the per-run evidence files."""
        write(os.path.join(self.o, "recent.tsv"), "1000\talpha\n1001\tbeta\n")
        write(os.path.join(self.o, "picker-order"), "alpha")
        write(os.path.join(self.o, "sidebar-mail.txt"), "the last body\n")
        for n in MUTT:
            write(os.path.join(self.o, "mutt", n), f"set folder={n}\n")
        for n in UNLINKED:
            write(os.path.join(self.o, n), f"{n}\n")
        return listing(self.o)

    def assert_one_file(self, name):
        a, b = os.path.join(self.o, name), os.path.join(self.n, name)
        self.assertTrue(os.path.samefile(a, b), f"{name}: not one file")
        self.assertEqual(os.stat(b).st_nlink, 2, name)

    def assert_linked_end_state(self, before):
        for n in LINKED + tuple(f"mutt/{m}" for m in MUTT):
            with self.subTest(name=n):
                self.assert_one_file(n)
        self.assertEqual(sorted(listing(self.o)), sorted(before), "the old dir lost or gained a name")
        for n in UNLINKED:
            self.assertFalse(os.path.lexists(os.path.join(self.n, n)), f"{n} reached the new dir")

    def log_lines(self, path, word):
        return [l for l in read(path).splitlines() if word in l] if os.path.exists(path) else []


class FreshHome(Home):
    def test_a_fresh_home_has_both_dirs_at_0700_and_nothing_old(self):
        self.frame()
        self.python()
        self.assertEqual(mode(self.n), 0o700)
        self.assertEqual(mode(self.ld), 0o700)
        self.assertFalse(os.path.lexists(self.o), "the old state dir was made")
        self.assertFalse(os.path.lexists(self.h))

    def test_the_sidebar_on_its_own_makes_the_state_dir_0700(self):
        got = self.python()
        self.assertEqual(got["state"], self.n)
        self.assertEqual(mode(self.n), 0o700)
        self.assertFalse(os.path.lexists(self.o))

    def test_an_existing_state_dir_is_set_to_0700_each_start(self):
        for start in (self.frame, self.python):
            with self.subTest(start=start.__name__):
                os.makedirs(self.n, exist_ok=True)
                os.chmod(self.n, 0o755)
                start()
                self.assertEqual(mode(self.n), 0o700)

    def test_a_state_dir_the_user_named_is_made_0700_and_never_remoded(self):
        for start in (self.frame, self.python):
            with self.subTest(start=start.__name__):
                mine = os.path.join(self.home, "mine-" + start.__name__)
                start(SESSIONVIEW_STATE=mine)
                self.assertEqual(mode(mine), 0o700)
                os.chmod(mine, 0o755)
                start(SESSIONVIEW_STATE=mine)
                self.assertEqual(mode(mine), 0o755)


class UpgradeHome(Home):
    def test_one_start_links_every_name_and_leaves_the_rest(self):
        before = self.seed_old()
        self.frame()
        self.assert_linked_end_state(before)
        self.assertEqual(mode(os.path.join(self.n, "mutt")), 0o700)
        self.assertTrue(os.path.isdir(os.path.join(self.o, "mutt")), "the old mutt/ was moved")
        self.python()
        # the log lines: one pointer in each log, no link-failure line
        self.assertEqual(len(self.log_lines(self.old_log, self.new_log)), 1)
        self.assertEqual(len(self.log_lines(self.new_log, self.old_log)), 1)
        self.assertEqual(self.log_lines(self.new_log, "not linked"), [])

    def test_a_second_start_is_a_no_op(self):
        self.seed_old()
        self.frame()
        self.python()
        o, n = listing(self.o), listing(self.n)
        logs = read(self.old_log), read(self.new_log)
        self.frame()
        self.python()
        self.assertEqual(listing(self.o), o)
        self.assertEqual(listing(self.n), n)
        self.assertEqual((read(self.old_log), read(self.new_log)), logs)
        self.assertEqual(mode(self.o), 0o700)

    def test_a_step_cut_short_is_finished(self):
        before = self.seed_old()
        os.makedirs(self.n)
        os.link(os.path.join(self.o, "recent.tsv"), os.path.join(self.n, "recent.tsv"))
        ino = os.stat(os.path.join(self.n, "recent.tsv")).st_ino
        self.frame()
        self.assert_linked_end_state(before)
        self.assertEqual(os.stat(os.path.join(self.n, "recent.tsv")).st_ino, ino)

    def test_an_existing_different_file_is_never_overwritten(self):
        self.seed_old()
        write(os.path.join(self.n, "recent.tsv"), "2000\tgamma\n")
        self.frame()
        self.assertEqual(read(os.path.join(self.n, "recent.tsv")), "2000\tgamma\n")
        self.assertEqual(read(os.path.join(self.o, "recent.tsv")), "1000\talpha\n1001\tbeta\n")
        self.assertFalse(os.path.samefile(os.path.join(self.o, "recent.tsv"), os.path.join(self.n, "recent.tsv")))
        got = self.python()
        self.assertEqual(got["recent"], {"alpha": 1000, "beta": 1001, "gamma": 2000})
        self.assertEqual(self.log_lines(self.new_log, "not linked"), [])

    def test_a_failed_link_leaves_the_old_files_to_the_fallback(self):
        before = self.seed_old()
        self.failing_ln()
        self.frame()
        self.assertEqual(listing(self.o), before, "the old dir changed")
        for n in LINKED + tuple(f"mutt/{m}" for m in MUTT):
            self.assertFalse(os.path.lexists(os.path.join(self.n, n)), n)
        got = self.python()
        self.assertEqual(got["recent"], {"alpha": 1000, "beta": 1001})
        self.assertEqual(got["order"], "alpha")
        failed = self.log_lines(self.new_log, "not linked")
        self.assertEqual(len(failed), 1, read(self.new_log))
        self.assertIn("recent.tsv, picker-order", failed[0])
        self.frame()
        self.python()
        self.assertEqual(len(self.log_lines(self.new_log, "not linked")), 1)

    def test_the_uninstall_old_dir_line_keeps_the_state(self):
        self.seed_old()
        self.frame()
        subprocess.run(["sh", "-c", 'rm -rf "${HOME:?}/.local/state/sessionview"'],
                       env=self.env(), check=True, timeout=30)
        self.assertEqual(read(os.path.join(self.n, "recent.tsv")), "1000\talpha\n1001\tbeta\n")
        self.assertEqual(read(os.path.join(self.n, "picker-order")), "alpha")
        for n in MUTT:
            self.assertEqual(read(os.path.join(self.n, "mutt", n)), f"set folder={n}\n")

    def test_the_older_move_from_herd_chains_into_the_link_step(self):
        write(os.path.join(self.h, "herd-recent.tsv"), "1000\tmain\n")
        write(os.path.join(self.h, "herd.tty"), "/dev/ttys001\n")
        write(os.path.join(self.h, "mutt", "a.rc"), "set folder=a\n")
        self.frame()
        self.assertFalse(os.path.lexists(self.h))
        self.assertEqual(sorted(os.listdir(self.o)), ["frame.tty", "mutt", "recent.tsv"])
        self.assert_one_file("recent.tsv")
        self.assert_one_file("mutt/a.rc")
        self.assertFalse(os.path.lexists(os.path.join(self.n, "frame.tty")))
        self.assertEqual(self.python()["recent"], {"main": 1000})


class Race(Home):
    """Several entry points start at once against one seeded home: a frame
    refused for want of a tty, the session verb with --print, the shell rule
    on its own appending a recent line the way the session verb does, and
    the sidebar's start. Repeated; the end state is always the same."""

    ROUNDS = 4
    EACH = 3

    def test_several_starters_at_once_lose_nothing(self):
        for rnd in range(self.ROUNDS):
            with self.subTest(round=rnd):
                for d in (self.n, self.o, self.ld):
                    subprocess.run(["rm", "-rf", d], check=True)
                before = self.seed_old()
                env = self.env()
                procs = []
                for i in range(self.EACH):
                    procs.append(subprocess.Popen([SV], env=env, cwd=self.home, stdin=subprocess.DEVNULL,
                                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                    procs.append(subprocess.Popen(
                        [os.path.join(support.BIN, "sessionview-session"), f"demo{i}", "--print"],
                        env=env, cwd=self.home, stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                    procs.append(subprocess.Popen(
                        ["sh", "-c", '. "$1"; printf "%s\\t%s\\n" 3000 "$2" >>"$SESSIONVIEW_STATE/recent.tsv"',
                         "sh", STATE_SH, f"racer{i}"], env=env, cwd=self.home))
                    procs.append(subprocess.Popen([sys.executable, "-B", "-c", HARNESS, SIDEBAR, "read"],
                                                  env=env, cwd=self.home, stdout=subprocess.DEVNULL,
                                                  stderr=subprocess.DEVNULL))
                for p in procs:
                    p.wait(timeout=60)
                self.assert_linked_end_state(before)
                lines = read(os.path.join(self.n, "recent.tsv")).splitlines()
                want = ["1000\talpha", "1001\tbeta"] + [f"3000\tracer{i}" for i in range(self.EACH)]
                self.assertEqual(sorted(lines), sorted(want), "a recent line was lost or doubled")
                self.assertEqual(len(self.log_lines(self.new_log, self.old_log)), 1)


class Fallback(Home):
    """Before any link step, with the state dir at the default, the sidebar
    reads the old dir's recents and picker order."""

    def test_the_sidebar_started_on_its_own_reads_the_old_dir(self):
        self.seed_old()
        got = self.python()
        self.assertEqual(got["recent"], {"alpha": 1000, "beta": 1001})
        self.assertEqual(got["order"], "alpha")
        self.assertFalse(os.path.lexists(os.path.join(self.n, "recent.tsv")), "the sidebar linked")

    def test_the_sidebar_started_by_a_shell_entry_reads_the_old_dir(self):
        # the shell entry's link step failed: the fallback carries the files
        self.seed_old()
        self.failing_ln()
        exported = self.shell()
        got = self.python(**{k: v for k, v in exported.items() if k.startswith("SESSIONVIEW_")})
        self.assertEqual(got["state"], self.n)
        self.assertEqual(got["recent"], {"alpha": 1000, "beta": 1001})
        self.assertEqual(got["order"], "alpha")

    def test_the_new_picker_order_wins_once_there_is_one(self):
        self.seed_old()
        write(os.path.join(self.n, "picker-order"), "recent")
        self.assertEqual(self.python()["order"], "recent")

    def test_the_session_verb_appends_to_the_new_dir_only(self):
        support.require_tmux()
        self.seed_old()
        self.failing_ln()
        self.session_verb("gamma")
        self.assertEqual(read(os.path.join(self.o, "recent.tsv")), "1000\talpha\n1001\tbeta\n")
        self.assertRegex(read(os.path.join(self.n, "recent.tsv")), r"^\d+\tgamma\n$")
        self.assertEqual(set(self.python()["recent"]), {"alpha", "beta", "gamma"})


class ExplicitState(Home):
    def check_untouched(self, state, **extra):
        before = self.seed_old()
        logs = read(self.old_log)
        self.frame(SESSIONVIEW_STATE=state, **extra)
        got = self.python(SESSIONVIEW_STATE=state, **extra)
        self.assertFalse(os.path.lexists(self.n), "the new state dir was made")
        self.assertEqual(sorted(listing(self.o)), sorted(before), "the old dir lost or gained a name")
        for n in LINKED:
            self.assertEqual(os.stat(os.path.join(self.o, n)).st_nlink, 1, f"{n} was linked")
        self.assertEqual(got["log"], state + "/sessionview.log")
        return got, logs

    def test_an_explicit_state_dir_is_never_linked_or_read_by_fallback(self):
        mine = os.path.join(self.home, "mine")
        got, logs = self.check_untouched(mine)
        self.assertEqual(got["recent"], {})
        self.assertEqual(read(self.old_log), logs, "a pointer line was written")
        self.assertFalse(os.path.lexists(self.new_log))

    def test_the_old_dir_given_as_a_value_is_not_the_default(self):
        # a process started by older code inherits the old dir: it keeps it
        got, logs = self.check_untouched(self.o)
        self.assertEqual(got["recent"], {"alpha": 1000, "beta": 1001})
        self.assertEqual(got["state"], self.o)
        self.assertNotIn(self.new_log, read(self.old_log), "a pointer line was written")
        self.assertFalse(os.path.lexists(self.new_log))


class HoldsOld(Home):
    """After the link step, a process at the old dir (older code still
    running, or new code that inherited it) and one at the new dir see the
    same files."""

    def test_a_recent_recorded_at_the_old_dir_is_listed_at_the_new(self):
        support.require_tmux()
        self.seed_old()
        self.frame()
        self.session_verb("delta", SESSIONVIEW_STATE=self.o)
        self.assertIn("delta", self.python()["recent"])
        self.assert_one_file("recent.tsv")

    def test_a_picker_flip_at_either_dir_is_read_at_the_other(self):
        self.seed_old()
        self.frame()
        self.python("flip")                                        # at the new dir
        self.assertEqual(self.python(SESSIONVIEW_STATE=self.o)["order"], "recent")
        self.python("flip", SESSIONVIEW_STATE=self.o)              # at the old dir
        self.assertEqual(self.python()["order"], "alpha")
        self.assert_one_file("picker-order")


# ---- private modes (V6 of the security review) --------------------------------
#
# Each file sessionview creates in its state dir and its log dir is 0600, and
# each dir it makes there is 0700, given at the create in each writer: never
# by a process umask, which every child inherits (a tmux server started under
# 077 gives it to every pane it ever opens). An existing file keeps its mode
# and its inode. At the default only, the old dir is set to 0700 on each
# start, never through a symlink, and no file in it is re-moded
# (docs/decisions/state-and-log-home.md, section 2).


def modes_under(*roots):
    """{path: mode} of every file and dir under ROOTS, the roots included."""
    out = {}
    for root in roots:
        out[root] = mode(root)
        for d, dirs, files in os.walk(root):
            for n in dirs + files:
                out[os.path.join(d, n)] = mode(os.path.join(d, n))
    return out


class PrivateModes(Home):
    def stub_mail_tools(self):
        """neomutt and message on PATH, for sessionview-messages --print."""
        stub = os.path.join(self.home, "stub-bin")
        write(os.path.join(stub, "neomutt"), "#!/bin/sh\nexit 0\n")
        write(os.path.join(stub, "message"), '#!/bin/sh\nmkdir -p "$HOME/box" && echo "$HOME/box"\n')
        for n in ("neomutt", "message"):
            os.chmod(os.path.join(stub, n), 0o755)
        self.path = stub + os.pathsep + self.path

    def messages(self, **extra):
        r = support.run("sessionview-messages", "demo", "--print", env=self.env(**extra))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_fresh_home_every_writer_makes_0600_files_in_0700_dirs(self):
        support.require_tmux()
        self.stub_mail_tools()
        self.frame()
        pin = os.path.join(self.n, "frame-4242.tty")
        for act, *args in (("flip",), ("mail", "a body"), ("remote", "devbox"), ("log",), ("plugin",)):
            self.python(act, *args)
        self.python("pin", SESSIONVIEW_PIN=pin)
        self.session_verb("demo")
        self.messages()
        # the frame's own pin line runs inside a real frame: FramePin, below
        made = modes_under(self.n, self.ld)
        want = {os.path.join(self.n, n) for n in (
            "picker-order", "sidebar-mail.txt", "sidebar-remote-devbox.json", "plugin-x-go.txt",
            "frame-4242.tty", "recent.tsv", "mutt", "mutt/demo.rc")} | {self.new_log}
        self.assertLessEqual(want, set(made), "a writer wrote nothing")
        for path, m in sorted(made.items()):
            with self.subTest(path=os.path.relpath(path, self.home)):
                self.assertEqual(m, 0o700 if os.path.isdir(path) else 0o600)

    def test_an_upgrade_sets_the_old_dir_0700_and_remodes_no_file(self):
        before = self.seed_old()
        os.chmod(self.o, 0o755)
        files = {p: m for p, m in modes_under(self.o).items() if not os.path.isdir(p)}
        self.assertIn(0o644, files.values(), "precondition: the seed is 0644 under umask 022")
        self.frame()
        self.assertEqual(mode(self.o), 0o700)
        self.assert_linked_end_state(before)
        self.assertEqual({p: mode(p) for p in files}, files, "a file in the old dir was re-moded")
        self.assertEqual(mode(os.path.join(self.o, "mutt")), 0o755, "a dir inside the old dir was re-moded")

    def test_a_symlinked_old_dir_is_never_followed(self):
        target = os.path.join(self.home, "elsewhere")
        write(os.path.join(target, "recent.tsv"), "1000\talpha\n")
        os.chmod(target, 0o755)
        os.makedirs(os.path.dirname(self.o))
        os.symlink(target, self.o)
        self.frame()
        self.assertEqual(mode(target), 0o755)
        self.assertTrue(os.path.islink(self.o))

    def test_a_named_state_dir_and_its_files_are_never_remoded(self):
        self.seed_old()
        os.chmod(self.o, 0o755)
        mine = os.path.join(self.home, "mine")
        write(os.path.join(mine, "picker-order"), "alpha")
        os.chmod(mine, 0o755)
        order = os.path.join(mine, "picker-order")
        ino = os.stat(order).st_ino
        self.assertEqual(mode(order), 0o644)
        self.frame(SESSIONVIEW_STATE=mine)
        self.python("flip", SESSIONVIEW_STATE=mine)
        self.python("remote", "devbox", SESSIONVIEW_STATE=mine)
        self.assertEqual(read(order), "recent")
        self.assertEqual(mode(mine), 0o755)
        self.assertEqual((mode(order), os.stat(order).st_ino), (0o644, ino))
        self.assertEqual(mode(os.path.join(mine, "sidebar-remote-devbox.json")), 0o600)
        self.assertEqual(mode(self.o), 0o755, "the old dir was re-moded for a named state dir")

    def test_no_writer_leaves_a_process_umask(self):
        # A umask is inherited by every child, the user's tmux server among
        # them, and a server keeps it for every pane it ever opens: the
        # private mode is given at each create instead.
        self.assertEqual(self.shell('SV_UMASK=$(umask); export SV_UMASK')["SV_UMASK"], "0022")
        self.assertEqual(self.python()["umask"], 0o022)
        self.assertEqual(self.python("flip")["umask"], 0o022)


class FramePin(HijackCase):
    """The frame's own pin, written by its shell once it has the terminal,
    is 0600, from a frame started at umask 022."""

    def setUp(self):
        self.addCleanup(os.umask, os.umask(0o022))      # before the private server starts
        super().setUp()

    def test_the_frame_pin_is_0600(self):
        a = self.client("A")
        rc, err = self.run_in_pane("pin", [FRAME], session="A")
        self.assertEqual(rc, 0, err)
        self.assertTrue(wait_for(lambda: a.tty in self.clients_on(sock=self.frame_sock)),
                        "the frame never took the terminal")
        state = self.base["SESSIONVIEW_STATE"]

        def pins():
            return sorted(os.path.join(state, n) for n in os.listdir(state)
                          if n.startswith("frame-") and n.endswith(".tty"))
        self.assertTrue(wait_for(lambda: pins() and os.path.getsize(pins()[0]) > 0), "no pin was written")
        self.assertEqual(mode(pins()[0]), 0o600)


# ---- every writer writes in place ---------------------------------------------
#
# The writers of the linked files, named once. Each is (file, the code line
# that writes it, found by the grep below, as (path, a substring of that
# line)). The grep test fails on a line that names a linked file and is on no
# list, so a new writer lands only by joining this one, under the in-place
# test.
WRITERS = {
    "recent.tsv": ("bin/sessionview-session", '>>"$SESSIONVIEW_STATE/recent.tsv"'),
    "picker-order": ("bin/tmux-sidebar", 'with _open_private(state("picker-order")) as f:'),
    "sidebar-mail.txt": ("bin/tmux-sidebar", 'path = state("sidebar-mail.txt")'),
    "mutt/demo.rc": ("bin/sessionview-messages", 'STATE="$SESSIONVIEW_STATE/mutt"'),
}


class WritersWriteInPlace(Home):
    """For each writer, with the new name seeded as a hard link of the old
    one: run it at the new dir, then at the old one. After each the two names
    are still one file, and both read the new content."""

    def seed_pair(self, name, text):
        old, new = os.path.join(self.o, name), os.path.join(self.n, name)
        write(old, text)
        os.makedirs(os.path.dirname(new), exist_ok=True)
        os.link(old, new)
        return old, new

    def assert_pair(self, old, new, check):
        self.assertTrue(os.path.samefile(old, new), "the writer split the two names")
        self.assertEqual(os.stat(new).st_nlink, 2)
        check(read(new))
        self.assertEqual(read(old), read(new))

    def at_both(self, name, text, run, check):
        old, new = self.seed_pair(name, text)
        for where in ({}, {"SESSIONVIEW_STATE": self.o}):
            with self.subTest(writer=name, at="old" if where else "new"):
                run(where)
                self.assert_pair(old, new, lambda body: check(body, where))

    # Each writer in WRITERS and the test that runs it.
    TESTS = {"recent.tsv": "test_writes_recent", "picker-order": "test_writes_picker_order",
             "sidebar-mail.txt": "test_writes_sidebar_mail", "mutt/demo.rc": "test_writes_mutt_rc"}

    def test_every_writer_is_tested(self):
        self.assertEqual(sorted(self.TESTS), sorted(WRITERS))
        self.assertEqual(sorted(self.TESTS.values()),
                         sorted(n for n in dir(self) if n.startswith("test_writes_")))

    def test_writes_recent(self):
        support.require_tmux()
        self.at_both("recent.tsv", "1000\talpha\n",
                     lambda where: self.session_verb("new" if not where else "old", **where),
                     lambda body, where: self.assertIn("\tnew" if not where else "\told", body))

    def test_writes_picker_order(self):
        self.at_both("picker-order", "alpha",
                     lambda where: self.python("flip", **where),
                     lambda body, where: self.assertEqual(body, "recent" if not where else "alpha"))

    def test_writes_sidebar_mail(self):
        self.at_both("sidebar-mail.txt", "old body\n",
                     lambda where: self.python("mail", "body at " + ("old" if where else "new"), **where),
                     lambda body, where: self.assertEqual(body, "body at " + ("old" if where else "new") + "\n"))

    def test_writes_mutt_rc(self):
        stub = os.path.join(self.home, "stub-bin")
        write(os.path.join(stub, "neomutt"), "#!/bin/sh\nexit 0\n")      # --print never runs it
        write(os.path.join(stub, "message"), '#!/bin/sh\nmkdir -p "$HOME/box" && echo "$HOME/box"\n')
        for n in ("neomutt", "message"):
            os.chmod(os.path.join(stub, n), 0o755)
        self.path = stub + os.pathsep + self.path

        def run(where):
            r = support.run("sessionview-messages", "demo", "--print", env=self.env(**where))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("rc=" + os.path.join(where.get("SESSIONVIEW_STATE", self.n), "mutt", "demo.rc"), r.stdout)
        self.at_both("mutt/demo.rc", "stale\n", run,
                     lambda body, where: self.assertIn("set mbox_type=Maildir", body))


# ---- the grep: code lines only ------------------------------------------------
#
# What is read: every tracked file under bin/, lib/, src/, plugins/ and tmux/,
# code lines only. A shell comment line, a heredoc body (usage text) and a
# Python comment or docstring are not code. The sh trampoline at the top of a
# Python tool is shell, so it is read as shell.
SCANNED = ("bin", "lib", "src", "plugins", "tmux")


def tracked():
    r = subprocess.run(["git", "-C", support.REPO, "ls-files", "--", *SCANNED],
                       capture_output=True, text=True, check=True)
    return [p for p in r.stdout.split() if os.path.isfile(os.path.join(support.REPO, p))]


def _shell_code(lines, numbers):
    """(n, line) for the shell code lines among LINES, numbered NUMBERS."""
    out, tag = [], None
    for n, line in zip(numbers, lines):
        if tag is not None:
            if line.strip() == tag:
                tag = None
            continue
        if line.lstrip().startswith("#"):
            continue
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", line)
        if m:
            tag = m.group(1)
        out.append((n, line))
    return out


def code_lines(rel):
    """[(line number, text)] of REL's code lines."""
    path = os.path.join(support.REPO, rel)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except UnicodeDecodeError:
        return []
    lines = text.splitlines()
    kind = support.script_kind(path) or ("python" if rel.endswith(".py") else "sh")
    if kind != "python":
        if rel.endswith((".toml", ".conf")):
            return [(i, l) for i, l in enumerate(lines, 1) if not l.lstrip().startswith("#")]
        return _shell_code(lines, range(1, len(lines) + 1))
    tree = ast.parse(text)
    skip, shell = set(), []
    for node in ast.walk(tree):
        # a string that is a statement of its own: a docstring, or a module's
        # second doc string after the sh trampoline
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            rng = range(node.lineno, node.end_lineno + 1)
            if node.lineno == 2 and lines[0].startswith("#!/bin/sh"):
                shell = list(rng)                          # the sh trampoline
            skip.update(rng)
        elif isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "__doc__" for t in node.targets):
            skip.update(range(node.lineno, node.end_lineno + 1))   # __doc__ = """..."""
    comments = {}
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            comments[tok.start[0]] = tok.start[1]
    out = _shell_code([lines[i - 1] for i in shell], shell)
    for i, line in enumerate(lines, 1):
        if i in skip or i == 1:
            continue
        line = line[:comments[i]] if i in comments else line
        if line.strip():
            out.append((i, line))
    return sorted(out)


def resolver_range():
    """The lines of resolve_paths() in bin/tmux-sidebar."""
    with open(SIDEBAR, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    f = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "resolve_paths")
    return range(f.lineno, f.end_lineno + 1)


# Every code line that names a linked file, and what it is. A line matches
# an entry when it is in that file and holds that substring. Each line must
# match exactly one entry, and each entry at least one line.
LINKED_NAME = re.compile(r"recent\.tsv|picker-order|sidebar-mail\.txt|SESSIONVIEW_STATE/mutt|_sv_[on]/mutt|_sv_link")
LINKED_LINES = [(path, needle, "writer") for path, needle in WRITERS.values()] + [
    ("bin/tmux-sidebar", 'for path in state_files("recent.tsv"):', "reader: recent_times"),
    ("bin/tmux-sidebar", 'for path in reversed(state_files("picker-order")):', "reader: picker_order"),
    ("bin/tmux-sidebar", '("picker-order", None)', "names it, touches nothing: the picker's flip key"),
    ("bin/tmux-sidebar", 'what == "picker-order"', "names it, touches nothing: the flip key's click"),
    ("bin/tmux-sidebar", '"picker-order", "picker-item"', "names it, touches nothing: the picker's keys"),
    ("bin/tmux-sidebar", 'for n in ("recent.tsv", "picker-order")', "reads only: the link-failure line"),
    ("lib/state.sh", "_sv_link", "the link step"),
    ("lib/state.sh", '/mutt"', "the link step: a fresh mutt/, its files linked one by one"),
    ("lib/state.sh", "herd-recent.tsv", "the older move from herd (section 5), before any link"),
]

# A rename, replace, delete or temp file whose target may be under the state
# dir. Allowed only for the older move from ~/.local/state/herd (section 5),
# which runs before anything is linked, and for text that is printed, not run.
OPS = re.compile(r"\b(os\.replace|os\.rename|rename|mv|unlink|os\.remove|rm|mktemp|tempfile)\b")
STATE_REF = re.compile(r"SESSIONVIEW_STATE|\bstate\(|_sv_[onhf]\b|\bSTATE\b|state_files|old_dir")
REPLACE_ALLOWED = [
    ("lib/state.sh", 'mv "$_sv_h" "$_sv_o"', "the older move from herd (section 5)"),
    ("lib/state.sh", 'mv "$_sv_o/herd-recent.tsv"', "the older move from herd (section 5)"),
    ("lib/state.sh", 'mv "$_sv_o/herd.tty"', "the older move from herd (section 5)"),
]

# Lines that rename or replace, but nothing under the state dir: named, so a
# change that points one at the state dir is caught.
NOT_STATE = [
    ("bin/sessionview-config", "mv {q_old} {q_new}", "printed text: the settings host step a user runs"),
    ("bin/sessionview-config", "-exec mv {{}} {q_dir}/", "printed text: the settings host step a user runs"),
    ("bin/sessionview-config", "tempfile.mkstemp(dir=d)", "the SETTINGS file, written whole"),
    ("bin/sessionview-config", "os.replace(tmp, p)", "the SETTINGS file, written whole"),
]


class TheGrep(unittest.TestCase):
    def matches(self, path, line, table):
        return [e for e in table if e[0] == path and e[1] in line]

    def hits(self, pattern, also=None):
        out = []
        for rel in tracked():
            for n, line in code_lines(rel):
                if pattern.search(line) and (also is None or also.search(line)):
                    out.append((rel, n, line.strip()))
        return out

    def test_the_grep_reads_code_not_docstrings(self):
        # the log() docstring names the default log; the guard must skip it
        lines = dict(code_lines("bin/tmux-sidebar"))
        doc = [n for n, l in enumerate(read(SIDEBAR).splitlines(), 1)
               if "~/.sessionkit/view/log/sessionview.log." in l]
        self.assertTrue(doc)
        self.assertFalse(set(doc) & set(lines))

    def test_no_hand_copy_of_a_default(self):
        default = re.compile(r"\.sessionkit/view/(state|log)|\.local/state/(sessionview|herd)"
                             r"|SESSIONVIEW_STATE:-|environ\.get\(\"SESSIONVIEW_STATE\"|environ\[\"SESSIONVIEW_STATE\"\]")
        resolver = resolver_range()
        stray = [h for h in self.hits(default)
                 if h[0] != "lib/state.sh" and not (h[0] == "bin/tmux-sidebar" and h[1] in resolver)]
        self.assertEqual(stray, [], "a path default written outside the one rule per language")

    def test_every_line_that_names_a_linked_file_is_known(self):
        used = set()
        for rel, n, line in self.hits(LINKED_NAME):
            with self.subTest(at=f"{rel}:{n}"):
                m = self.matches(rel, line, LINKED_LINES)
                self.assertEqual(len(m), 1, f"{rel}:{n} names a linked file and is on no list (or two): {line}")
                used.update(m)
        self.assertEqual([e for e in LINKED_LINES if e not in used], [], "a listed line is gone")

    def test_nothing_replaces_or_deletes_under_the_state_dir(self):
        used = set()
        for rel, n, line in self.hits(OPS, STATE_REF):
            with self.subTest(at=f"{rel}:{n}"):
                m = self.matches(rel, line, REPLACE_ALLOWED)
                self.assertEqual(len(m), 1, f"{rel}:{n} may replace or delete a state file: {line}")
                used.update(m)
        self.assertEqual([e for e in REPLACE_ALLOWED if e not in used], [], "an allowed line is gone")

    def test_the_grep_catches_a_replace_of_a_state_file(self):
        for planted in ('os.replace(tmp, state("picker-order"))',
                        'mv "$tmp" "$SESSIONVIEW_STATE/recent.tsv"',
                        'os.remove(state("sidebar-mail.txt"))',
                        'rm -f "$SESSIONVIEW_STATE/mutt/x.rc"'):
            with self.subTest(line=planted):
                self.assertTrue(OPS.search(planted) and STATE_REF.search(planted))
                self.assertTrue(LINKED_NAME.search(planted))

    def test_the_known_settings_replaces_are_not_state(self):
        found = {(rel, e[1]) for rel, n, line in self.hits(OPS)
                 for e in self.matches(rel, line, NOT_STATE)}
        self.assertEqual(found, {(e[0], e[1]) for e in NOT_STATE}, "a named line is gone")
        for rel, n, line in self.hits(OPS):
            if self.matches(rel, line, NOT_STATE):
                self.assertIsNone(STATE_REF.search(line), f"{rel}:{n} now names the state dir")

    def test_nothing_writes_an_ssh_control_socket(self):
        self.assertEqual(self.hits(re.compile(r"ssh-cm|ControlPath")), [])


if __name__ == "__main__":
    unittest.main()
