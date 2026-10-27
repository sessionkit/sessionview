"""Asking never acts: every verb answers -h/--help, and the dispatcher
--version, without doing anything else (SV-197).

In the 0.3.0 wheel four verbs ACTED on --help: `sidebar --help` launched the
sidebar (its supervisor dropped the flag and reloaded forever), `install
--help` ran the requirements check (in a checkout it also linked every tool
into ~/.local/bin), `autostart --help` decided whether to start an agent, and
`from --help` ran the resolver. `terminal --help` ran its query too. Even the
dispatcher's own --help made ~/.local/state/sessionview (lib/state.sh) before
it printed a word. `--version` was refused everywhere.

"Starts nothing" is measured, not assumed. Each call runs:
- under a scratch HOME and a scratch PREFIX, with TMUX_TMPDIR in the same
  scratch root, and every path under those three is listed, DIRECTORIES too,
  before and after: the two lists must be equal;
- with a RECORDER first on PATH for tmux, every python3.x, pgrep, neomutt,
  notmuch, session, tm, message, osacompile, open and uv. A recorder writes
  its name and argv to a log outside the scratch root and exits 1. The log
  must stay empty, so no tmux server or client, no TUI, no requirements
  check and no Python probe ran (a recorder tmux cannot start a server);
- with SESSIONVIEW_PYTHON set to a recording wrapper around the suite's own
  interpreter. Only `config`, a Python tool, may run it, and only on itself.

Every verb the dispatcher routes is read from bin/sessionview's own case, so
a verb added later is covered without editing this file. Each call is in its
own process group with a timeout; one that does not exit (the 0.3.0
sidebar's supervisor loop) is killed by group and reported.
"""
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import tomllib
import unittest

from tests import support

DISPATCHER = os.path.join(support.BIN, "sessionview")
RECORDED = ("tmux", "python3", "python3.11", "python3.12", "python3.13", "python3.14",
            "pgrep", "neomutt", "notmuch", "session", "tm", "message", "osacompile",
            "open", "uv")
TIMEOUT = 15


def routed_verbs(path=DISPATCHER):
    """The verbs bin/sessionview routes: the word arms of its FIRST case, the
    one that runs before lib/state.sh (SV-200 moved the routing into it, so
    a routed verb is exec'd before the state dir is made)."""
    with open(path) as f:
        text = f.read()
    start = text.index('case "${1:-}" in\n')
    body = text[start:text.index("\nesac\n", start)]
    verbs = []
    for m in re.finditer(r"^  ([a-z][a-z|-]*)\)", body, re.M):
        verbs += m.group(1).split("|")
    return verbs


def tools():
    """Every tool in bin/, read from the directory, so a new one is covered
    without editing this file."""
    return sorted(n for n in os.listdir(support.BIN)
                  if os.path.isfile(os.path.join(support.BIN, n))
                  and os.access(os.path.join(support.BIN, n), os.X_OK))


def tree(*roots):
    """Every path under ROOTS, directories included (repro-001 counted only
    files and links, and missed a mkdir)."""
    out = set()
    for root in roots:
        for d, dirs, files in os.walk(root):
            for n in dirs + files:
                out.add(os.path.relpath(os.path.join(d, n), os.path.dirname(root)))
    return out


