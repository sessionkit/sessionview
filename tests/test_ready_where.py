"""bin/tmux-sidebar: `ready_where` counts unmerged ready/ + egg/ tags against
origin/<default> first (SV-144). Real temp git repos; the function is loaded
into a child process the way test_pinned_agents does."""
import json
import os
import subprocess
import sys
import tempfile
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
    print(json.dumps(m.ready_where(sys.argv[2], "master")))
''')


class ReadyWhere(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="sv-rw-")
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.realpath(self._tmp.name)
        self.env = {k: os.environ[k] for k in support.KEEP if k in os.environ}
        self.env.update(HOME=self.root, GIT_CONFIG_NOSYSTEM="1",
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

    def git(self, cwd, *args):
        r = subprocess.run(["git", "-C", cwd, *args], env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def repo(self, name="work"):
        d = os.path.join(self.root, name)
        os.makedirs(d)
        self.git(d, "init", "-q", "-b", "master")
        self.git(d, "commit", "-q", "--allow-empty", "-m", "base")
        return d

    def commit_branch(self, d, branch, tags=()):
        """Commit on BRANCH off master, tag it, return to master."""
        self.git(d, "checkout", "-q", "-b", branch, "master")
        self.git(d, "commit", "-q", "--allow-empty", "-m", branch)
        for t in tags:
            self.git(d, "tag", t)
        self.git(d, "checkout", "-q", "master")

    def count(self, d):
        r = subprocess.run([sys.executable, "-B", "-c", HARNESS, SIDEBAR, d],
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)[1]

    def test_only_ready(self):
        d = self.repo()
        self.commit_branch(d, "x", ["ready/x"])
        self.assertEqual(self.count(d), 1)

    def test_only_egg(self):
        d = self.repo()
        self.commit_branch(d, "x", ["egg/x"])
        self.assertEqual(self.count(d), 1)

    def test_both_prefixes_count_once(self):
        d = self.repo()
        self.commit_branch(d, "x", ["ready/x", "egg/x"])
        self.assertEqual(self.count(d), 1)

    def test_different_names_count_separately(self):
        d = self.repo()
        self.commit_branch(d, "x", ["ready/x"])
        self.commit_branch(d, "y", ["egg/y"])
        self.assertEqual(self.count(d), 2)

    def test_local_master_behind_origin_counts_against_origin(self):
        up = self.repo("up")
        clone = os.path.join(self.root, "clone")
        self.git(self.root, "clone", "-q", up, clone)
        # origin merges the tagged branch; the clone's local master stays behind
        self.commit_branch(up, "x", ["ready/x"])
        self.git(up, "merge", "-q", "--ff-only", "x")
        self.git(clone, "fetch", "-q", "--tags", "origin")
        self.assertNotEqual(self.git(clone, "rev-parse", "master"),
                            self.git(clone, "rev-parse", "origin/master"))
        self.assertEqual(self.count(clone), 0)

    def test_no_remote_tracking_ref_uses_local_default(self):
        d = self.repo()
        self.commit_branch(d, "x", ["ready/x"])
        self.assertEqual(self.count(d), 1)
        self.git(d, "merge", "-q", "--ff-only", "x")
        # fresh path: the 30s cache is per process, so a new child re-counts
        self.assertEqual(self.count(d), 0)


if __name__ == "__main__":
    unittest.main()
