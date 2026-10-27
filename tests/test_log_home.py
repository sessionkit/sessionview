"""Where the log lives: ~/.sessionkit/view/log/sessionview.log by default,
beside the settings (docs/decisions/state-and-log-home.md, rule 2).

- $SESSIONVIEW_LOG, set and not empty, is the log.
- Otherwise, when the state dir is the default, the log is the kit's
  ~/.sessionkit/view/log/sessionview.log, in a dir made 0700.
- Otherwise ($SESSIONVIEW_STATE named by the user) the log stays in that
  dir, $SESSIONVIEW_STATE/sessionview.log, exactly as before.

The old log, ~/.local/state/sessionview/sessionview.log, is never moved,
copied or truncated. The start that creates the new default log adds one
line to each file, naming the other, and only if the old file exists.

The Python half (bin/tmux-sidebar) is loaded into a child process the way
test_log_levels does, with its own HOME, so no test starts the sidebar's
screen. The shell half (lib/state.sh) is sourced under sh. Both answer the
same, state dir and log, on every value in the decision's edge list, and
the shell exports SESSIONVIEW_LOG only when the user gave it."""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest

from tests import support
from tests.test_frame_hijack import FRAME, HijackCase, wait_for

SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")
STATE_SH = os.path.join(support.REPO, "lib", "state.sh")

# Load the sidebar's module (its start runs: the paths, the dirs, the log's
# create), optionally log one line, and print what it resolved.
HARNESS = textwrap.dedent('''
    import importlib.machinery, importlib.util, json, sys
    loader = importlib.machinery.SourceFileLoader("sidebar", sys.argv[1])
    spec = importlib.util.spec_from_loader("sidebar", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    if sys.argv[2]:
        m.log_err("probe", sys.argv[2])
    print(json.dumps({"state": m.SESSIONVIEW_STATE, "log": m.SESSIONVIEW_LOG}))
''')

# What an entry script does: source the rule, which defaults the state dir.
# Prints the shell's LOG, then the exported environment, NUL-separated.
SHELL = '. "$1"; printf "%s\\n" "$LOG"; env -0'

LINE = r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d sock=\S+ "


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def read(path):
    with open(path) as f:
        return f.read()