class Sandbox:
    """A scratch root (home, prefix, tmux) and a recorder dir, outside it."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="sessionview-verb-help-",
                                                ignore_cleanup_errors=True)
        base = self._tmp.name
        self.root = os.path.join(base, "root")
        self.home = os.path.join(self.root, "home")
        self.prefix = os.path.join(self.root, "prefix")
        self.tmux = os.path.join(self.root, "tmux")
        for d in (self.home, self.prefix, self.tmux):
            os.makedirs(d)
        self.shims = os.path.join(base, "shims")
        os.makedirs(self.shims)
        self.log = os.path.join(base, "calls.log")
        for name in RECORDED:
            self._shim(name, f"printf '%s\\n' {shlex.quote(name)}\" $*\" >> {shlex.quote(self.log)}\nexit 1\n")
        self.python = self._shim("sv-python", (
            f"printf '%s\\n' \"python $*\" >> {shlex.quote(self.log)}\n"
            f"exec {shlex.quote(sys.executable)} -B \"$@\"\n"))

    def _shim(self, name, body):
        p = os.path.join(self.shims, name)
        with open(p, "w") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(p, 0o755)
        return p

    def env(self):
        env = {k: os.environ[k] for k in support.KEEP if k in os.environ}
        env["PATH"] = self.shims + os.pathsep + env.get("PATH", "/usr/bin:/bin")
        env.update(HOME=self.home, PREFIX=self.prefix, TMUX_TMPDIR=self.tmux,
                   USER="probe", SESSIONVIEW_PYTHON=self.python)
        return env

    def calls(self):
        try:
            with open(self.log) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def run(self, argv):
        """(rc, stdout, stderr, new paths, calls) for ARGV; rc None = it did
        not exit in TIMEOUT and its process group was killed."""
        before = tree(self.home, self.prefix, self.tmux)
        if os.path.exists(self.log):
            os.unlink(self.log)
        p = subprocess.Popen(argv, env=self.env(), cwd=self.root, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             start_new_session=True)
        try:
            out, err = p.communicate(timeout=TIMEOUT)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)       # this call's own group, nobody else's
            out, err = p.communicate()
            rc = None
        after = tree(self.home, self.prefix, self.tmux)
        return rc, out, err, sorted(after ^ before), self.calls()

    def cleanup(self):
        self._tmp.cleanup()


def fresh_run(argv):
    """ARGV in a Sandbox of its own (SV-200 F2): one call's leftovers can
    never hide, or be blamed on, the next call's."""
    box = Sandbox()
    try:
        return box.run(argv)
    finally:
        box.cleanup()


def shown(argv):
    return " ".join(os.path.relpath(a, support.REPO) if a.startswith(support.REPO) else a
                    for a in argv)


class AskingNeverActs(unittest.TestCase):
    def assert_quiet(self, argv, name, python_ok=None):
        """ARGV exits 0, prints usage naming NAME, and touches nothing.
        PYTHON_OK: the one script the Python wrapper may run (config's own).
        Each call gets its own fresh Sandbox, so a failure names its verb."""
        rc, out, err, changed, calls = fresh_run(argv)
        what = shown(argv)
        self.assertIsNotNone(rc, f"{what}: did not exit in {TIMEOUT}s (a TUI or a loop); "
                                 f"stdout {out[-300:]!r}")
        self.assertEqual(rc, 0, f"{what}: exit {rc}; stderr {err[-300:]!r}")
        if python_ok:
            calls = [c for c in calls if not (c.startswith("python ") and python_ok in c)]
        self.assertEqual(calls, [], f"{what}: ran {calls}")
        self.assertEqual(changed, [], f"{what}: touched {changed}")
        self.assertIn(name, out, f"{what}: no usage naming {name}; stdout {out[:300]!r}")
        self.assertGreaterEqual(len(out.strip().splitlines()), 3, f"{what}: usage too short: {out!r}")
        self.assertNotIn("requirements:", out, f"{what}: ran the requirements check")

    def test_the_routing_list_is_read(self):
        verbs = routed_verbs()
        for v in ("install", "autostart", "from", "terminal", "sidebar", "config"):
            self.assertIn(v, verbs)

    def test_dispatcher_help(self):
        for flag in ("-h", "--help", "help"):
            with self.subTest(flag=flag):
                self.assert_quiet([DISPATCHER, flag], "sessionview")

    def test_every_routed_verb_help_through_the_dispatcher(self):
        for verb in routed_verbs():
            name = "tmux-sidebar" if verb == "sidebar" else f"sessionview-{verb}"
            ok = "sessionview-config" if verb == "config" else None
            for flag in ("--help", "-h"):
                with self.subTest(verb=verb, flag=flag):
                    self.assert_quiet([DISPATCHER, verb, flag], name, python_ok=ok)

    def test_every_routed_verb_help_called_directly(self):
        for verb in routed_verbs():
            tool = "tmux-sidebar" if verb == "sidebar" else f"sessionview-{verb}"
            ok = "sessionview-config" if verb == "config" else None
            for flag in ("--help", "-h"):
                with self.subTest(tool=tool, flag=flag):
                    self.assert_quiet([os.path.join(support.BIN, tool), flag], tool, python_ok=ok)

    def test_frame_help_makes_no_state_dir(self):
        for flag in ("--help", "-h"):
            with self.subTest(flag=flag):
                self.assert_quiet([os.path.join(support.BIN, "sessionview-frame"), flag],
                                  "sessionview-frame")


