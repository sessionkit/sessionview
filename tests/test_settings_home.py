"""The home settings live under ~/.sessionkit/view/settings/: view.json, and
the neomutt override `neomuttrc` beside it. The old home, ~/.sessionview/, is
never created and never read.

Every case runs in a scratch HOME (support.scratch_env) with no
SESSIONVIEW_CONFIG, so the DEFAULT home is what is exercised.

LOUD, NOT SILENT: when the new home file is absent and an old
~/.sessionview/config.json is present, sessionview-config makes no new file
from the template. It refuses, exits non-zero, names both paths and says to
run the host step that moves the file. It reads nothing from the old file.
The sidebar shows the same message and keeps running on the template.

LEFTOVER, WARNED: when BOTH files exist (moved, but the old one left behind),
sessionview-config goes on with the new file and warns once per process on
stderr, naming the leftover and saying a project walk-up under HOME reads it
as an untrusted layer. It only stats the leftover. The sidebar shows the
warning as its note.
"""
import json
import os
import re
import subprocess
import sys
import unittest

from tests import support

SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")
SENTINEL = "old-home-value-never-read"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def new_home(home):
    return os.path.join(home, ".sessionkit", "view", "settings")


def old_home(home):
    return os.path.join(home, ".sessionview")


def shims(home):
    """`message path NAME` answers a scratch maildir; neomutt is a no-op.
    Returns the shim dir, to go first on PATH."""
    b = os.path.join(home, "shims")
    box = os.path.join(home, "mail", "alpha")
    for sub in ("new", "cur", "tmp"):
        os.makedirs(os.path.join(box, sub), exist_ok=True)
    os.makedirs(b, exist_ok=True)
    for name, text in (("message", f'#!/bin/sh\n[ "$1" = path ] && echo "{box}" && exit 0\nexit 2\n'),
                       ("neomutt", "#!/bin/sh\nexit 0\n")):
        p = os.path.join(b, name)
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, 0o755)
    return b


class HomeBase(unittest.TestCase):
    def setUp(self):
        self._ctx = support.scratch_env()
        self.env, self.home = self._ctx.__enter__()
        self.assertNotIn("SESSIONVIEW_CONFIG", self.env)
        self.assertNotIn("SIDEBAR_CONFIG", self.env)
        self.view_json = os.path.join(new_home(self.home), "view.json")
        self.old_json = os.path.join(old_home(self.home), "config.json")
        with open(os.path.join(support.CONFIG, "config.json"), encoding="utf-8") as f:
            self.template = json.load(f)

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def cli(self, *args):
        return support.run("sessionview-config", *args, env=self.env)


