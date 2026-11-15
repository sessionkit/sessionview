"""bin/tmux-sidebar: the new-session picker shows each project's eggs (the
ready tags waiting in its own repo), ^g keeps only the projects with eggs,
and space / ^a mark rows so one enter opens them all.

The sidebar is loaded into a child process under a scratch HOME (as
test_store_view does) and never into this one. The picker's sources are
stubbed in the child: four projects, and an egg count per name. The egg
counter itself runs against a real git repo in the scratch HOME, so its
count is the real ready_where()."""
import json
import os
import subprocess
import sys
import textwrap
import unittest

from tests import support

SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")

HARNESS = textwrap.dedent('''
    import importlib.machinery, importlib.util, json, sys
    loader = importlib.machinery.SourceFileLoader("sidebar", sys.argv[1])
    spec = importlib.util.spec_from_loader("sidebar", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    OUT = {}
    exec(sys.argv[2])
    print(json.dumps(OUT))
''')

# Four projects; alpha has two eggs, beta none, gamma is still being counted,
# delta could not be counted ("?"). The picker's opens are recorded.
STUBS = textwrap.dedent('''
    import re
    ANSI = re.compile(r"\\x1b\\[[0-9;]*m")
    EGGS = {"alpha": ("2E", 2), "beta": ("", 0), "gamma": None, "delta": ("?E", None)}
    m.session_items = lambda: [{"name": n, "live": False, "tag": ""}
                               for n in ("alpha", "beta", "gamma", "delta")]
    m.project_eggs = lambda n: EGGS[n]
    opened = []
    m.open_project = lambda n: opened.append(n)
    m.open_projects = lambda names: opened.append(list(names))
    def drawn():
        lines = []
        m.render_picker(lambda text, target=None, selected=False: lines.append(ANSI.sub("", text)), 0, 30)
        return lines
    def shown():
        return [it["name"] for it in m.picker_shown(m.PICKER, 100)]
''')


class PickerBase(unittest.TestCase):
    def setUp(self):
        self._scratch = support.scratch_env(SIDEBAR_WIDTH="40")
        self.env, self.home = self._scratch.__enter__()

    def tearDown(self):
        self._scratch.__exit__(None, None, None)

    def harness(self, body, stubs=True):
        code = (STUBS if stubs else "") + textwrap.dedent(body)
        r = subprocess.run([sys.executable, "-B", "-c", HARNESS, SIDEBAR, code],
                           env=self.env, capture_output=True, text=True, timeout=60,
                           cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.splitlines()[-1])


