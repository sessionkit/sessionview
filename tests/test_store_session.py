"""bin/sessionview-session --store-view: the store view's session (SV-92,
design.md §1, §2, §6 cases 1-3).

Every tmux call is on a private socket (support.private_tmux: `-L sv-test-*`
under a scratch TMUX_TMPDIR). Fixture stores mirror the real layouts:
fx-corp (projects/store, no slipbox/scripts), fx-legacy (projects/store,
slipbox, scripts), fx-named (projects/fx-named under the identity name,
slipbox, scripts), fx-bare (slipbox only, no project dir, no mailbox).
"""
import os
import subprocess
import unittest

from tests import support

# design §2's oracle: the store tabs each layout gets, in position order.
ORACLE = {
    "fx-corp": ["tasks", "messages"],
    "fx-legacy": ["tasks", "slipbox", "scripts", "messages"],
    "fx-named": ["tasks", "slipbox", "scripts", "messages"],
    "fx-bare": ["slipbox"],
}
PROJDIR = {"fx-corp": "projects/store", "fx-legacy": "projects/store",
           "fx-named": "projects/fx-named", "fx-bare": None}


class StoreBase(unittest.TestCase):
    TAG = "store"
    LIVE = ()

    def setUp(self):
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self._pt = support.private_tmux(self.TAG)
        self.pt = self._pt.__enter__()
        self.fx = support.StoreFixtures(os.path.join(self.home, "fx"), self.pt, live=self.LIVE)
        self.env = self.fx.env(env)

    def tearDown(self):
        self._pt.__exit__(None, None, None)
        self._scratch.__exit__(None, None, None)

    def store(self, session, ident, *extra):
        """Run store mode for SESSION on fixture IDENT's private socket."""
        return support.run("sessionview-session", session, "--store-view", ident,
                           "--socket", self.pt.sock, "--store", self.fx.path(ident),
                           *extra, env=self.env)

    def names(self, session):
        return [n for _, n, _ in self.pt.windows(session)]

    def tabs(self, session):
        """(index of the first window, the names of the rest): the boot window plus what was added."""
        w = self.pt.windows(session)
        return w[0][0], [n for _, n, _ in w[1:]]

    def active_index(self, session):
        return next(i for i, _, a in self.pt.windows(session) if a)

    def active(self, session):
        return next(n for _, n, a in self.pt.windows(session) if a)

    def boot(self, ident):
        """What the sidebar does for a down store: tm store boot (the shim)."""
        r = subprocess.run([os.path.join(self.fx.bin, "tm"), "store", "boot", ident],
                                   env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)


