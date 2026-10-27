"""bin/tmux-sidebar: a project's repo (and so its ready badge) is cached per
STORE, not per name. Two stores can each hold a project called `alpha`, with
its own clone. A store switch must never serve the other store's repo: not
from the cache, and not from a resolve that was asked before the switch and
finishes after it.

No tmux and no tm: the sidebar is loaded into a child process (as
test_ready_where does), and in it `stores()` names two stub stores and
`session_cmd()` answers `repo=` for whichever store is viewed when it is
called, as sessionview-session does. The repos are real git repos in a
scratch HOME, so the badge count is the real ready_where()."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

from tests import support

SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")

# argv: sidebar path, scratch root, scenario. Prints one JSON object.
HARNESS = textwrap.dedent('''
    import importlib.machinery, importlib.util, json, os, sys, time
    loader = importlib.machinery.SourceFileLoader("sidebar", sys.argv[1])
    spec = importlib.util.spec_from_loader("sidebar", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    root, scenario = sys.argv[2], sys.argv[3]

    STORES = [
        {"store": "store-a", "socket": "sock-a", "path": os.path.join(root, "stores", "store-a")},
        {"store": "store-b", "socket": "sock-b", "path": os.path.join(root, "stores", "store-b")},
    ]
    CLONE = {"sock-a": os.path.join(root, "clones", "alpha-a"),
             "sock-b": os.path.join(root, "clones", "alpha-b")}
    asked = []          # the store each resolve was asked on, in order
    delay = {"s": 0}

    def session_cmd(name, *flags):
        # what sessionview-session --print says: the viewed store's clone
        asked.append(m.viewed_store().get("store"))
        line = "store=%s root=%s repo=%s" % (m.viewed_store().get("path"),
                                             CLONE[m.SOCK], CLONE[m.SOCK])
        return [sys.executable, "-c",
                "import sys, time; time.sleep(float(sys.argv[1])); print(sys.argv[2])",
                str(delay["s"]), line]

    m.stores = lambda: STORES
    m.session_cmd = session_cmd

    def settle():
        """Wait for every in-flight resolve to write back."""
        end = time.time() + 10
        while m._REPO_ASK and time.time() < end:
            time.sleep(0.02)

    out = {}
    if scenario == "switch":
        m.ONESHOT = True
        m.switch_store("store-a")
        out["a"] = m.project_repo("alpha")
        out["a_ready"] = m.project_ready("alpha", root, "master")[1]
        m.switch_store("store-b")
        out["b"] = m.project_repo("alpha")
        out["b_ready"] = m.project_ready("alpha", root, "master")[1]
        m.switch_store("store-a")
        out["a_again"] = m.project_repo("alpha")
        out["a_again_ready"] = m.project_ready("alpha", root, "master")[1]
    elif scenario == "inflight":
        # asked on store-a by the render loop, the switch lands while it runs
        m.switch_store("store-a")
        delay["s"] = 0.5
        out["first"] = m.project_repo("alpha")
        m.switch_store("store-b")
        settle()
        delay["s"] = 0
        m.ONESHOT = True
        out["b"] = m.project_repo("alpha")
        m.switch_store("store-a")
        out["a"] = m.project_repo("alpha")
    elif scenario == "late":
        # asked on store-a, but the switch lands before its command is built:
        # that command names store-b, so its answer is not store-a's
        import threading
        go = threading.Event()
        real = session_cmd
        def late_cmd(name, *flags):
            go.wait(10)
            return real(name, *flags)
        m.session_cmd = late_cmd
        m.switch_store("store-a")
        out["first"] = m.project_repo("alpha")
        m.switch_store("store-b")
        go.set()
        settle()
        m.session_cmd = session_cmd
        m.ONESHOT = True
        m.switch_store("store-a")
        out["a"] = m.project_repo("alpha")
        m.switch_store("store-b")
        out["b"] = m.project_repo("alpha")
    out["asked"] = asked
    print(json.dumps(out))
''')


class RepoCacheStore(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="sv-rcs-")
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.realpath(self._tmp.name)
        self.env = {k: os.environ[k] for k in support.KEEP if k in os.environ}
        self.env.update(HOME=self.root, GIT_CONFIG_NOSYSTEM="1",
                        GIT_CEILING_DIRECTORIES=self.root,
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        for s in ("store-a", "store-b"):
            os.makedirs(os.path.join(self.root, "stores", s, "projects", "alpha"))
        # store-a's alpha holds 1 unmerged ready tag, store-b's holds 3
        self.clone_a = self.clone("alpha-a", 1)
        self.clone_b = self.clone("alpha-b", 3)

    def git(self, cwd, *args):
        r = subprocess.run(["git", "-C", cwd, *args], env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def clone(self, name, tags):
        d = os.path.join(self.root, "clones", name)
        os.makedirs(d)
        self.git(d, "init", "-q", "-b", "master")
        self.git(d, "commit", "-q", "--allow-empty", "-m", "base")
        for i in range(tags):
            self.git(d, "checkout", "-q", "-b", f"work-{i}", "master")
            self.git(d, "commit", "-q", "--allow-empty", "-m", f"work {i}")
            self.git(d, "tag", f"ready/work-{i}")
        self.git(d, "checkout", "-q", "master")
        return d

    def scenario(self, name):
        r = subprocess.run([sys.executable, "-B", "-c", HARNESS, SIDEBAR, self.root, name],
                           env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_switch_serves_the_viewed_stores_repo(self):
        out = self.scenario("switch")
        self.assertEqual(out["a"], self.clone_a)
        self.assertEqual(out["a_ready"], 1)
        # the bug: store-b's alpha row was served store-a's clone and count
        self.assertEqual(out["b"], self.clone_b)
        self.assertEqual(out["b_ready"], 3)
        self.assertEqual(out["a_again"], self.clone_a)
        self.assertEqual(out["a_again_ready"], 1)

    def test_switching_back_reuses_the_first_stores_answer(self):
        """Each store is asked once; going back to store-a is a cache hit."""
        out = self.scenario("switch")
        self.assertEqual(out["asked"], ["store-a", "store-b"])

    def test_a_resolve_that_finishes_after_a_switch_stays_with_its_store(self):
        out = self.scenario("inflight")
        self.assertEqual(out["first"], "")      # asked, not yet known
        self.assertEqual(out["b"], self.clone_b)
        self.assertEqual(out["a"], self.clone_a)

    def test_a_resolve_built_after_a_switch_is_not_kept_for_the_old_store(self):
        out = self.scenario("late")
        self.assertEqual(out["first"], "")
        self.assertEqual(out["a"], self.clone_a)
        self.assertEqual(out["b"], self.clone_b)


if __name__ == "__main__":
    unittest.main()
