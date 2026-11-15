"""bin/tmux-sidebar: the picker's project recency counts a task made under
projects/NAME/tasks/.

A new directory moves only its parent's mtime. A new task made at
projects/NAME/tasks/<ID>_<type>_<slug>/ moves projects/NAME/tasks and leaves
projects/NAME alone, so a recency read from projects/NAME by itself stayed
put while tasks kept landing, and the picker ranked a busy project as idle.
projects_recent() now takes the newest of projects/NAME, projects/NAME/tasks
(when there is one) and recent.tsv.

No tmux and no tm: the sidebar is loaded into a child process under a
scratch HOME (as test_repo_cache_store does), with a private socket name in
SESSIONVIEW_VIEW_SOCK. `tm project list` is stubbed to name the scratch
store's projects, and the store itself is real directories whose mtimes the
test sets."""
import json
import os
import subprocess
import sys
import textwrap
import unittest

from tests import support

SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")

# argv: sidebar path, store path, JSON {name: recent.tsv epoch}. Prints the
# picker's [(name, recency)] as JSON.
HARNESS = textwrap.dedent('''
    import importlib.machinery, importlib.util, json, os, sys
    loader = importlib.machinery.SourceFileLoader("sidebar", sys.argv[1])
    spec = importlib.util.spec_from_loader("sidebar", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    store, rec = sys.argv[2], json.loads(sys.argv[3])
    names = sorted(os.listdir(os.path.join(store, "projects")))

    def sh(cmd):
        if cmd[:3] == ["tm", "project", "list"]:
            return json.dumps([{"name": n} for n in names])
        return ""

    m.sh = sh
    m.viewed_store = lambda: {"store": "scratch", "path": store}
    m.repo_projects = lambda: {}
    m.sessions = lambda: []
    m.recent_times = lambda: dict(rec)
    m.picker_order = lambda: "recent"
    print(json.dumps(m.projects_recent()))
''')

OLD = 1_000_000_000      # 2001: the "long ago" every fixture starts from
MID = 1_500_000_000      # 2017: a project touched since OLD, before now


class PickerTasksRecency(unittest.TestCase):

    def setUp(self):
        cm = support.scratch_env(SESSIONVIEW_VIEW_SOCK="sv-test-tasks-recency")
        self.env, self.home = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self.store = os.path.join(os.path.realpath(self.home), "store")
        os.makedirs(os.path.join(self.store, "projects"))

    def project(self, name, mtime, tasks=None):
        """projects/NAME at MTIME; with TASKS, a tasks/ holding one old task,
        tasks/ itself at TASKS."""
        path = os.path.join(self.store, "projects", name)
        os.makedirs(path)
        if tasks is not None:
            os.makedirs(os.path.join(path, "tasks", "X-1_fix_old"))
            os.utime(os.path.join(path, "tasks", "X-1_fix_old"), (OLD, OLD))
            os.utime(os.path.join(path, "tasks"), (tasks, tasks))
        os.utime(path, (mtime, mtime))
        return path

    def recent(self, rec=None):
        r = subprocess.run(
            [sys.executable, "-B", "-c", HARNESS, SIDEBAR, self.store,
             json.dumps(rec or {})],
            env=self.env, capture_output=True, text=True, timeout=30,
            cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        return [(n, t) for n, t in json.loads(r.stdout)]

    def test_new_task_under_tasks_ranks_the_project_first(self):
        old = self.project("old", OLD, tasks=OLD)
        self.project("mid", MID)
        # Taskmaster makes a new task in old's tasks/ dir: only tasks/ moves.
        os.makedirs(os.path.join(old, "tasks", "X-2_fix_new"))
        self.assertEqual(os.stat(old).st_mtime, OLD,
                         "fixture: a new task must not move projects/NAME")
        got = self.recent()
        self.assertEqual([n for n, _ in got], ["old", "mid"], got)
        self.assertGreater(dict(got)["old"], MID)

    def test_tasks_mtime_is_the_recency(self):
        self.project("old", OLD, tasks=MID + 10)
        self.project("mid", MID)
        self.assertEqual(self.recent(), [("old", MID + 10), ("mid", MID)])

    def test_older_tasks_dir_never_lowers_the_project(self):
        # tasks/ older than projects/NAME: projects/NAME still counts.
        self.project("busy", MID + 10, tasks=OLD)
        self.project("mid", MID)
        self.assertEqual(self.recent(), [("busy", MID + 10), ("mid", MID)])

    def test_project_without_tasks_dir_keeps_its_own_mtime(self):
        self.project("flat", MID + 10)
        self.project("mid", MID)
        self.assertEqual(self.recent(), [("flat", MID + 10), ("mid", MID)])

    def test_recent_tsv_still_wins_when_newer(self):
        self.project("old", OLD, tasks=MID)
        self.project("opened", OLD)
        self.assertEqual(self.recent({"opened": MID + 20}),
                         [("opened", MID + 20), ("old", MID)])


if __name__ == "__main__":
    unittest.main()
