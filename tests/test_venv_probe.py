"""The probe's venv step: a wheel copy runs on the venv that installed it (SV-172).

A stranger who follows the kit's install (`uv tool install --python 3.14 ...`)
has no python3.11+ on PATH, only the OS's 3.9. The console scripts set
SESSIONVIEW_PYTHON, but every other route runs a bin/ tool directly: the plugin,
a hand-made link, a binding in a tmux server that predates sessionview. Each of
those probes. So the probe's step 2, in lib/python.sh and the three trampolines,
is the venv that installed the copy: when the script's REAL path lies under
*/site-packages/sessionview/_data/*, walk up to the first pyvenv.cfg and take its
bin/python3 if it is 3.11+. A checkout never matches, so it keeps the PATH order.

Every test here REMOVES the named key SESSIONVIEW_PYTHON, which scratch_env()
sets for the rest of the suite: these tests are the ones that exercise the probe.
The PATH they run under is a stub dir first, then /usr/bin:/bin. The stubs are
python3 and python3.11 .. python3.14, each exiting non-zero, so no PATH Python
can pass the >= 3.11 check (on macOS /usr/bin/python3 is 3.9 behind them anyway).
A tool that runs at all ran on the interpreter the test planted.

The interpreters the tests plant are WRAPPERS: a sh script that appends its argv
to a log and execs the suite's own Python. The log names which interpreter ran
which tool, so the assertion is "this wrapper ran bin/X", never a guess.
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import unittest

from tests import support

#: The four probe copies. The block between the markers is the same text in each.
SITES = ("lib/python.sh", "bin/sessionview-config", "bin/tmux-sidebar",
         "lib/sessionview-config-screen")
TRAMPOLINES = SITES[1:]
BLOCK_RX = re.compile(r"^# >>> venv probe.*?^# <<< venv probe$", re.M | re.S)
PATH_LOOP_RX = re.compile(r"\bfor (?:p|_sv_p) in python3\.")
#: What the wheel ships under sessionview/_data (pyproject.toml force-include).
DATA_DIRS = ("bin", "lib", "config", "tmux", "plugins")
NEEDS = "needs Python 3.11 or newer"


def read(rel):
    with open(os.path.join(support.REPO, rel), encoding="utf-8") as f:
        return f.read()


def executable(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def wrapper(path, log, tag):
    """An interpreter at PATH that logs `TAG argv...` to LOG, then runs the
    suite's Python with that argv."""
    executable(path, "#!/bin/sh\n"
                     f'printf "%s\\n" "{tag} $*" >> "{log}"\n'
                     f'exec "{sys.executable}" "$@"\n')


def failing(path):
    """A python name that exits non-zero for any argv: it fails the >= 3.11
    check, as Apple's 3.9 does, and runs nothing."""
    executable(path, "#!/bin/sh\nexit 1\n")


def strict_stubs(bindir):
    """python3 and python3.11 .. python3.14, all failing, in BINDIR."""
    os.makedirs(bindir, exist_ok=True)
    for name in ("python3", "python3.11", "python3.12", "python3.13", "python3.14"):
        failing(os.path.join(bindir, name))