class Marks(PickerBase):
    def test_space_marks_and_moves_down_then_enter_opens_all(self):
        out = self.harness('''
            m.open_picker("sessions")
            m.picker_keys(" ")
            OUT["marks1"], OUT["cur1"] = list(m.PICKER["marks"]), m.PICKER["cur"]
            m.picker_keys("  ")
            OUT["marks3"] = list(m.PICKER["marks"])
            OUT["hint"] = drawn()[2].strip()
            m.picker_keys("\\r")
            OUT["opened"], OUT["closed"] = opened, m.PICKER is None
        ''')
        self.assertEqual(out["marks1"], ["alpha"])
        self.assertEqual(out["cur1"], 1)
        self.assertEqual(out["marks3"], ["alpha", "beta", "gamma"])
        self.assertTrue(out["hint"].startswith("3 marked"), out["hint"])
        self.assertEqual(out["opened"], [["alpha", "beta", "gamma"]])
        self.assertTrue(out["closed"])

    def test_space_on_a_marked_row_unmarks_it(self):
        out = self.harness('''
            m.open_picker("sessions")
            m.picker_keys(" ")
            m.PICKER["cur"] = 0
            m.picker_keys(" ")
            OUT["marks"] = list(m.PICKER["marks"])
        ''')
        self.assertEqual(out["marks"], [])

    def test_ctrl_a_marks_what_the_filter_shows_and_marks_survive_it(self):
        out = self.harness('''
            m.open_picker("sessions")
            m.picker_keys("l")
            OUT["shown"] = shown()
            m.picker_keys("\\x01")
            OUT["marks"] = list(m.PICKER["marks"])
            m.picker_keys("\\x7f")
            OUT["after_backspace"] = list(m.PICKER["marks"])
            OUT["ticks"] = [l.split()[1] for l in drawn()[4:] if l.startswith("\\u2713")]
            m.picker_keys("\\r")
            OUT["opened"] = opened
        ''')
        self.assertEqual(out["shown"], ["alpha", "delta"])
        self.assertEqual(out["marks"], ["alpha", "delta"])
        self.assertEqual(out["after_backspace"], ["alpha", "delta"])
        self.assertEqual(out["ticks"], ["alpha", "delta"])
        self.assertEqual(out["opened"], [["alpha", "delta"]])

    def test_ctrl_a_again_unmarks_them(self):
        out = self.harness('''
            m.open_picker("sessions")
            m.picker_keys("\\x01")
            OUT["all"] = list(m.PICKER["marks"])
            m.picker_keys("\\x01")
            OUT["none"] = list(m.PICKER["marks"])
        ''')
        self.assertEqual(out["all"], ["alpha", "beta", "gamma", "delta"])
        self.assertEqual(out["none"], [])

    def test_enter_with_no_marks_opens_the_highlighted_row(self):
        out = self.harness('''
            m.open_picker("sessions")
            m.picker_keys("\\x1b[B\\r")
            OUT["opened"] = opened
        ''')
        self.assertEqual(out["opened"], ["beta"])

    def test_space_is_still_typed_in_a_box_without_marks(self):
        out = self.harness('''
            m.window_items = lambda sess: [{"name": "repo"}, {"name": "git"}]
            m.open_picker("windows", "sess")
            m.picker_keys("a b")
            OUT["filter"] = m.PICKER["filter"]
            OUT["marks"] = m.PICKER["marks"]
        ''')
        self.assertEqual(out["filter"], "a b")
        self.assertEqual(out["marks"], [])

    def test_a_callers_own_pick_takes_one_value(self):
        out = self.harness('''
            got = []
            m.open_picker("sessions", pick=got.append)
            m.picker_keys(" ")
            OUT["filter"], OUT["marks"] = m.PICKER["filter"], m.PICKER["marks"]
            m.PICKER["filter"] = ""
            m.picker_keys("\\r")
            OUT["got"], OUT["opened"] = got, opened
        ''')
        self.assertEqual(out["filter"], " ")
        self.assertEqual(out["marks"], [])
        self.assertEqual(out["got"], ["alpha"])
        self.assertEqual(out["opened"], [])


class Eggs(PickerBase):
    def test_each_row_shows_its_eggs(self):
        out = self.harness('''
            m.open_picker("sessions")
            OUT["rows"] = {l.split()[1]: l.rstrip() for l in drawn()[4:] if l.strip()}
        ''')
        self.assertTrue(out["rows"]["alpha"].endswith("2E"), out["rows"]["alpha"])
        self.assertTrue(out["rows"]["delta"].endswith("?E"), out["rows"]["delta"])
        self.assertNotIn("E", out["rows"]["beta"].split()[-1])
        self.assertTrue(out["rows"]["gamma"].endswith("gamma"), out["rows"]["gamma"])

    def test_ctrl_g_keeps_rows_with_eggs_or_unknown(self):
        out = self.harness('''
            m.open_picker("sessions")
            m.picker_keys("\\x07")
            lines = drawn()
            OUT["shown"], OUT["title"], OUT["hint"] = shown(), lines[0], lines[2].strip()
            m.picker_keys("\\x07")
            OUT["again"] = shown()
        ''')
        self.assertEqual(out["shown"], ["alpha", "delta"])
        self.assertIn("only", out["title"])
        self.assertTrue(out["hint"].startswith("counting 1"), out["hint"])
        self.assertEqual(out["again"], ["alpha", "beta", "gamma", "delta"])

    def test_ctrl_a_under_ctrl_g_marks_only_the_projects_with_eggs(self):
        out = self.harness('''
            m.open_picker("sessions")
            m.picker_keys("\\x07\\x01\\r")
            OUT["opened"] = opened
        ''')
        self.assertEqual(out["opened"], [["alpha", "delta"]])

    def test_opening_the_picker_starts_every_count(self):
        out = self.harness('''
            asked = []
            m.project_eggs = lambda n: asked.append(n)
            m.open_picker("sessions")
            OUT["asked"] = asked
        ''')
        self.assertEqual(out["asked"], ["alpha", "beta", "gamma", "delta"])