class NewHome(HomeBase):
    """The default home is ~/.sessionkit/view/settings/view.json, and
    ~/.sessionview stays absent through init, get, set and the messages
    launcher."""

    def assert_no_old_home(self, after):
        self.assertFalse(os.path.lexists(old_home(self.home)),
                         f"{after} created ~/.sessionview")

    def test_path_is_the_new_home(self):
        r = self.cli("path")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), self.view_json)
        self.assert_no_old_home("path")

    def test_init_makes_view_json_from_the_template(self):
        r = self.cli("init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), self.view_json)
        with open(self.view_json, encoding="utf-8") as f:
            self.assertEqual(json.load(f), self.template)
        self.assert_no_old_home("init")

    def test_get_set_unset_use_the_new_home(self):
        r = self.cli("get", "terminal", "--where")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(self.view_json), "get made no home file")
        self.assert_no_old_home("get")
        r = self.cli("set", "terminal", "ghostty")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.rstrip("\n").split("\t"), ["terminal", "ghostty", self.view_json])
        r = self.cli("get", "terminal", "--where")
        self.assertEqual(r.stdout.rstrip("\n").split("\t"), ["ghostty", self.view_json])
        self.assert_no_old_home("set")
        r = self.cli("unset", "terminal")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_no_old_home("unset")

    def test_the_override_still_names_another_file(self):
        other = os.path.join(self.home, "elsewhere", "mine.json")
        for var in ("SESSIONVIEW_CONFIG", "SIDEBAR_CONFIG"):
            env = dict(self.env, **{var: other})
            r = support.run("sessionview-config", "path", env=env)
            self.assertEqual(r.stdout.strip(), other, var)

    def test_messages_sources_the_new_neomuttrc_only(self):
        env = dict(self.env, PATH=shims(self.home) + os.pathsep + self.env.get("PATH", ""),
                   SESSIONVIEW_STATE=os.path.join(self.home, "state"))
        mine = os.path.join(new_home(self.home), "neomuttrc")
        r = support.run("sessionview-messages", "alpha", "--print", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        sources = [l for l in r.stdout.splitlines() if l.startswith("source ")]
        self.assertEqual(sources, [f'source "{os.path.join(support.CONFIG, "neomuttrc")}"'],
                         "sourced a user neomuttrc that does not exist")
        self.assert_no_old_home("the messages launcher")
        os.makedirs(os.path.dirname(mine), exist_ok=True)
        with open(mine, "w") as f:
            f.write("# mine\n")
        r = support.run("sessionview-messages", "alpha", "--print", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f'source "{mine}"\n', r.stdout)
        self.assertNotIn(".sessionview", r.stdout)
        self.assert_no_old_home("the messages launcher")


class LoudDetector(HomeBase):
    """Old ~/.sessionview/config.json present, new home file absent: refuse."""

    def setUp(self):
        super().setUp()
        os.makedirs(old_home(self.home))
        with open(self.old_json, "w") as f:
            json.dump({"terminal": SENTINEL, "width": 77}, f)

    def assert_refused(self, r, verb):
        self.assertNotEqual(r.returncode, 0, f"{verb}: exit 0\n{r.stdout}{r.stderr}")
        self.assertIn(self.old_json, r.stderr, verb)
        self.assertIn(self.view_json, r.stderr, verb)
        self.assertIn("host step", r.stderr, verb)
        self.assertNotIn(SENTINEL, r.stdout + r.stderr, f"{verb} read the old file")
        self.assertFalse(os.path.exists(self.view_json), f"{verb} made a new home file")
        self.assertFalse(os.path.exists(new_home(self.home)), f"{verb} made the new home dir")

    def test_every_reading_verb_refuses(self):
        for args in (("init",), ("get", "terminal"), ("get", "width", "--where"),
                     ("dump",), ("windows",), ("set", "terminal", "ghostty"),
                     ("unset", "terminal")):
            self.assert_refused(self.cli(*args), " ".join(args))

    def test_the_old_file_is_left_alone(self):
        before = os.stat(self.old_json)
        with open(self.old_json, "rb") as f:
            body = f.read()
        self.cli("set", "terminal", "ghostty")
        with open(self.old_json, "rb") as f:
            self.assertEqual(f.read(), body)
        self.assertEqual(os.listdir(old_home(self.home)), ["config.json"])
        self.assertEqual(os.stat(self.old_json).st_mtime_ns, before.st_mtime_ns)

    def test_the_recipe_runs_for_a_home_with_a_space(self):
        """The refusal's recipe, pasted into sh as printed, moves the file,
        its backups and neomuttrc and leaves no ~/.sessionview, even for a HOME that
        holds a space. Nothing in it fails on a file left behind."""
        home = os.path.join(self.home, "my home")
        old_dir = old_home(home)
        os.makedirs(old_dir)
        with open(os.path.join(old_dir, "config.json"), "w") as f:
            json.dump({"width": 77}, f)
        backup = "config.json.before-upgrade-20300609-123456"
        with open(os.path.join(old_dir, backup), "w") as f:
            f.write("{}\n")
        with open(os.path.join(old_dir, "neomuttrc"), "w") as f:
            f.write("# mine\n")
        env = dict(self.env, HOME=home)
        r = support.run("sessionview-config", "get", "width", env=env)
        self.assertEqual(r.returncode, 3, r.stderr)
        recipe = "\n".join(l[4:] for l in r.stderr.splitlines() if l.startswith("    "))
        self.assertTrue(recipe, r.stderr)
        s = subprocess.run(["/bin/sh", "-c", recipe], env=env, capture_output=True, text=True)
        self.assertEqual(s.returncode, 0, s.stderr + recipe)
        self.assertFalse(os.path.lexists(old_dir), "the recipe left ~/.sessionview behind")
        self.assertTrue(os.path.isfile(os.path.join(new_home(home), backup)), "backup not moved")
        self.assertTrue(os.path.isfile(os.path.join(new_home(home), "neomuttrc")), "neomuttrc not moved")
        r = support.run("sessionview-config", "get", "width", "--where", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.rstrip("\n").split("\t"),
                         ["77", os.path.join(new_home(home), "view.json")])
        self.assertEqual(r.stderr, "")

    def test_the_recipe_never_fails_on_a_file_left_behind(self):
        """Something else in the old dir: every step still exits 0, the
        settings move, and the dir (no longer a layer) stays for the user."""
        with open(os.path.join(old_home(self.home), "notes.txt"), "w") as f:
            f.write("mine\n")
        r = self.cli("get", "width")
        recipe = "\n".join(l[4:] for l in r.stderr.splitlines() if l.startswith("    "))
        s = subprocess.run(["/bin/sh", "-c", recipe], env=self.env, capture_output=True, text=True)
        self.assertEqual(s.returncode, 0, s.stderr + recipe)
        self.assertEqual(os.listdir(old_home(self.home)), ["notes.txt"])
        self.assertTrue(os.path.isfile(self.view_json))

    def test_moved_file_is_used(self):
        """After the host step (move the file), the same value is read from
        the new home and the refusal is gone."""
        os.makedirs(new_home(self.home))
        os.rename(self.old_json, self.view_json)
        os.rmdir(old_home(self.home))
        r = self.cli("get", "width", "--where")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.rstrip("\n").split("\t"), ["77", self.view_json])
        self.assertFalse(os.path.lexists(old_home(self.home)))

    def test_an_explicit_override_is_not_refused(self):
        """SESSIONVIEW_CONFIG names the file outright: the default home, old
        or new, is not consulted."""
        other = os.path.join(self.home, "elsewhere", "mine.json")
        env = dict(self.env, SESSIONVIEW_CONFIG=other)
        r = support.run("sessionview-config", "get", "terminal", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.rstrip("\n"), self.template["terminal"])

    def test_the_sidebar_shows_it_and_does_not_crash(self):
        if not support.have_tmux():
            self.skipTest(support.TMUX_SKIP)
        # a PRIVATE tmux server only (support.private_tmux), and `session list`
        # answers nothing, so no real server or seat is ever read
        with support.private_tmux("home") as pt:
            fx = support.StoreFixtures(os.path.join(self.home, "fx"), pt)
            with open(os.path.join(fx.bin, "session"), "w") as f:
                f.write("#!/bin/sh\necho '[]'\n")
            os.chmod(os.path.join(fx.bin, "session"), 0o755)
            env = fx.env(self.env)
            del env["SESSIONVIEW_CONFIG"]          # the DEFAULT home is the case here
            env.update(SESSIONVIEW_VIEW_SOCK=pt.sock, SIDEBAR_HEIGHT="40")   # the DEFAULT width
            r = subprocess.run([sys.executable, "-B", SIDEBAR, "--once"], env=env,
                               capture_output=True, text=True, timeout=60, cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        # the panel wraps the text: compare with the frame and all spaces gone
        joined = re.sub(r"[\s│╭╮╰╯─]", "", ANSI.sub("", r.stdout))
        self.assertIn("hoststep", joined, r.stdout)
        self.assertIn("~/.sessionview/config.json", joined, r.stdout)
        self.assertIn("~/.sessionkit/view/settings/view.json", joined, r.stdout)
        self.assertNotIn("\u2026", r.stdout, "the note was cut short")
        self.assertNotIn(SENTINEL, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.view_json))