def help_argv(argv):
    """The --help call that answers for ARGV's tool: the same words with the
    flag swapped for --help."""
    return argv[:-1] + ["--help"]


class UnknownFlagRefuses(unittest.TestCase):
    """An unknown flag refuses (SV-200): exit 2, nothing on stdout, ONE
    reason line on stderr naming the flag, then the tool's COMPLETE usage,
    byte for byte what its --help prints. Nothing is made under the scratch
    HOME, PREFIX or tmux dir, and no recorder runs: no link, no TUI, no tmux,
    no requirements check, no Python probe. `--version` on a verb is such a
    flag (only the dispatcher's own --version is known)."""

    FLAGS = ("--bogus", "--version")

    def assert_refuses(self, argv, python_ok=None, help=None):
        what = shown(argv)
        help = help or help_argv(argv)
        hrc, usage, herr, _, _ = fresh_run(help)
        self.assertEqual(hrc, 0, f"{shown(help)}: exit {hrc}; stderr {herr[-300:]!r}")
        self.assertGreaterEqual(len(usage.strip().splitlines()), 3, f"{what}: usage too short: {usage!r}")
        rc, out, err, changed, calls = fresh_run(argv)
        self.assertIsNotNone(rc, f"{what}: did not exit in {TIMEOUT}s (a TUI or a loop)")
        if python_ok:
            calls = [c for c in calls if not (c.startswith("python ") and python_ok in c)]
        self.assertEqual(calls, [], f"{what}: ran {calls}")
        self.assertEqual(changed, [], f"{what}: touched {changed}")
        self.assertEqual(rc, 2, f"{what}: exit {rc}; stderr {err[-300:]!r}")
        self.assertEqual(out, "", f"{what}: printed on stdout")
        first, _, rest = err.partition("\n")
        self.assertIn(argv[-1], first, f"{what}: the reason line does not name the flag: {first!r}")
        self.assertEqual(rest, usage, f"{what}: stderr after the reason is not the whole --help text")

    def test_the_tool_list_is_read(self):
        self.assertIn("sessionview-install", tools())
        self.assertIn("tmux-sidebar", tools())

    def test_every_routed_verb_through_the_dispatcher(self):
        for verb in routed_verbs():
            ok = "sessionview-config" if verb == "config" else None
            for flag in self.FLAGS:
                with self.subTest(verb=verb, flag=flag):
                    self.assert_refuses([DISPATCHER, verb, flag], python_ok=ok)

    def test_every_tool_called_directly(self):
        for tool in tools():
            ok = "sessionview-config" if tool == "sessionview-config" else None
            for flag in self.FLAGS:
                if tool == "sessionview" and flag == "--version":
                    continue                     # the dispatcher's own, answered
                with self.subTest(tool=tool, flag=flag):
                    self.assert_refuses([os.path.join(support.BIN, tool), flag], python_ok=ok)


    def test_the_sidebar_picker_takes_only_a_kind_it_knows(self):
        # KIND is one of three words: anything else, a flag included, used to
        # reach Python, which made the state dir and died on a traceback.
        tool = os.path.join(support.BIN, "tmux-sidebar")
        for argv in (["--pick", "--bogus"], ["--pick", "--version"], ["--pick", "nosuch"],
                     ["--pick", "windows", "S", "--bogus"]):
            with self.subTest(argv=argv):
                self.assert_refuses([tool, *argv], help=[tool, "--help"])


    def test_a_flag_in_an_operand_slot_refuses(self):
        # A SOCK, SESSION, NAME, fresh-window or DIR that starts with - is a
        # flag in a word's slot, and a word after DIR is one the grammar does
        # not name: each once reached config, tmux or `session`. NAME - (a
        # plain claude) and a DIR after `--` stay legal.
        cases = {
            "sessionview-autostart": (["--status", "--bogus"], ["--status", "sock", "--version"],
                                      ["--start", "--bogus"], ["--start", "claude", "--bogus"],
                                      ["--start", "-", "sock", "--bogus"], ["nosock", "--bogus"],
                                      ["nosock", "--version"],
                                      ["nosock", "nosess", "--fresh-window", "--bogus"]),
            "sessionview-newtab": (["foo", "--bogus"], ["", "--version"], ["--popup", "--bogus"],
                                   ["foo", "/tmp", "--bogus"], ["--popup", "/tmp", "--bogus"],
                                   ["--", "foo", "/tmp", "--bogus"]),
        }
        for tool, argvs in cases.items():
            path = os.path.join(support.BIN, tool)
            for argv in argvs:
                with self.subTest(tool=tool, argv=argv):
                    self.assert_refuses([path, *argv], help=[path, "--help"])


