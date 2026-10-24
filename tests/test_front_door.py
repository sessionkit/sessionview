"""The front door routes `from` and `sidebar-toggle`: what the docs tell a user
to type works from a package install, not only from a checkout.

The wheel puts four console scripts on PATH (sessionview, sessionview-config,
sessionview-session, sessionview-messages). Every other tool ships as package
data under sessionview/_data/bin, off PATH, so a user reaches it through
`sessionview COMMAND`. The README and docs/configuration.md say
`sessionview from` prints the name mail is sent as; the sidebar-toggle header
says `sessionview sidebar-toggle` hides or shows the sidebar from a shell.

Two layers:
- the checkout's bin/sessionview routes both (fast, no build);
- a wheel built from this checkout, installed into a scratch venv, runs
  `sessionview from` and prints the name (the route a package user has).
  Needs uv on PATH; without it that class is a LOUD skip naming uv.

Programmatic callers (bin/sessionview-send, bin/tmux-send-agent, the tab-bar
binding in tmux/frame.conf) keep calling the tools by path; that is pinned
here too, so a later tidy-up does not route them through the front door.
"""
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests import support

UV_SKIP = "SKIPPED: needs uv, which is not on PATH (to build and install the wheel)"


def front_door(*args, env):
    return support.run("sessionview", *args, env=env)


@contextlib.contextmanager
def isolated(**extra):
    """A scratch HOME and state dir, and tmux pointed at a PRIVATE scratch
    TMUX_TMPDIR (support.private_tmux). Load-bearing: a front door that does
    NOT route a word hands it to the frame as a session name, and the frame
    starts tmux. Without this, the regression this file guards against would
    open a session on the developer's own tmux server."""
    with support.scratch_env(**extra) as (env, home), support.private_tmux("front") as pt:
        env = pt.env(env)
        env["SESSIONVIEW_STATE"] = os.path.join(home, "state")
        try:
            yield env, home
        finally:
            _kill_scratch_servers(pt)


def _kill_scratch_servers(pt):
    """Kill any server a misrouted call started under the scratch TMUX_TMPDIR
    (the frame's own -L name, or a stray default there). Only names found in
    that scratch dir, and only with -L and that TMUX_TMPDIR."""
    if not support.have_tmux():
        return
    sockdir = os.path.join(pt.tmpdir, f"tmux-{os.getuid()}")
    try:
        names = os.listdir(sockdir)
    except FileNotFoundError:
        return
    for name in names:
        subprocess.run(["tmux", "-L", name, "kill-server"], env=pt.env(),
                       capture_output=True, text=True, timeout=30)