def ran(log, tag, tool):
    """True when LOG has a line where interpreter TAG was given TOOL (a path
    ending in /TOOL) as its script."""
    try:
        with open(log, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return False
    for line in lines:
        words = line.split()
        if len(words) >= 2 and words[0] == tag and words[1].endswith("/" + tool):
            return True
    return False


def fake_wheel(base, python=None):
    """A uv-tool-shaped venv under BASE holding a copy of this checkout's data
    dirs, as a wheel install lays them out. Returns (venv, data). The venv's
    bin/python3 is PYTHON (a callable that writes it), else absent."""
    # Real path: the probe resolves symlinks (macOS's /var is /private/var).
    venv = os.path.join(os.path.realpath(base), "tools", "sessionview")
    data = os.path.join(venv, "lib", "python3.14", "site-packages", "sessionview", "_data")
    os.makedirs(os.path.join(venv, "bin"))
    with open(os.path.join(venv, "pyvenv.cfg"), "w", encoding="utf-8") as f:
        f.write(f"home = {os.path.dirname(sys.executable)}\n")
    for d in DATA_DIRS:
        shutil.copytree(os.path.join(support.REPO, d), os.path.join(data, d), symlinks=True)
    if python:
        python(os.path.join(venv, "bin", "python3"))
    return venv, data


class ProbeEnv(unittest.TestCase):
    """A scratch HOME, SESSIONVIEW_PYTHON removed, PATH = failing stubs first."""

    def setUp(self):
        ctx = support.scratch_env()
        self.env, self.home = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        self.env.pop("SESSIONVIEW_PYTHON")
        self.stubs = os.path.join(self.home, "stubs")
        strict_stubs(self.stubs)
        self.env["PATH"] = os.pathsep.join([self.stubs, "/usr/bin", "/bin"])
        self.log = os.path.join(self.home, "interp.log")
        # cwd outside every checkout and store: a layer walk-up finds nothing real.
        self.cwd = os.path.join(self.home, "work")
        os.mkdir(self.cwd)

    def run_sh(self, argv, timeout=30, stdin=subprocess.DEVNULL):
        """Run ARGV directly, as a plugin or a link does: never through
        support.run, which hands a python tool the suite's interpreter."""
        return subprocess.run(argv, env=self.env, cwd=self.cwd, capture_output=True,
                              text=True, timeout=timeout, stdin=stdin)


class Drift(unittest.TestCase):
    def blocks(self):
        out = {}
        for rel in SITES:
            found = BLOCK_RX.findall(read(rel))
            self.assertEqual(len(found), 1, f"{rel}: {len(found)} venv probe blocks, want 1")
            out[rel] = found[0]
        return out

    def test_the_block_is_the_same_text_in_all_four_copies(self):
        blocks = self.blocks()
        want = blocks[SITES[0]]
        for rel in SITES[1:]:
            with self.subTest(site=rel):
                self.assertTrue(blocks[rel] == want, f"{rel}: the venv probe block drifted from {SITES[0]}")

    def test_the_block_comes_before_the_path_loop(self):
        for rel in SITES:
            with self.subTest(site=rel):
                text = read(rel)
                block = BLOCK_RX.search(text)
                loop = PATH_LOOP_RX.search(text)
                self.assertIsNotNone(block, f"{rel}: no venv probe block")
                self.assertIsNotNone(loop, f"{rel}: no PATH loop")
                self.assertLess(block.end(), loop.start(), f"{rel}: the venv step is not before PATH")

    def test_the_block_is_guarded_by_the_wheel_layout(self):
        block = self.blocks()[SITES[0]]
        self.assertIn("*/site-packages/sessionview/_data/*)", block)
        self.assertIn('readlink -f "$0"', block)
        self.assertIn("pyvenv.cfg", block)
        self.assertIn("sys.version_info < (3, 11)", block)

    def test_the_regex_sees_a_drifted_copy(self):
        # A drift test that matched nothing would pass vacuously.
        a = "# >>> venv probe x\nA\n# <<< venv probe\n"
        b = "# >>> venv probe x\nB\n# <<< venv probe\n"
        self.assertNotEqual(BLOCK_RX.findall(a), BLOCK_RX.findall(b))
        self.assertEqual(len(BLOCK_RX.findall(a)), 1)

    def test_no_entry_gates_on_a_bare_python3(self):
        # newtab gated the picker on `command -v python3` and autostart set
        # PY from it: Apple's 3.9 passed both (SV-172). They use the probe.
        bare = re.compile(r"command -v python3\b(?!\.)")
        for rel in ("bin/sessionview-newtab", "bin/sessionview-autostart"):
            with self.subTest(site=rel):
                text = read(rel)
                self.assertEqual(bare.findall(text), [], f"{rel} still asks for a bare python3")
                self.assertIn('. "$SESSIONVIEW_ROOT/lib/python.sh"', text)


class WheelCopy(ProbeEnv):
    """The stranger route as a unit test: a fake wheel layout, the tools run
    DIRECTLY, every PATH python failing."""

    def setUp(self):
        super().setUp()
        self.venv, self.data = fake_wheel(self.home, lambda p: wrapper(p, self.log, "VENV"))

    def test_sessionview_config_runs_on_the_venv_python(self):
        r = self.run_sh([os.path.join(self.data, "bin", "sessionview-config"), "get", "project_dirs"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(NEEDS, r.stderr)
        self.assertTrue(ran(self.log, "VENV", "sessionview-config"), "not run on the venv's python3")

    def test_tmux_sidebar_runs_on_the_venv_python(self):
        r = self.run_sh([os.path.join(self.data, "bin", "tmux-sidebar"), "--once"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(NEEDS, r.stderr)
        self.assertTrue(ran(self.log, "VENV", "tmux-sidebar"), "not run on the venv's python3")

    def test_the_config_screen_runs_on_the_venv_python(self):
        r = self.run_sh([os.path.join(self.data, "lib", "sessionview-config-screen"), "--help"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(ran(self.log, "VENV", "sessionview-config-screen"), "not run on the venv's python3")

    def test_a_python_sh_entry_names_the_venv_python(self):
        # sessionview-install sources lib/python.sh and prints what it chose.
        r = self.run_sh([os.path.join(self.data, "bin", "sessionview-install"), "--check"])
        want = os.path.join(self.venv, "bin", "python3")
        rows = [ln for ln in r.stdout.splitlines() if " python " in f" {ln} "]
        self.assertEqual(len(rows), 1, r.stdout)
        self.assertTrue(rows[0].split()[0] == "PASS", rows[0])
        self.assertIn(f"({want})", rows[0])

    def test_a_link_outside_the_venv_resolves_to_the_venv(self):
        # The walk-up starts at the link's TARGET (readlink -f), not the link's dir.
        links = os.path.join(self.home, "links")
        os.mkdir(links)
        for tool in ("sessionview-config", "tmux-sidebar"):
            os.symlink(os.path.join(self.data, "bin", tool), os.path.join(links, tool))
        r = self.run_sh([os.path.join(links, "sessionview-config"), "get", "project_dirs"])
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_sh([os.path.join(links, "tmux-sidebar"), "--once"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(ran(self.log, "VENV", "sessionview-config"))
        self.assertTrue(ran(self.log, "VENV", "tmux-sidebar"))

    def test_an_entry_that_sources_python_sh_takes_the_venv(self):
        # lib/python.sh locates the copy from the SOURCING script's $0.
        script = f'. "{self.data}/lib/python.sh"; printf %s "$SESSIONVIEW_PYTHON"'
        entry = os.path.join(self.data, "bin", "probe-entry")
        executable(entry, f"#!/bin/sh\n{script}\n")
        r = self.run_sh([entry])
        self.assertEqual(r.stdout, os.path.join(self.venv, "bin", "python3"))


class TooOldVenv(ProbeEnv):
    def test_a_venv_python_under_3_11_falls_through_to_path(self):
        _venv, data = fake_wheel(self.home, failing)
        wrapper(os.path.join(self.stubs, "python3.14"), self.log, "PATH")
        r = self.run_sh([os.path.join(data, "bin", "sessionview-config"), "get", "project_dirs"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(ran(self.log, "PATH", "sessionview-config"), "did not fall through to PATH")

    def test_a_venv_with_no_python3_falls_through_to_path(self):
        _venv, data = fake_wheel(self.home, None)
        wrapper(os.path.join(self.stubs, "python3.14"), self.log, "PATH")
        r = self.run_sh([os.path.join(data, "bin", "tmux-sidebar"), "--once"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(ran(self.log, "PATH", "tmux-sidebar"))


class Checkout(ProbeEnv):
    """The checkout route is the PATH route, as it was (SV-171's order)."""

    def test_the_checkout_takes_path_python3_14(self):
        wrapper(os.path.join(self.stubs, "python3.14"), self.log, "PATH")
        for tool, args in (("sessionview-config", ["get", "project_dirs"]), ("tmux-sidebar", ["--once"])):
            with self.subTest(tool=tool):
                r = self.run_sh([os.path.join(support.BIN, tool), *args])
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(ran(self.log, "PATH", tool))

    def test_a_checkout_under_a_pyvenv_cfg_still_takes_path(self):
        # A checkout that happens to sit inside a tree with a pyvenv.cfg above
        # it: no site-packages/sessionview/_data in its path, so no venv step.
        tree = os.path.join(self.home, "venvish")
        os.makedirs(os.path.join(tree, "bin"))
        with open(os.path.join(tree, "pyvenv.cfg"), "w", encoding="utf-8") as f:
            f.write("home = /nonexistent\n")
        wrapper(os.path.join(tree, "bin", "python3"), self.log, "VENV")
        copy = os.path.join(tree, "src", "sessionview")
        for d in DATA_DIRS:
            shutil.copytree(os.path.join(support.REPO, d), os.path.join(copy, d), symlinks=True)
        wrapper(os.path.join(self.stubs, "python3.14"), self.log, "PATH")
        r = self.run_sh([os.path.join(copy, "bin", "sessionview-config"), "get", "project_dirs"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(ran(self.log, "PATH", "sessionview-config"))
        self.assertFalse(ran(self.log, "VENV", "sessionview-config"))

    def test_no_python_3_11_is_still_the_loud_message(self):
        # Not a silent wrong Python: the message and exit 1.
        for rel, args in (("bin/sessionview-config", ["get", "project_dirs"]),
                          ("bin/tmux-sidebar", ["--once"]),
                          ("lib/sessionview-config-screen", ["--help"])):
            with self.subTest(tool=rel):
                r = self.run_sh([os.path.join(support.REPO, rel), *args])
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn(NEEDS, r.stderr)
                self.assertIn("brew install python@3.14", r.stderr)

    def test_no_python_3_11_python_sh_sets_nothing(self):
        script = '. "$1/lib/python.sh"; printf "[%s]" "${SESSIONVIEW_PYTHON:-}"'
        r = self.run_sh(["/bin/sh", "-c", script, os.path.join(support.BIN, "x"), support.REPO])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "[]")


class NewtabGate(ProbeEnv):
    """[+] opens the window picker (tmux-sidebar, Python 3.11+) only when the
    probe found a Python; a 3.9 python3 on PATH must not pass the gate."""

    def setUp(self):
        super().setUp()
        # A tmux that names the popup's session, so the gate is reached.
        executable(os.path.join(self.stubs, "tmux"), "#!/bin/sh\necho alpha\n")
        self.env["TMUX"] = "/nonexistent/sock,1,7"

    def popup(self, newtab):
        # Esc at the plain name prompt: exit 1 without making a tab.
        return subprocess.run(["/bin/bash", newtab, "--popup", self.cwd], env=self.env, cwd=self.cwd,
                              input="\x1b", capture_output=True, text=True, timeout=30)

    def test_a_3_9_python3_does_not_pass_the_gate(self):
        r = self.popup(os.path.join(support.BIN, "sessionview-newtab"))
        self.assertIn("new tab", r.stdout)
        self.assertNotIn(NEEDS, r.stderr)

    def test_a_probe_python_opens_the_picker(self):
        wrapper(os.path.join(self.stubs, "python3.14"), self.log, "PATH")
        # The picker itself needs a terminal; that it was started is the point.
        self.popup(os.path.join(support.BIN, "sessionview-newtab"))
        self.assertTrue(ran(self.log, "PATH", "tmux-sidebar"), "the picker was not opened")

    def test_a_wheel_copy_opens_the_picker_on_the_venv_python(self):
        _venv, data = fake_wheel(self.home, lambda p: wrapper(p, self.log, "VENV"))
        self.popup(os.path.join(data, "bin", "sessionview-newtab"))
        self.assertTrue(ran(self.log, "VENV", "tmux-sidebar"), "the picker was not opened")


class AutostartPython(ProbeEnv):
    """autostart's `running` check reads `session list --json` with PY: the
    probe's Python, never a bare python3 (which fails here, like a 3.9)."""

    def test_running_uses_the_probe_python(self):
        wrapper(os.path.join(self.stubs, "python3.14"), self.log, "PATH")
        executable(os.path.join(self.stubs, "session"),
                   "#!/bin/sh\necho '[{\"agent\": \"alice\", \"name\": \"seat-1\"}]'\n")
        r = self.run_sh([os.path.join(support.BIN, "sessionview-config"), "set", "autostart_agent", "alice"])
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_sh([os.path.join(support.BIN, "sessionview-autostart"), "--status"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("already running: seat-1", r.stdout)


if __name__ == "__main__":
    unittest.main()