def header_usage(path):
    """What a sh tool's -h must print, read from its header WITHOUT sed: from
    line 2 to the `# (end of usage)` marker or the first line that is not a
    comment, comment marks stripped. Never a line number."""
    out = []
    with open(path) as f:
        lines = f.read().split("\n")
    for line in lines[1:]:
        if line == "# (end of usage)" or not line.startswith("#"):
            break
        out.append(re.sub(r"^# ?", "", line))
    return "\n".join(out) + "\n"


class HelpIsComplete(unittest.TestCase):
    """Each --help is the whole usage: a range read by line number cut the
    frame's help mid-sentence once its header grew."""

    def test_every_sh_tool_prints_its_whole_usage(self):
        for tool in tools():
            path = os.path.join(support.BIN, tool)
            if support.script_kind(path) not in ("sh", "bash"):
                continue                         # config, tmux-sidebar: Python
            with self.subTest(tool=tool):
                rc, out, err, _, _ = fresh_run([path, "--help"])
                self.assertEqual(rc, 0, err)
                self.assertEqual(out, header_usage(path))

    def test_no_usage_range_is_a_line_number(self):
        for tool in tools():
            with open(os.path.join(support.BIN, tool), encoding="utf-8") as f:
                text = f.read()
            with self.subTest(tool=tool):
                self.assertIsNone(re.search(r"sed -n '[0-9]+,[0-9]+p' \"\$0\"", text))

    def test_the_dispatcher_usage_names_every_routed_verb(self):
        rc, out, err, _, _ = fresh_run([DISPATCHER, "--help"])
        self.assertEqual(rc, 0, err)
        for verb in routed_verbs():
            with self.subTest(verb=verb):
                self.assertRegex(out, rf"(?m)^  sessionview {re.escape(verb)} ")