class CheckoutFrontDoor(unittest.TestCase):
    """bin/sessionview in this checkout."""

    def test_from_prints_the_name(self):
        with isolated(SESSIONVIEW_FROM="front-door-name") as (env, home):
            r = front_door("from", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.rstrip("\n"), "front-door-name")

    def test_from_matches_the_tool_it_runs(self):
        # The front door adds nothing: same answer as bin/sessionview-from.
        with isolated(USER="login-name") as (env, home):
            env["SESSIONVIEW_CONFIG"] = os.path.join(home, "scratch", "config.json")
            via = front_door("from", env=env)
            direct = support.run("sessionview-from", env=env)
        self.assertEqual(via.returncode, 0, via.stderr)
        self.assertEqual(via.stdout, direct.stdout)
        self.assertEqual(via.stdout.rstrip("\n"), "login-name")

    def test_sidebar_toggle_is_routed(self):
        with isolated() as (env, home):
            r = front_door("sidebar-toggle", "--help", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("sessionview sidebar-toggle --hide | --show", r.stdout)
        # the usage block only, no comment marks
        self.assertNotIn("# ", r.stdout)
        self.assertNotIn("HOW:", r.stdout)

    def test_sidebar_toggle_errors_are_its_own(self):
        # An unknown argument reaches the toggle (exit 2, its own message),
        # never the frame.
        with isolated() as (env, home):
            r = front_door("sidebar-toggle", "--no-such-flag", env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("sessionview-sidebar-toggle: unknown argument", r.stderr)

    def test_help_lists_both_and_prints_the_whole_header(self):
        with isolated() as (env, home):
            r = front_door("-h", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("sessionview from ", r.stdout)
        self.assertIn("sessionview sidebar-toggle ", r.stdout)
        # The sed range must cover the header to its last line, and stop there.
        lines = r.stdout.rstrip("\n").splitlines()
        self.assertTrue(lines[-1].startswith("State: "), lines[-1])
        self.assertTrue(lines[0].startswith("sessionview - a sidebar for tmux"), lines[0])

    def test_docs_name_the_front_door(self):
        for rel in ("README.md", os.path.join("docs", "configuration.md")):
            with self.subTest(doc=rel):
                with open(os.path.join(support.REPO, rel), encoding="utf-8") as f:
                    text = f.read()
                self.assertIn("`sessionview from`", text)
                self.assertNotIn("`sessionview-from`", text)
                self.assertNotIn("bin/sessionview-from`", text)

    def test_programmatic_callers_keep_the_path(self):
        for rel, needle in (("bin/sessionview-send", '"$here/sessionview-from"'),
                            ("bin/tmux-send-agent", '"$here/sessionview-from"'),
                            ("tmux/frame.conf", "$SESSIONVIEW_ROOT/bin/sessionview-sidebar-toggle")):
            with self.subTest(file=rel):
                with open(os.path.join(support.REPO, rel), encoding="utf-8") as f:
                    self.assertIn(needle, f.read())


@unittest.skipUnless(shutil.which("uv"), UV_SKIP)
class WheelFrontDoor(unittest.TestCase):
    """A wheel built from this checkout, installed into a scratch venv: the
    package user's route. Built once for the class."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="sessionview-wheel-")
        base = cls._tmp.name
        # The build tool's own environment (its cache, its index), minus
        # anything that could point at a sessionview install.
        benv = {k: v for k, v in os.environ.items() if not k.startswith(("SESSIONVIEW_", "VIRTUAL_ENV"))}
        dist = os.path.join(base, "dist")
        cls.venv = os.path.join(base, "venv")
        for argv in (["uv", "build", "--wheel", "--out-dir", dist, support.REPO],
                     ["uv", "venv", "-q", "--python", sys.executable, cls.venv]):
            r = subprocess.run(argv, env=benv, capture_output=True, text=True, timeout=300, cwd=base)
            if r.returncode != 0:
                cls._tmp.cleanup()
                raise AssertionError(f"{' '.join(argv)} failed:\n{r.stderr}")
        wheels = [os.path.join(dist, n) for n in os.listdir(dist) if n.endswith(".whl")]
        r = subprocess.run(["uv", "pip", "install", "-q", "--python",
                            os.path.join(cls.venv, "bin", "python"), *wheels],
                           env=benv, capture_output=True, text=True, timeout=300, cwd=base)
        if r.returncode != 0:
            cls._tmp.cleanup()
            raise AssertionError(f"uv pip install failed:\n{r.stderr}")
        cls.script = os.path.join(cls.venv, "bin", "sessionview")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_installed(self, *args, **extra):
        with isolated(**extra) as (env, home):
            # The console script decides the Python, as for a real user.
            env.pop("SESSIONVIEW_PYTHON", None)
            env["PATH"] = os.path.join(self.venv, "bin") + os.pathsep + env.get("PATH", "")
            return subprocess.run([self.script, *args], env=env, capture_output=True,
                                  text=True, timeout=60, cwd=home)

    def test_from_is_not_its_own_command(self):
        # The premise: only the front door is on PATH, so the docs must name it.
        self.assertFalse(os.path.exists(os.path.join(self.venv, "bin", "sessionview-from")))

    def test_sessionview_from_prints_the_env_name(self):
        r = self.run_installed("from", SESSIONVIEW_FROM="x")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "x\n")

    def test_sessionview_from_falls_back_to_the_login_name(self):
        # No env name, no config: the bundled sessionview-config answers
        # nothing and $USER wins.
        r = self.run_installed("from", USER="pkg-user")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "pkg-user\n")

    def test_sessionview_sidebar_toggle_runs(self):
        r = self.run_installed("sidebar-toggle", "--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("sessionview sidebar-toggle", r.stdout)


if __name__ == "__main__":
    unittest.main()