class Case1TabSet(StoreBase):
    """§6 case 1: the tab set per layout, with no tmux (--list-windows)."""

    def test_tab_set_per_layout(self):
        for ident, want in ORACLE.items():
            with self.subTest(store=ident):
                r = self.store(ident, ident, "--list-windows")
                self.assertEqual(r.returncode, 0, r.stderr)
                got = [line.split("\t")[0] for line in r.stdout.splitlines()]
                # the picker always offers the fallback shell (a shell at the root is never wrong)
                self.assertEqual(got, want + ["shell"])
        self.assertFalse(self.pt.alive(), "--list-windows started a server")

    def test_bare_has_no_tasks_and_no_error(self):
        r = self.store("fx-bare", "fx-bare", "--list-windows")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("tasks", r.stdout)
        self.assertNotIn("messages", r.stdout)

    def test_project_mode_offers_no_store_tab(self):
        r = support.run("sessionview-session", "alpha", "--socket", self.pt.sock,
                        "--store", self.fx.path("fx-legacy"), "--list-windows", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = [line.split("\t")[0] for line in r.stdout.splitlines()]
        for n in ("slipbox", "scripts"):
            self.assertNotIn(n, got)
        self.assertIn("project", got)

    def test_help_prints_the_whole_store_mode_paragraph(self):
        r = support.run("sessionview-session", "--help", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--store-view STORENAME", r.stdout)
        self.assertTrue(r.stdout.rstrip().endswith("No recency line: a store is not a project."),
                        r.stdout[-200:])

    def test_config_key_flag(self):
        r = support.run("sessionview-config", "windows", "--key", "store_windows", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([line.split("\t")[1] for line in r.stdout.splitlines()],
                         ["tasks", "slipbox", "scripts", "messages", "shell"])
        r = support.run("sessionview-config", "windows", env=self.env)
        self.assertIn("project", [line.split("\t")[1] for line in r.stdout.splitlines()])


class Case2Plan(StoreBase):
    """§6 case 2: the plan and PROJDIR, with no tmux (--print)."""

    def plan(self, session, ident):
        r = self.store(session, ident, "--print")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stderr

    def test_projdir_by_the_q10_rule(self):
        for ident, rel in PROJDIR.items():
            sessions = [ident] + (["store"] if ident == "fx-legacy" else [])
            for session in sessions:
                with self.subTest(store=ident, session=session):
                    want = os.path.join(self.fx.path(ident), rel) if rel else "NONE"
                    self.assertIn(f" projdir={want} ", self.plan(session, ident))

    def test_projects_store_wins_over_identity(self):
        os.makedirs(os.path.join(self.fx.path("fx-legacy"), "projects", "fx-legacy"))
        want = os.path.join(self.fx.path("fx-legacy"), "projects", "store")
        self.assertIn(f" projdir={want} ", self.plan("fx-legacy", "fx-legacy"))

    def test_typed_lines(self):
        p = self.plan("fx-legacy", "fx-legacy")
        self.assertIn("send-keys -t =fx-legacy:tasks tm task list --project store C-m", p)
        self.assertIn("send-keys -t =fx-legacy:messages sessionview-messages fx-legacy C-m", p)
        p = self.plan("fx-named", "fx-named")
        self.assertIn("send-keys -t =fx-named:tasks tm task list --project fx-named C-m", p)

    def test_messages_keyed_by_identity_never_the_session(self):
        p = self.plan("store", "fx-legacy")
        self.assertIn("sessionview-messages fx-legacy C-m", p)
        self.assertNotIn("sessionview-messages store", p)

    def test_no_repo_lookup_and_no_recency(self):
        self.plan("fx-legacy", "fx-legacy")
        self.assertFalse(any(line.startswith("project get") for line in self.fx.log()), self.fx.log())
        self.assertFalse(os.path.exists(os.path.join(self.fx.state, "recent.tsv")))


@unittest.skipUnless(support.have_tmux(), support.TMUX_SKIP)
class Case3PrivateServer(StoreBase):
    """§6 case 3: on a real PRIVATE server. sessionview never boots servers."""

    def test_a_down_server_is_refused(self):
        r = self.store("fx-named", "fx-named")
        self.assertEqual(r.returncode, 2)
        self.assertIn("tm store boot", r.stderr)
        self.assertFalse(self.pt.alive(), "store mode started a down server")

    def test_b_after_boot_adds_the_oracle_tabs(self):
        for ident in ("fx-corp", "fx-legacy", "fx-named"):
            with self.subTest(store=ident):
                self.boot(ident)
                (boot_i, _, _), = self.pt.windows(ident)   # the boot window (its name follows the shell)
                r = self.store(ident, ident)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.tabs(ident), (boot_i, ORACLE[ident]))
                self.assertEqual(self.active_index(ident), boot_i, "no --fresh: the window must not move")
                r = self.store(ident, ident, "--fresh")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.tabs(ident), (boot_i, ORACLE[ident]), "not idempotent")
                self.assertEqual(self.active(ident), "tasks")
                r = self.store(ident, ident)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.tabs(ident), (boot_i, ORACLE[ident]), "not idempotent")
                self.assertEqual(self.active(ident), "tasks", "a re-run without --fresh moved the window")

    def test_b_fresh_lands_on_tasks_after_boot(self):
        self.boot("fx-named")
        (boot_i, _, _), = self.pt.windows("fx-named")
        r = self.store("fx-named", "fx-named", "--fresh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.tabs("fx-named"), (boot_i, ORACLE["fx-named"]))
        self.assertEqual(self.active("fx-named"), "tasks")
        env = self.pt.tmux("show-environment", "-g", "TASKMASTER_STORE")
        self.assertEqual(env.stdout.strip(), "TASKMASTER_STORE=fx-named")

    def test_c_retrofit_only_adds(self):
        t = self.pt.tmux
        self.assertEqual(t("new-session", "-d", "-s", "store", "-n", "project").returncode, 0)
        for n in ("gap", "messages", "work"):
            t("new-window", "-d", "-t", "=store:", "-n", n)
        t("kill-window", "-t", "=store:gap")              # a hole in the indices: not to be filled
        t("select-window", "-t", "=store:work")
        before = self.pt.windows("store")
        self.assertEqual([n for _, n, _ in before], ["project", "messages", "work"])
        r = self.store("store", "fx-legacy")
        self.assertEqual(r.returncode, 0, r.stderr)
        after = self.pt.windows("store")
        self.assertEqual([(i, n) for i, n, _ in after[:3]], [(i, n) for i, n, _ in before],
                         "an existing window moved or was renamed")
        self.assertEqual([n for _, n, _ in after[3:]], ["tasks", "slipbox", "scripts"])
        self.assertTrue(all(i > before[-1][0] for i, _, _ in after[3:]), f"not appended: {after}")
        self.assertEqual([n for _, n, _ in after].count("messages"), 1, "a second messages window")
        self.assertEqual(self.active("store"), "work")

    def test_d_never_creates_store(self):
        self.assertEqual(self.pt.tmux("new-session", "-d", "-s", "alpha").returncode, 0)
        r = self.store("store", "fx-legacy")
        self.assertEqual(r.returncode, 2)
        self.assertIn("never creates a 'store' session", r.stderr)
        self.assertEqual(self.pt.sessions(), ["alpha"])

    def test_e_creates_the_identity_on_a_live_server(self):
        self.assertEqual(self.pt.tmux("new-session", "-d", "-s", "alpha").returncode, 0)
        alpha = self.pt.windows("alpha")
        r = self.store("fx-corp", "fx-corp")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.names("fx-corp"), ORACLE["fx-corp"])
        self.assertEqual(self.active("fx-corp"), "tasks")
        self.assertEqual(self.pt.windows("alpha"), alpha, "alpha was touched")
        self.assertEqual(sorted(self.pt.sessions()), ["alpha", "fx-corp"])
        self.assertFalse(any(line.startswith("store boot") for line in self.fx.log()), self.fx.log())
        self.assertFalse(os.path.exists(os.path.join(self.fx.state, "recent.tsv")),
                         "a store session joined the project recency")

    def test_e_bare_creates_slipbox_only(self):
        self.assertEqual(self.pt.tmux("new-session", "-d", "-s", "alpha").returncode, 0)
        r = self.store("fx-bare", "fx-bare")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.names("fx-bare"), ["slipbox"])


if __name__ == "__main__":
    unittest.main()