class RoutedVerbsNeedNoInheritedEnv(unittest.TestCase):
    """The dispatcher execs a routed verb BEFORE lib/state.sh and lib/python.sh,
    so the verb inherits no SESSIONVIEW_PYTHON or SESSIONVIEW_STATE from it.
    Each still works with both scrubbed: a verb that needs one sets it itself.
    The Python probe finds the suite's own interpreter through a plain
    python3.14 on PATH; the other recorders stay."""

    def via(self, *args):
        """ARGS through the dispatcher, in a Sandbox of its own (one call's
        state dir can never pass the next call's check): (rc, out, err, box)."""
        box = Sandbox()
        self.addCleanup(box.cleanup)
        for n in os.listdir(box.shims):
            if n.startswith("python") or n == "sv-python":
                os.unlink(os.path.join(box.shims, n))
        box._shim("python3.14", f"exec {shlex.quote(sys.executable)} \"$@\"\n")
        box._shim("message", 'mkdir -p "$HOME/box" && echo "$HOME/box"\n')
        env = box.env()
        env.pop("SESSIONVIEW_PYTHON")
        self.assertNotIn("SESSIONVIEW_STATE", env)
        box.env = lambda: env
        rc, out, err, _, _ = box.run([DISPATCHER, *args])
        return rc, out, err, box

    @staticmethod
    def state(box):
        return os.path.join(box.home, ".sessionkit", "view", "state")

    def test_each_routed_verb_works(self):
        cases = {
            "config": (["path"], 0, lambda home: os.path.join(home, ".sessionkit", "view", "settings", "view.json") + "\n"),
            "autostart": (["--status"], 0, "autostart_agent=ask"),
            "terminal": ([], 0, None),
            "usermail": (["--print"], 0, "socket=default session=mail"),
            "from": ([], 0, "probe\n"),
            "sidebar-toggle": (["--frame", "nosuch:F", "--show"], 0, "sidebar already shown"),
            "messages": (["demo", "--print"], 0, "box=demo folder="),
            "session": (["demo", "--print"], 0, None),
            "install": (["--check"], None, "requirements:"),
        }
        self.assertEqual(sorted(cases), sorted(v for v in routed_verbs() if v != "sidebar"))
        for verb, (args, want_rc, want_out) in cases.items():
            with self.subTest(verb=verb):
                rc, out, err, box = self.via(verb, *args)
                if want_rc is not None:
                    self.assertEqual(rc, want_rc, err[-300:])
                if callable(want_out):
                    want_out = want_out(box.home)
                if want_out is not None:
                    self.assertIn(want_out, out, err[-300:])
                self.assertNotIn("needs Python 3.11", err)

    def test_install_finds_a_python_itself(self):
        rc, out, err, _ = self.via("install", "--check")
        self.assertRegex(out, r"(PASS|WARN) +python 3\.1[1-9]")

    def test_session_and_messages_make_their_own_state_dir(self):
        for verb in ("session", "messages"):
            with self.subTest(verb=verb):
                rc, out, err, box = self.via(verb, "demo", "--print")
                self.assertEqual(rc, 0, err[-300:])
                self.assertTrue(os.path.isdir(self.state(box)), f"{verb} made no state dir")

    def test_the_sidebar_arm_still_sets_both_up(self):
        # No tty: tmux-sidebar draws once, exits 0, and the supervisor redraws
        # until the run is killed. One drawn frame and the state dir are the
        # proof that the arm found a Python and made the state dir.
        rc, out, err, box = self.via("sidebar")
        self.assertIsNone(rc)
        self.assertIn("mail", out, err[-300:])
        self.assertTrue(os.path.isdir(self.state(box)))