class Counter(PickerBase):
    """project_eggs() on a real repo: one ready tag not merged into master."""

    def repo(self):
        path = os.path.join(self.home, "alpha")
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
               "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-C", path]
        os.makedirs(path)
        for args in (["init", "-q", "-b", "master"], ["commit", "-q", "--allow-empty", "-m", "one"],
                     ["checkout", "-q", "-b", "feat"], ["commit", "-q", "--allow-empty", "-m", "two"],
                     ["tag", "-a", "-m", "ready", "ready/feat"], ["checkout", "-q", "master"]):
            r = subprocess.run(git + args, env=self.env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        return path

    def test_counts_in_a_thread_then_answers_from_the_cache(self):
        path = self.repo()
        out = self.harness(f'''
            import time
            m.project_repo_now = lambda n: {path!r} if n == "alpha" else ""
            OUT["first"] = m.project_eggs("alpha")
            end = time.time() + 10
            while m._EGGS_ASK and time.time() < end:
                time.sleep(0.02)
            OUT["then"] = m.project_eggs("alpha")
            m.ONESHOT = True
            OUT["none"] = m.project_eggs("beta")
        ''', stubs=False)
        self.assertIsNone(out["first"])
        self.assertEqual(out["then"][1], 1)
        self.assertTrue(out["then"][0].startswith("1"), out["then"])
        self.assertEqual(out["none"], ["", 0])


class OpenMany(PickerBase):
    def test_first_opens_and_jumps_the_rest_open_behind_it(self):
        out = self.harness('''
            import sys
            jumped, notes = [], []
            m.jump = lambda t: jumped.append(list(t))
            m.note = lambda text, title="note": notes.append(text)
            m.project_cmd = lambda n: [sys.executable, "-c",
                "import sys, time; time.sleep(0.2); sys.exit(sys.argv[1] == 'bad')", n]
            t = m.open_projects(["a", "b", "bad", "a", " "])
            OUT["during"] = dict(m.OPENING)
            OUT["jumped_first"] = list(jumped)
            t.join(10)
            OUT["after"] = dict(m.OPENING)
            OUT["notes"] = notes
        ''', stubs=False)
        self.assertEqual(out["jumped_first"], [["session", "a"]])
        self.assertEqual(out["during"]["total"], 3)
        self.assertEqual(out["after"]["total"], 0)
        self.assertEqual(out["notes"], ["could not open: bad"])

    def test_a_popup_opens_them_all_before_its_jump(self):
        out = self.harness('''
            ran, jumped = [], []
            m.POPUP = True
            m.project_cmd = lambda n: ["x", n]
            m.subprocess.run = lambda cmd, **kw: ran.append(cmd[-1])
            m.jump = lambda t: jumped.append((list(t), list(ran)))
            OUT["t"] = m.open_projects(["a", "b", "c"])
            OUT["jumped"] = jumped
        ''', stubs=False)
        self.assertIsNone(out["t"])
        self.assertEqual(out["jumped"], [[["session", "a"], ["b", "c", "a"]]])


if __name__ == "__main__":
    unittest.main()
