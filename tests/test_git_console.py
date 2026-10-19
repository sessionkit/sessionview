"""bin/sessionview-session: the git tab's CONSOLE (SV-90).

What it is: a console at the bottom of the git tab, a
pane under lazygit, CWD the repo root, minimised by default; focus expands it
to 20%, unfocus minimises it to one line. Config, not code: a `console: true`
on a `windows` entry (the shipped `git` entry carries it) splits a shell pane
under the tab's own and sizes it with hooks on THAT window only.

Every tmux call is on a private socket (support.private_tmux: `-L sv-test-*`
under a scratch TMUX_TMPDIR); nothing here names or touches a real server.
lazygit is a shim that records its cwd and sleeps, typed BY ITS ABSOLUTE PATH
(the git entry's command, in the scratch home layer): a pane's login shell
re-orders PATH (macOS path_helper), so a bare `lazygit` found the real one.
The test never runs a real lazygit and still sees the command go into pane 0.
"""
import json
import os
import subprocess
import time
import unittest

from tests import support

SHELLS = {"bash", "zsh", "sh", "dash", "fish", "ksh"}

LAZYGIT_SHIM = """#!/bin/sh
pwd -P > "$HOME/lazygit-ran"
exec sleep 600
"""


class ConsoleBase(unittest.TestCase):
    TAG = "gitc"
    SHIM_CONFIG = True      # the home layer's git entry types the shim, not `lazygit`

    def setUp(self):
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self._pt = support.private_tmux(self.TAG)
        self.pt = self._pt.__enter__()
        self.fx = support.StoreFixtures(os.path.join(self.home, "fx"), self.pt)
        self.env = self.fx.env(env)
        self.shim = os.path.join(self.fx.bin, "lazygit")
        with open(self.shim, "w") as f:
            f.write(LAZYGIT_SHIM)
        os.chmod(self.shim, 0o755)
        self.repo = os.path.realpath(os.path.join(self.home, "code", "alpha"))
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", self.repo], check=True, capture_output=True)
        self.store = self.fx.path("fx-bare")
        if self.SHIM_CONFIG:
            self.home_config(windows=self.template_windows())

    def tearDown(self):
        self._pt.__exit__(None, None, None)
        self._scratch.__exit__(None, None, None)

    # -- config -------------------------------------------------------------
    def home_config(self, **keys):
        """Write the HOME layer (SESSIONVIEW_CONFIG) with KEYS; the template stays under it."""
        with open(self.env["SESSIONVIEW_CONFIG"], "w") as f:
            json.dump(keys, f)

    def template_windows(self):
        """The shipped `windows` list, its git command the shim's absolute path."""
        with open(os.path.join(support.CONFIG, "config.json")) as f:
            rows = json.load(f)["windows"]
        for w in rows:
            if w["name"] == "git":
                self.assertEqual(w["command"], "lazygit")
                w["command"] = self.shim
        return rows

    # -- runs ---------------------------------------------------------------
    def build(self, *extra, name="alpha"):
        r = support.run("sessionview-session", name, "--socket", self.pt.sock, "--store", self.store,
                        "--repo", self.repo, *extra, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    # -- reads --------------------------------------------------------------
    def tm(self, *args):
        r = self.pt.tmux(*args)
        self.assertEqual(r.returncode, 0, (args, r.stderr))
        return r.stdout

    def panes(self, target="=alpha:git"):
        """[{index, id, height, active, path, cmd}] of TARGET's panes, in index order."""
        out = []
        for line in self.tm("list-panes", "-t", target, "-F",
                            "#{pane_index}\t#{pane_id}\t#{pane_height}\t#{pane_active}"
                            "\t#{pane_current_path}\t#{pane_current_command}").splitlines():
            i, pid, h, a, path, cmd = line.split("\t")
            out.append(dict(index=int(i), id=pid, height=int(h), active=a == "1",
                            path=os.path.realpath(path), cmd=cmd))
        return out

    def window_height(self, target="=alpha:git"):
        return int(self.tm("display-message", "-p", "-t", target, "#{window_height}").strip())

    def hooks(self, *args):
        """show-hooks ARGS, as a sorted list of the lines that carry a command."""
        r = self.pt.tmux("show-hooks", *args)
        return sorted(line for line in r.stdout.splitlines() if line.strip())

    def settle(self, check, timeout=3.0):
        """Wait for CHECK() to be true: a hook runs on tmux's own loop, after the command returns."""
        end = time.time() + timeout
        while time.time() < end:
            if check():
                return True
            time.sleep(0.05)
        return check()

    def console_height(self, target="=alpha:git"):
        return self.panes(target)[1]["height"]

    def assert_twenty_percent(self, target="=alpha:git"):
        want = self.window_height(target) * 0.20
        ok = self.settle(lambda: abs(self.console_height(target) - want) <= 1)
        self.assertTrue(ok, f"console {self.console_height(target)} rows, want 20% of "
                            f"{self.window_height(target)} = {want:.1f} (+/-1)")

    def assert_one_row(self, target="=alpha:git"):
        ok = self.settle(lambda: self.console_height(target) == 1)
        self.assertTrue(ok, f"console {self.console_height(target)} rows, want 1")


class Build(ConsoleBase):
    """Success criterion 1: two panes, lazygit on top and active, the console a 1-row shell in the repo."""

    def test_two_panes_lazygit_on_top_console_in_repo(self):
        self.build()
        p = self.panes()
        self.assertEqual(len(p), 2, p)
        top, con = p
        self.assertEqual((top["index"], con["index"]), (0, 1))
        self.assertTrue(top["active"], "lazygit lost focus to the console")
        self.assertFalse(con["active"])
        self.assertEqual(con["height"], 1, con)
        self.assertEqual(con["path"], self.repo)
        self.assertIn(con["cmd"], SHELLS, "the console is a plain shell, nothing typed")
        # the tab's command went into pane 0, in the repo
        marker = os.path.join(self.home, "lazygit-ran")
        self.assertTrue(self.settle(lambda: os.path.exists(marker), timeout=5), "lazygit never ran")
        with open(marker) as f:
            self.assertEqual(f.read().strip(), self.repo)
        self.assertTrue(self.settle(lambda: self.panes()[0]["cmd"] == "sleep", timeout=5),
                        f"pane 0 runs {self.panes()[0]['cmd']}, not the lazygit shim")
        self.assertIn(self.panes()[1]["cmd"], SHELLS, "lazygit was typed into the console")

    def test_other_windows_are_one_pane(self):
        self.build()
        for _, n, _ in self.pt.windows("alpha"):
            if n != "git":
                self.assertEqual(len(self.panes(f"=alpha:{n}")), 1, n)


class Sizing(ConsoleBase):
    """Success criterion 2: 20% on select, 1 row on select back, 20% again after a resize."""

    def setUp(self):
        super().setUp()
        self.build()
        self.tm("resize-window", "-t", "=alpha:git", "-x", "100", "-y", "50")
        self.assert_one_row()                   # window-resized with lazygit active: still 1
        self.con = self.panes()[1]["id"]

    def test_select_console_then_back(self):
        self.tm("select-pane", "-t", self.con)
        self.assert_twenty_percent()
        self.assertTrue(self.panes()[1]["active"])
        self.tm("select-pane", "-t", "=alpha:git.0")
        self.assert_one_row()
        self.tm("select-pane", "-t", self.con)  # and again: the hook is not one-shot
        self.assert_twenty_percent()

    def test_resize_with_console_active_keeps_twenty_percent(self):
        self.tm("select-pane", "-t", self.con)
        self.assert_twenty_percent()
        for rows in ("30", "60"):
            self.tm("resize-window", "-t", "=alpha:git", "-y", rows)
            self.assertTrue(self.settle(lambda: abs(self.window_height() - int(rows)) <= 1),
                            f"window is {self.window_height()} rows, asked {rows}")
            self.assert_twenty_percent()

    def test_resize_with_lazygit_active_keeps_one_row(self):
        self.tm("resize-window", "-t", "=alpha:git", "-y", "60")
        self.assert_one_row()

    def test_closed_console_is_quiet(self):
        self.tm("kill-pane", "-t", self.con)
        self.assertEqual(len(self.panes()), 1)
        self.tm("select-pane", "-t", "=alpha:git.0")
        self.tm("resize-window", "-t", "=alpha:git", "-y", "40")
        self.tm("split-window", "-v", "-d", "-t", "=alpha:git")      # a pane of the user's own
        self.tm("select-pane", "-t", "=alpha:git.1")
        time.sleep(0.3)
        msgs = self.tm("show-messages")
        self.assertNotIn("can't find", msgs)
        self.assertNotIn("no such", msgs.lower())
        # The guard held: no resize was aimed at the dead console. The message
        # log records each command a hook runs, newest first, so the lines
        # above the kill-pane are the ones after it.
        after = msgs.split(f'kill-pane -t "{self.con}"')[0]
        self.assertNotIn(f'command: resize-pane -t "{self.con}"', after)
        # And no error was queued. With no client attached, a failed hook
        # command becomes a config error that tmux shows on the NEXT attach
        # (a view-mode panel over the pane). A control-mode attach prints it
        # as `%config-error`. Measured on tmux 3.7c, review of do-001:
        # without the guard this prints "can't find pane: %N".
        att = subprocess.Popen(["tmux", "-L", self.pt.sock, "-C", "attach", "-t", "=alpha"],
                               env=self.pt.env(), stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        time.sleep(0.5)
        out, _ = att.communicate("detach\n", timeout=10)
        self.assertNotIn("%config-error", out)
        self.assertNotIn("can't find", out)
        self.assertTrue(self.pt.alive())


class Scope(ConsoleBase):
    """Success criterion 3: window hooks on the git window only; nothing global."""

    def test_only_the_git_window_has_hooks(self):
        # a server to measure "before" on: the build would otherwise start it
        self.tm("new-session", "-d", "-s", "seed")
        g, wg = self.hooks("-g"), self.hooks("-wg")
        fe = self.tm("show-options", "-gv", "focus-events")
        self.build()
        self.assertEqual(self.hooks("-g"), g, "a global session hook changed")
        self.assertEqual(self.hooks("-wg"), wg, "a global window hook changed")
        self.assertEqual(self.tm("show-options", "-gv", "focus-events"), fe)
        mine = self.hooks("-w", "-t", "=alpha:git")
        self.assertEqual([h.split("[")[0] for h in mine], ["window-pane-changed", "window-resized"], mine)
        for _, n, _ in self.pt.windows("alpha"):
            if n != "git":
                self.assertEqual(self.hooks("-w", "-t", f"=alpha:{n}"), [], n)
        self.assertEqual(self.hooks("-w", "-t", "=seed:0"), [], "another session's window")
        self.assertEqual(self.hooks("-t", "=alpha"), [], "a session hook")


class WindowFlag(ConsoleBase):
    """Success criterion 4: `--window git` into an existing session gives the same tab."""

    def test_window_git_same_shape(self):
        self.tm("new-session", "-d", "-s", "alpha", "-n", "first", "-c", self.repo)
        self.build("--window", "git")
        p = self.panes()
        self.assertEqual(len(p), 2, p)
        self.assertTrue(p[0]["active"])
        self.assertEqual(p[1]["height"], 1)
        self.assertEqual(p[1]["path"], self.repo)
        self.assertEqual(len(self.hooks("-w", "-t", "=alpha:git")), 2)
        self.assertEqual(self.hooks("-w", "-t", "=alpha:first"), [])
        self.tm("resize-window", "-t", "=alpha:git", "-y", "50")
        self.tm("select-pane", "-t", p[1]["id"])
        self.assert_twenty_percent()

    def test_window_without_console_is_one_pane(self):
        self.tm("new-session", "-d", "-s", "alpha", "-n", "first", "-c", self.repo)
        self.build("--window", "repo")
        self.assertEqual(len(self.panes("=alpha:repo")), 1)
        self.assertEqual(self.hooks("-w", "-t", "=alpha:repo"), [])


class NoConsole(ConsoleBase):
    """Success criterion 5: an entry without `console` builds exactly as before."""

    def test_git_without_console_is_one_pane_no_hooks(self):
        rows = self.template_windows()
        for w in rows:
            w.pop("console", None)
        self.home_config(windows=rows)
        self.build()
        self.assertEqual(len(self.panes()), 1)
        self.assertEqual(self.hooks("-w", "-t", "=alpha:git"), [])

    def test_console_on_another_entry(self):
        """Config, not code: the name `git` is not special; `console` on `repo` gives repo one."""
        rows = self.template_windows()
        for w in rows:
            w["console"] = w["name"] == "repo"
        self.home_config(windows=rows)
        self.build()
        self.assertEqual(len(self.panes("=alpha:git")), 1)
        self.assertEqual(len(self.panes("=alpha:repo")), 2)
        self.assertEqual(self.panes("=alpha:repo")[1]["path"], self.repo)

    def test_print_plan_names_the_console_lines_for_git_only(self):
        plan = self.build("--print").stderr
        splits = [line for line in plan.splitlines() if "split-window" in line]
        self.assertEqual(len(splits), 1, plan)
        self.assertIn("split-window -v -d -l 1 -t =alpha:git -c " + self.repo, splits[0])
        hooks = [line for line in plan.splitlines() if "set-hook" in line]
        self.assertEqual(len(hooks), 2, plan)
        for h in hooks:
            self.assertIn("set-hook -w -t =alpha:git ", h)
            self.assertNotIn(" -g", h)
        self.assertEqual(self.pt.sessions(), [], "--print touched the server")
        rows = self.template_windows()
        for w in rows:
            w.pop("console", None)
        self.home_config(windows=rows)
        plan = self.build("--print").stderr
        self.assertNotIn("split-window", plan)
        self.assertNotIn("set-hook", plan)


class ConfigColumn(ConsoleBase):
    """`sessionview-config windows`: console is a TRAILING column; the seven before it do not move."""
    SHIM_CONFIG = False     # the shipped list, as it is

    def rows(self):
        r = support.run("sessionview-config", "windows", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return [line.split("\t") for line in r.stdout.splitlines()]

    def test_shipped_git_carries_console(self):
        rows = self.rows()
        self.assertTrue(all(len(r) == 8 for r in rows), rows)
        self.assertEqual({r[1]: r[7] for r in rows}["git"], "true")
        self.assertEqual({r[7] for r in rows if r[1] != "git"}, {"false"})
        git = next(r for r in rows if r[1] == "git")
        self.assertEqual(git[:7], ["50", "git", "has_repo", "repo", "lazygit", "false", "-"])

    def test_only_a_true_bool_turns_it_on(self):
        self.home_config(windows=[
            {"position": 1, "name": "a", "console": True},
            {"position": 2, "name": "b", "console": "yes"},
            {"position": 3, "name": "c", "console": 1},
            {"position": 4, "name": "d"},
        ])
        self.assertEqual([(r[1], r[7]) for r in self.rows()],
                         [("a", "true"), ("b", "false"), ("c", "false"), ("d", "false")])

    def test_store_windows_key_has_the_column(self):
        r = support.run("sessionview-config", "windows", "--key", "store_windows", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(all(line.split("\t")[7] == "false" for line in r.stdout.splitlines()))


class StoreAdd(ConsoleBase):
    """The store view's add path builds configured windows too: a `console` entry gets its pane there."""

    def test_store_add_path_honours_console(self):
        self.tm("new-session", "-d", "-s", "fx-legacy")
        with open(os.path.join(support.CONFIG, "config.json")) as f:
            rows = json.load(f)["store_windows"]
        for w in rows:
            w["console"] = w["name"] == "scripts"
        self.home_config(store_windows=rows)
        r = support.run("sessionview-session", "fx-legacy", "--store-view", "fx-legacy",
                        "--socket", self.pt.sock, "--store", self.fx.path("fx-legacy"), env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        p = self.panes("=fx-legacy:scripts")
        self.assertEqual(len(p), 2, p)
        self.assertEqual(p[1]["height"], 1)
        self.assertEqual(p[1]["path"], os.path.join(self.fx.path("fx-legacy"), "scripts"))
        self.assertEqual(len(self.panes("=fx-legacy:slipbox")), 1)
        self.assertEqual(len(self.hooks("-w", "-t", "=fx-legacy:scripts")), 2)


if __name__ == "__main__":
    unittest.main()