class RealUsageStillWorks(unittest.TestCase):
    """What legitimately starts with - is not refused."""

    def test_config_set_value_may_start_with_a_dash(self):
        with support.scratch_env() as (env, _):
            r = support.run("sessionview-config", "set", "mail_from", "-x", env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = support.run("sessionview-config", "get", "mail_from", env=env)
            self.assertEqual(r.stdout, "-x\n")

    def test_autostart_decide_form_with_fresh_window(self):
        rc, out, err, changed, calls = fresh_run(
            [os.path.join(support.BIN, "sessionview-autostart"), "nosock", "nosess", "--fresh-window", "@1"])
        self.assertEqual(rc, 0, err)
        self.assertNotIn("unknown argument", err)

    def test_autostart_start_a_plain_claude(self):
        rc, out, err, changed, calls = fresh_run(
            [os.path.join(support.BIN, "sessionview-autostart"), "--start", "-", "nosock", "nosess"])
        self.assertNotIn("unknown argument", err)
        self.assertIn("tmux -L nosock new-window -t =nosess -n claude exec session start -", calls)

    def test_the_sidebar_picker_kinds_reach_python(self):
        # No tty here, so the picker itself fails: the proof is that the sh
        # front passed the argv on to Python unrefused.
        tool = os.path.join(support.BIN, "tmux-sidebar")
        for argv in (["--pick"], ["--pick", "windows", "S"], ["--pick", "sessions"],
                     ["--pick", "agents", "S"]):
            with self.subTest(argv=argv):
                rc, out, err, changed, calls = fresh_run([tool, *argv])
                self.assertNotIn("unknown argument", err)
                self.assertTrue(calls and calls[0].startswith("python ")
                                and calls[0].endswith("tmux-sidebar " + " ".join(argv)), calls)

    def test_autostart_status_still_takes_sock_and_session(self):
        rc, out, err, changed, calls = fresh_run(
            [os.path.join(support.BIN, "sessionview-autostart"), "--status", "nosock", "nosess"])
        self.assertNotIn("unknown argument", err)
        self.assertTrue(any("sessionview-config get autostart_agent" in c for c in calls), calls)

    def test_newtab_takes_a_name_that_starts_with_a_dash_after_double_dash(self):
        support.require_tmux()
        with support.private_tmux("newtab-dash") as pt, tempfile.TemporaryDirectory() as d:
            r = pt.tmux("new-session", "-d", "-s", "demo", "-c", d)
            self.assertEqual(r.returncode, 0, r.stderr)
            path = pt.tmux("display-message", "-p", "-t", "=demo:", "#{socket_path}").stdout.strip()
            sid = pt.tmux("display-message", "-p", "-t", "=demo:", "#{session_id}").stdout.strip()
            env = pt.env()
            env.update(HOME=d, TMUX=f"{path},0,{sid.lstrip('$')}")
            r = subprocess.run([os.path.join(support.BIN, "sessionview-newtab"), "--", "-x", d],
                               env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("-x", [n for _, n, _ in pt.windows("demo")])


class Version(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)

    def test_checkout_prints_the_pyproject_version(self):
        with open(os.path.join(support.REPO, "pyproject.toml"), "rb") as f:
            want = tomllib.load(f)["project"]["version"]
        rc, out, err, changed, calls = self.box.run([DISPATCHER, "--version"])
        self.assertEqual((rc, out, err), (0, f"sessionview {want}\n", ""))
        self.assertEqual(calls, [])
        self.assertEqual(changed, [])

    def test_wheel_layout_reads_the_package_version(self):
        # A wheel has no pyproject.toml: bin/ is sessionview/_data/bin, and
        # __version__ is in sessionview/__init__.py, one level above _data.
        pkg = os.path.join(self.box.root, "site", "sessionview")
        os.makedirs(os.path.join(pkg, "_data", "bin"))
        with open(os.path.join(pkg, "__init__.py"), "w") as f:
            f.write('"""stub"""\n__version__ = "9.8.7"\n')
        tool = os.path.join(pkg, "_data", "bin", "sessionview")
        shutil.copy2(DISPATCHER, tool)
        rc, out, err, changed, calls = self.box.run([tool, "--version"])
        self.assertEqual((rc, out, err), (0, "sessionview 9.8.7\n", ""))
        self.assertEqual(calls, [])
        self.assertEqual(changed, [])

    def test_no_version_source_is_an_error_not_a_guess(self):
        lone = os.path.join(self.box.root, "lone", "bin")
        os.makedirs(lone)
        tool = os.path.join(lone, "sessionview")
        shutil.copy2(DISPATCHER, tool)
        rc, out, err, changed, calls = self.box.run([tool, "--version"])
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertIn("no version found", err)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