class LeftoverWarn(HomeBase):
    """Both files: the new home is used, and the leftover old file is named
    once per process as a hazard. It is only stat'ed."""

    def setUp(self):
        super().setUp()
        os.makedirs(new_home(self.home))
        with open(self.view_json, "w") as f:
            json.dump(dict(self.template, width=51), f)
        os.makedirs(old_home(self.home))
        with open(self.old_json, "w") as f:
            json.dump({"terminal": SENTINEL, "width": 77}, f)

    def warnings(self, stderr):
        return [l for l in stderr.splitlines() if l.startswith("sessionview-config: warning:")]

    def test_every_reading_verb_warns_once_and_goes_on(self):
        before = os.stat(self.old_json).st_mtime_ns
        for args in (("init",), ("get", "width"), ("dump",), ("windows",),
                     ("set", "terminal", "ghostty"), ("unset", "terminal")):
            verb = " ".join(args)
            r = self.cli(*args)
            self.assertEqual(r.returncode, 0, f"{verb}: {r.stderr}")
            w = self.warnings(r.stderr)
            self.assertEqual(len(w), 1, f"{verb}: not once per process:\n{r.stderr}")
            self.assertIn(self.old_json, w[0], verb)
            self.assertIn("untrusted", w[0], verb)
            self.assertIn("remove", w[0].lower(), verb)
            self.assertIn(self.view_json, r.stderr, verb)
            # the old dir may hold the neomutt override too: removing the dir
            # as told must not lose it, so the warning names it
            self.assertIn("neomuttrc", r.stderr, verb)
            self.assertNotIn(SENTINEL, r.stdout + r.stderr, f"{verb} read the old file")
        self.assertEqual(self.cli("get", "width").stdout.strip(), "51")
        self.assertEqual(os.stat(self.old_json).st_mtime_ns, before)

    def test_no_warning_once_it_is_gone(self):
        os.remove(self.old_json)
        r = self.cli("get", "width")
        self.assertEqual((r.returncode, r.stdout.strip(), r.stderr), (0, "51", ""))

    def test_an_explicit_override_is_not_warned(self):
        """As with the refusal: SESSIONVIEW_CONFIG names the file outright,
        and the default home, old or new, is not consulted."""
        other = os.path.join(self.home, "elsewhere", "mine.json")
        r = support.run("sessionview-config", "get", "width",
                        env=dict(self.env, SESSIONVIEW_CONFIG=other))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.warnings(r.stderr), [])

    def test_the_sidebar_shows_it_and_uses_the_new_file(self):
        if not support.have_tmux():
            self.skipTest(support.TMUX_SKIP)
        with support.private_tmux("left") as pt:
            fx = support.StoreFixtures(os.path.join(self.home, "fx"), pt)
            with open(os.path.join(fx.bin, "session"), "w") as f:
                f.write("#!/bin/sh\necho '[]'\n")
            os.chmod(os.path.join(fx.bin, "session"), 0o755)
            env = fx.env(self.env)
            del env["SESSIONVIEW_CONFIG"]          # the DEFAULT home is the case here
            env.update(SESSIONVIEW_VIEW_SOCK=pt.sock, SIDEBAR_HEIGHT="40")
            r = subprocess.run([sys.executable, "-B", SIDEBAR, "--once"], env=env,
                               capture_output=True, text=True, timeout=60, cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        joined = re.sub(r"[\s│╭╮╰╯─]", "", ANSI.sub("", r.stdout))
        self.assertIn("~/.sessionview/config.json", joined, r.stdout)
        self.assertIn("untrusted", joined, r.stdout)
        self.assertNotIn("refusing", joined, r.stdout)
        self.assertNotIn("\u2026", r.stdout, "the note was cut short")
        self.assertNotIn(SENTINEL, r.stdout + r.stderr)


def code_lines(pattern):
    """{repo-relative path: [stripped line]} of every NON-comment line in a
    shipped script (bin/, plugins/*/, lib/) that matches PATTERN."""
    rx, out = re.compile(pattern), {}
    paths = [p for p, _ in support.scripts()]
    lib = os.path.join(support.REPO, "lib")
    paths += [os.path.join(lib, n) for n in sorted(os.listdir(lib))]
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                t = line.strip()
                if t.startswith(("#", "--")) or not rx.search(t):
                    continue
                out.setdefault(os.path.relpath(p, support.REPO), []).append(t)
    return out


class OneDefinition(unittest.TestCase):
    """The home settings dir is spelt ONCE per language: Python in
    bin/sessionview-config (every other Python caller asks `sessionview-config
    path`), shell in bin/sessionview-messages. The old home file is named once,
    by the detector, which only checks that it exists."""

    def test_the_new_home_is_defined_once_per_language(self):
        self.assertEqual(code_lines(r"\.sessionkit/view/settings"), {
            "bin/sessionview-config": [
                "2. ~/.sessionkit/view/settings/view.json",       # the --help text
                'SETTINGS_DIR = "~/.sessionkit/view/settings"',
            ],
            "bin/sessionview-messages": ['VIEW_SETTINGS="$HOME/.sessionkit/view/settings"'],
        })

    def test_the_old_home_is_named_only_by_the_detector(self):
        self.assertEqual(code_lines(r"~/\.sessionview|HOME/\.sessionview|\.sessionview/(config\.json|neomuttrc)"), {
            "bin/sessionview-config": ['LEGACY_HOME_FILE = "~/.sessionview/config.json"'],
        })

    def test_the_docs_name_the_old_home_once(self):
        """Every doc points at "Upgrading from 0.1.0" in docs/configuration.md,
        which names the old folder on one line, its move's first. CHANGELOG.md
        is history and is left out."""
        rx = re.compile(r"~/\.sessionview|HOME/\.sessionview|\.sessionview/(config\.json|neomuttrc)")
        out = {}
        for d, subdirs, files in os.walk(support.REPO):
            subdirs[:] = sorted(n for n in subdirs if not n.startswith(".") and n != "tests")
            for n in sorted(files):
                rel = os.path.relpath(os.path.join(d, n), support.REPO)
                if not n.endswith(".md") or rel == "CHANGELOG.md":
                    continue
                with open(os.path.join(d, n), encoding="utf-8") as f:
                    hits = [line.strip() for line in f if rx.search(line)]
                if hits:
                    out[rel] = hits
        self.assertEqual(out, {
            "docs/configuration.md": ["old=~/.sessionview new=~/.sessionkit/view/settings"],
        })


def upgrading_move():
    """The sh block of "Upgrading from 0.1.0" in docs/configuration.md."""
    with open(os.path.join(support.REPO, "docs", "configuration.md"), encoding="utf-8") as f:
        text = f.read()
    section = text.split("\n## Upgrading from 0.1.0\n", 1)[1].split("\n## ", 1)[0]
    return section.split("```sh\n", 1)[1].split("```", 1)[0]


class UpgradingDoc(HomeBase):
    """The move "Upgrading from 0.1.0" documents runs as written."""

    def test_the_documented_move_runs(self):
        """Pasted into sh, for a HOME with a space and a file of the user's own
        left in the old folder: every step exits 0, the file, its backup and
        neomuttrc move, the check names view.json, and the folder stays only
        because it still holds the user's file."""
        home = os.path.join(self.home, "my home")
        old_dir = old_home(home)
        os.makedirs(old_dir)
        with open(os.path.join(old_dir, "config.json"), "w") as f:
            json.dump({"width": 64}, f)
        backup = "config.json.before-upgrade-20300609-123456"
        for name, body in ((backup, "{}\n"), ("neomuttrc", "# mine\n"), ("notes.txt", "mine\n")):
            with open(os.path.join(old_dir, name), "w") as f:
                f.write(body)
        move = upgrading_move()
        lines = move.rstrip("\n").split("\n")
        self.assertEqual(lines[-1], "sessionview-config get width --where", move)
        env = dict(self.env, HOME=home)
        s = subprocess.run(["/bin/sh", "-c", "\n".join(lines[:-1])], env=env,
                           capture_output=True, text=True)
        self.assertEqual(s.returncode, 0, s.stderr + move)
        self.assertEqual(os.listdir(old_dir), ["notes.txt"])
        for name in ("view.json", backup, "neomuttrc"):
            self.assertTrue(os.path.isfile(os.path.join(new_home(home), name)), name)
        r = support.run("sessionview-config", "get", "width", "--where", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.rstrip("\n").split("\t"),
                         ["64", os.path.join(new_home(home), "view.json")])

    def test_an_empty_old_folder_is_removed(self):
        """With only the settings files in it, the old folder is gone after."""
        os.makedirs(old_home(self.home))
        with open(self.old_json, "w") as f:
            json.dump({"width": 64}, f)
        with open(os.path.join(old_home(self.home), "neomuttrc"), "w") as f:
            f.write("# mine\n")
        lines = upgrading_move().rstrip("\n").split("\n")
        s = subprocess.run(["/bin/sh", "-c", "\n".join(lines[:-1])], env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(s.returncode, 0, s.stderr)
        self.assertFalse(os.path.lexists(old_home(self.home)))
        self.assertEqual(sorted(os.listdir(new_home(self.home))), ["neomuttrc", "view.json"])


class NoOverwrite(HomeBase):
    """Both moves, the refusal's and the documented one, stop at their first
    step when view.json is already there: the new file is never overwritten
    by the old one, and nothing is moved or removed."""

    def setUp(self):
        super().setUp()
        os.makedirs(old_home(self.home))
        with open(self.old_json, "w") as f:
            json.dump({"width": 11}, f)

    def make_new(self):
        os.makedirs(new_home(self.home))
        with open(self.view_json, "w") as f:
            json.dump({"width": 99}, f)

    def assert_untouched(self, s, move):
        self.assertNotEqual(s.returncode, 0, move)
        with open(self.view_json, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"width": 99}, "view.json was overwritten")
        self.assertTrue(os.path.isfile(self.old_json), "the old file was moved")

    def test_the_refusal_move_never_overwrites_view_json(self):
        """Printed while view.json was absent, pasted after it appeared."""
        r = self.cli("get", "width")
        self.assertEqual(r.returncode, 3, r.stderr)
        move = "\n".join(l[4:] for l in r.stderr.splitlines() if l.startswith("    "))
        self.make_new()
        s = subprocess.run(["/bin/sh", "-c", move], env=self.env, capture_output=True, text=True)
        self.assert_untouched(s, move)

    def test_the_documented_move_never_overwrites_view_json(self):
        self.make_new()
        lines = upgrading_move().rstrip("\n").split("\n")
        move = "\n".join(lines[:-1])
        s = subprocess.run(["/bin/sh", "-c", move], env=self.env, capture_output=True, text=True)
        self.assert_untouched(s, move)


if __name__ == "__main__":
    unittest.main()