class Home(unittest.TestCase):
    """A scratch HOME under $TMPDIR, and its default paths."""

    def setUp(self):
        # Every child starts at umask 022, the default, whatever the runner's
        # is: under a 077 runner a mode test would pass for nothing.
        self.addCleanup(os.umask, os.umask(0o022))
        tmp = tempfile.TemporaryDirectory(prefix="sv-loghome-")
        self.addCleanup(tmp.cleanup)
        self.home = os.path.realpath(tmp.name)
        self.ld = os.path.join(self.home, ".sessionkit", "view", "log")
        self.new = os.path.join(self.ld, "sessionview.log")
        self.ndir = os.path.join(self.home, ".sessionkit", "view", "state")
        self.odir = os.path.join(self.home, ".local", "state", "sessionview")
        self.old = os.path.join(self.odir, "sessionview.log")

    def env(self, **extra):
        e = {k: os.environ[k] for k in support.KEEP if k in os.environ}
        e.update(HOME=self.home, GIT_CEILING_DIRECTORIES=self.home)
        e.update(extra)
        return e

    def python(self, probe="", **extra):
        """The sidebar module's start under ENV; returns {state, log}."""
        r = subprocess.run([sys.executable, "-B", "-c", HARNESS, SIDEBAR, probe],
                           env=self.env(**extra), capture_output=True, text=True,
                           timeout=60, cwd=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def shell(self, **extra):
        """lib/state.sh sourced under sh; returns (LOG, exported env)."""
        r = subprocess.run(["sh", "-c", SHELL, "sh", STATE_SH], env=self.env(**extra),
                           capture_output=True, timeout=30, cwd=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        log, _, rest = r.stdout.partition(b"\n")
        exported = dict(kv.split("=", 1) for kv in rest.decode().split("\0") if "=" in kv)
        return log.decode(), exported

    def seed_old_log(self, text="OLD-LOG-LINE sock=default click: it broke\n"):
        os.makedirs(self.odir, exist_ok=True)
        with open(self.old, "w") as f:
            f.write(text)
        return text


class PythonRule(Home):
    """bin/tmux-sidebar resolves the log and writes to it."""

    def test_the_default_log_is_the_kit_log_dir(self):
        got = self.python("hello")
        self.assertEqual(got["log"], self.new)
        self.assertRegex(read(self.new), rf"(?m)^{LINE}probe: hello$")
        self.assertFalse(os.path.exists(self.old), "a log was written in the old dir")

    def test_the_log_dir_is_0700_and_its_parents_exist(self):
        self.python()
        self.assertEqual(mode(self.ld), 0o700)
        self.assertTrue(os.path.isdir(os.path.join(self.home, ".sessionkit", "view")))

    def test_an_existing_log_dir_is_set_to_0700(self):
        os.makedirs(self.ld)
        os.chmod(self.ld, 0o755)
        self.python()
        self.assertEqual(mode(self.ld), 0o700)

    def test_the_log_is_created_at_start_even_with_nothing_to_say(self):
        self.python()
        self.assertTrue(os.path.isfile(self.new))

    def test_SESSIONVIEW_LOG_wins(self):
        mine = os.path.join(self.home, "mine", "view.log")
        got = self.python("hello", SESSIONVIEW_LOG=mine)
        self.assertEqual(got["log"], mine)
        self.assertIn("probe: hello", read(mine))
        self.assertFalse(os.path.exists(self.ld), "the default log dir was made")

    def test_SESSIONVIEW_LOG_wins_over_SESSIONVIEW_STATE(self):
        mine = os.path.join(self.home, "mine.log")
        state = os.path.join(self.home, "state")
        got = self.python("hello", SESSIONVIEW_LOG=mine, SESSIONVIEW_STATE=state)
        self.assertEqual(got["log"], mine)
        self.assertIn("probe: hello", read(mine))
        self.assertFalse(os.path.exists(os.path.join(state, "sessionview.log")))

    def test_a_log_dir_the_user_named_is_made_0700_when_missing(self):
        mine = os.path.join(self.home, "mine", "view.log")
        self.python("hello", SESSIONVIEW_LOG=mine)
        self.assertEqual(mode(os.path.dirname(mine)), 0o700)

    def test_an_existing_log_dir_the_user_named_is_never_remoded(self):
        d = os.path.join(self.home, "mine")
        os.makedirs(d)
        os.chmod(d, 0o755)
        self.python("hello", SESSIONVIEW_LOG=os.path.join(d, "view.log"))
        self.assertEqual(mode(d), 0o755)

    def test_SESSIONVIEW_STATE_alone_keeps_the_log_in_it(self):
        state = os.path.join(self.home, "state")
        got = self.python("hello", SESSIONVIEW_STATE=state)
        self.assertEqual(got["log"], os.path.join(state, "sessionview.log"))
        self.assertIn("probe: hello", read(os.path.join(state, "sessionview.log")))
        self.assertFalse(os.path.exists(self.ld), "the default log dir was made")

    def test_SESSIONVIEW_STATE_set_to_the_default_is_the_default(self):
        # the entry scripts export the default; a sidebar they start sees it set
        got = self.python("hello", SESSIONVIEW_STATE=self.ndir)
        self.assertEqual(got["log"], self.new)

    def test_SESSIONVIEW_STATE_set_to_the_old_dir_is_not_the_default(self):
        # a sidebar started by older code inherits the old dir: its log stays there
        got = self.python("hello", SESSIONVIEW_STATE=self.odir)
        self.assertEqual(got["log"], self.old)
        self.assertFalse(os.path.exists(self.new))

    def test_an_empty_SESSIONVIEW_LOG_is_unset(self):
        got = self.python("hello", SESSIONVIEW_LOG="")
        self.assertEqual(got["log"], self.new)


class LogMode(Home):
    """The log FILE is created 0600, wherever it is; one that already exists
    keeps its mode and its inode (its dir is the guard)."""

    def test_a_fresh_kit_log_is_0600(self):
        self.python()
        self.assertEqual(mode(self.new), 0o600)

    def test_a_log_at_SESSIONVIEW_LOG_is_created_0600(self):
        mine = os.path.join(self.home, "mine", "view.log")
        self.python("hello", SESSIONVIEW_LOG=mine)
        self.assertEqual(mode(mine), 0o600)

    def test_a_log_in_a_named_state_dir_is_created_0600(self):
        state = os.path.join(self.home, "state")
        self.python("hello", SESSIONVIEW_STATE=state)
        self.assertEqual(mode(os.path.join(state, "sessionview.log")), 0o600)

    def test_an_existing_0644_log_keeps_its_mode_and_inode(self):
        for name, path, extra in (
                ("kit", self.new, {}),
                ("given", os.path.join(self.home, "given.log"), {"SESSIONVIEW_LOG": os.path.join(self.home, "given.log")})):
            with self.subTest(log=name):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write("an earlier line\n")
                os.chmod(path, 0o644)
                ino = os.stat(path).st_ino
                self.python("hello", **extra)
                self.assertIn("probe: hello", read(path))
                self.assertEqual((mode(path), os.stat(path).st_ino), (0o644, ino))


class PointerLines(Home):
    """The old log stays; one line in each file names the other."""

    def test_both_pointer_lines_and_the_old_log_is_untouched(self):
        before = self.seed_old_log()
        ino = os.stat(self.old).st_ino
        self.python("hello")
        old = read(self.old)
        self.assertTrue(old.startswith(before), "the old log was rewritten")
        added = old[len(before):].splitlines()
        self.assertEqual(len(added), 1, old)
        self.assertRegex(added[0], rf"^{LINE}log: .*{re.escape(self.new)}$")
        self.assertEqual(os.stat(self.old).st_ino, ino, "the old log was replaced")
        new = read(self.new).splitlines()
        self.assertRegex(new[0], rf"^{LINE}log: .*{re.escape(self.old)}$")
        self.assertEqual(sum(self.old in l for l in new), 1, new)

    def test_the_pointer_lines_are_written_once(self):
        self.seed_old_log()
        self.python()
        old, new = read(self.old), read(self.new)
        self.python("again")
        self.assertEqual(read(self.old), old)
        self.assertEqual(sum(self.old in l for l in read(self.new).splitlines()), 1)
        self.assertTrue(read(self.new).startswith(new))

    def test_no_old_log_no_pointer_and_none_is_created(self):
        self.python("hello")
        self.assertFalse(os.path.exists(self.old), "the old log was created")
        self.assertNotIn(self.old, read(self.new))

    def test_an_explicit_state_dir_writes_no_pointer(self):
        before = self.seed_old_log()
        self.python("hello", SESSIONVIEW_STATE=os.path.join(self.home, "state"))
        self.assertEqual(read(self.old), before)
        self.assertFalse(os.path.exists(self.new))

    def test_a_log_the_user_named_writes_no_pointer(self):
        before = self.seed_old_log()
        self.python("hello", SESSIONVIEW_LOG=os.path.join(self.home, "mine.log"))
        self.assertEqual(read(self.old), before)
        self.assertFalse(os.path.exists(self.new))


class ShellRule(Home):
    """lib/state.sh holds the same rule, and exports SESSIONVIEW_LOG only
    when the user gave it."""

    # docs/decisions/state-and-log-home.md section 1, "The tests that hold it".
    CASES = (
        {},
        {"SESSIONVIEW_STATE": "{home}/state"},
        {"SESSIONVIEW_LOG": "{home}/mine.log"},
        {"SESSIONVIEW_STATE": "{home}/state", "SESSIONVIEW_LOG": "{home}/mine.log"},
        {"SESSIONVIEW_LOG": ""},
        {"SESSIONVIEW_STATE": ""},
        {"SESSIONVIEW_STATE": "", "SESSIONVIEW_LOG": ""},
        {"SESSIONVIEW_STATE": "{home}/.sessionkit/view/state"},
        {"SESSIONVIEW_STATE": "{home}/.local/state/sessionview"},
        {"SESSIONVIEW_STATE": "~/state"},
        {"SESSIONVIEW_STATE": "{home}/state/"},
        {"SESSIONVIEW_STATE": "{home}/.sessionkit/view/state/"},
        {"HOME": "{home}/"},
    )

    def case(self, c):
        return {k: v.format(home=self.home) for k, v in c.items()}

    def test_shell_and_python_agree_on_the_log(self):
        for c in self.CASES:
            with self.subTest(env=c):
                env = self.case(c)
                log, exported = self.shell(**env)
                got = self.python(**env)
                self.assertEqual(log, got["log"])
                self.assertEqual(exported["SESSIONVIEW_STATE"], got["state"])
                # the fixed point: the answer, fed back in, is the answer
                again = {k: exported[k] for k in ("SESSIONVIEW_STATE", "SESSIONVIEW_LOG") if k in exported}
                if "HOME" in env:
                    again["HOME"] = env["HOME"]
                self.assertEqual(self.shell(**again)[0], log)
                self.assertEqual(self.python(**again), got)

    def test_SESSIONVIEW_LOG_is_exported_only_when_given(self):
        for c in self.CASES:
            with self.subTest(env=c):
                env = self.case(c)
                _, exported = self.shell(**env)
                if env.get("SESSIONVIEW_LOG"):
                    self.assertEqual(exported.get("SESSIONVIEW_LOG"), env["SESSIONVIEW_LOG"])
                else:
                    self.assertNotIn("SESSIONVIEW_LOG", exported)

    def test_the_shell_makes_the_default_log_dir_0700(self):
        self.shell()
        self.assertEqual(mode(self.ld), 0o700)
        self.assertFalse(os.path.exists(self.new), "the shell wrote the log")

    def test_no_log_leak_into_a_child_that_names_its_own_state(self):
        # a child of an entry script's environment (the default resolved and
        # exported) that sets only SESSIONVIEW_STATE logs in that dir
        _, exported = self.shell()
        child = {k: v for k, v in exported.items() if k.startswith("SESSIONVIEW_")}
        state = os.path.join(self.home, "child-state")
        child["SESSIONVIEW_STATE"] = state
        got = self.python("hello", **child)
        self.assertEqual(got["log"], os.path.join(state, "sessionview.log"))
        self.assertFalse(os.path.exists(self.new), "the child wrote the default log")


class FrameHop(HijackCase):
    """The frame re-runs itself across `detach-client -E`, which runs with
    the CLIENT's environment. A log the user gave the frame survives the hop,
    and a log they did not give is never handed to the frame server."""

    def frame_env(self, name):
        r = self.tmux("show-environment", "-g", name, sock=self.frame_sock)
        return r.stdout.strip() if r.returncode == 0 else ""

    def start_frame(self, *pre):
        a = self.client("A")
        rc, err = self.run_in_pane("hop", [*pre, FRAME], session="A")
        self.assertEqual(rc, 0, err)
        self.assertTrue(wait_for(lambda: a.tty in self.clients_on(sock=self.frame_sock)),
                        "the frame never took the terminal")

    def test_a_given_log_survives_the_hop(self):
        mine = os.path.join(self.home, "mine.log")
        self.start_frame("env", f"SESSIONVIEW_LOG={mine}")
        self.assertEqual(self.frame_env("SESSIONVIEW_LOG"), f"SESSIONVIEW_LOG={mine}")

    def test_no_log_given_none_reaches_the_frame_server(self):
        self.start_frame()
        self.assertNotIn("SESSIONVIEW_LOG=", self.frame_env("SESSIONVIEW_LOG"))


if __name__ == "__main__":
    unittest.main()
