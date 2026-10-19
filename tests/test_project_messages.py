"""bin/sessionview-session, project mode: the `messages` tab is STORE-QUALIFIED
(SV-120).

A project session used to look its mail up by the bare project NAME, which
resolves through the host-global postfix map: a second store's `store` session opened
the first store's `store` box. Now the session's store identity (the `tm store list`
record whose realpath is --store's: `store` field, else `name`) qualifies both
the has_mail predicate and the typed command, `sessionview-messages NAME
--store STOREID`. The rca's four cases (findings/rca.md, "Tests for fix-001"),
plus the no-identity rule the foreman chose (no registry = bare name; a
registry without this store = no tab).

Every tmux call is on a private socket (support.private_tmux: `-L sv-test-*`
under a scratch TMUX_TMPDIR); nothing here names or touches a real server.
"""
import json
import os
import shlex
import unittest

from tests import support

CMD = "sessionview-messages"


class ProjectMailBase(unittest.TestCase):
    TAG = "pmail"

    def setUp(self):
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self._pt = support.private_tmux(self.TAG)
        self.pt = self._pt.__enter__()
        self.fx = support.StoreFixtures(os.path.join(self.home, "fx"), self.pt)
        self.env = self.fx.env(env)
        with open(self.fx.fixtures) as f:
            self.data = json.load(f)

    def tearDown(self):
        self._pt.__exit__(None, None, None)
        self._scratch.__exit__(None, None, None)

    # -- fixture edits: the shims re-read fixtures.json on every call ----------
    def save(self):
        with open(self.fx.fixtures, "w") as f:
            json.dump(self.data, f)

    def boxes(self, *names):
        """Give each NAME (`slug/project`, or a bare `project` = the postfix
        map's host-global row) a maildir, the way `message path` would find it."""
        for n in names:
            d = os.path.join(self.fx.base, "mail", *n.split("/"))
            for sub in ("new", "cur", "tmp"):
                os.makedirs(os.path.join(d, sub), exist_ok=True)
            self.data["boxes"][n] = d
        self.save()

    def record(self, ident):
        return next(s for s in self.data["stores"] if s["store"] == ident)

    # -- runs ---------------------------------------------------------------
    def project(self, name, store_path, *extra):
        return support.run("sessionview-session", name, "--socket", self.pt.sock,
                           "--store", store_path, *extra, env=self.env)

    def listed(self, name, ident=None, path=None):
        """{tab: hint} that --list-windows offers for NAME in that store."""
        r = self.project(name, path or self.fx.path(ident), "--list-windows")
        self.assertEqual(r.returncode, 0, r.stderr)
        return dict(line.split("\t", 1) for line in r.stdout.splitlines())

    def plan(self, name, ident=None, path=None):
        r = self.project(name, path or self.fx.path(ident), "--print")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stderr


class SharedNameTwoStores(ProjectMailBase):
    """rca case 1: two stores share a project name; each opens its OWN box."""

    def setUp(self):
        super().setUp()
        # `store` is a project in both fx-corp and fx-legacy; the bare
        # row is the postfix map's, and it points at fx-corp's (as on a real host)
        self.boxes("fx-corp/store", "fx-legacy/store", "store")

    def test_list_windows_names_each_store(self):
        for ident in ("fx-corp", "fx-legacy"):
            with self.subTest(store=ident):
                got = self.listed("store", ident)
                self.assertEqual(got.get("messages"), f"{CMD} store --store {ident}")

    def test_print_types_the_qualified_command(self):
        for ident in ("fx-corp", "fx-legacy"):
            with self.subTest(store=ident):
                p = self.plan("store", ident)
                self.assertIn(f"send-keys -t =store:messages {CMD} store --store {ident} C-m", p)
                self.assertIn(f" store_id={ident} ", p)

    def test_the_typed_command_opens_that_stores_folder(self):
        """End to end: the command the tab would type resolves fx-legacy's box."""
        cmd = shlex.split(self.listed("store", "fx-legacy")["messages"])
        self.assertEqual(cmd[0], CMD)
        r = support.run(CMD, *cmd[1:], "--print", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        want = self.data["boxes"]["fx-legacy/store"]
        self.assertIn(f"box=fx-legacy/store folder={want} ", r.stdout)
        self.assertNotIn(self.data["boxes"]["store"] + " ", r.stdout)


class OneStoreHasNoBox(ProjectMailBase):
    """rca case 2 (repro step 8): fx-legacy has no `store` box, fx-corp does.
    fx-legacy's session gets NO messages tab - never fx-corp's box."""

    def setUp(self):
        super().setUp()
        self.boxes("fx-corp/store", "store")

    def test_no_tab_for_the_store_without_a_box(self):
        self.assertNotIn("messages", self.listed("store", "fx-legacy"))
        self.assertNotIn(":messages", self.plan("store", "fx-legacy"))
        # and the other store still has its own
        self.assertEqual(self.listed("store", "fx-corp").get("messages"),
                         f"{CMD} store --store fx-corp")

    @unittest.skipUnless(support.have_tmux(), support.TMUX_SKIP)
    def test_on_a_private_server(self):
        """A real create on the private socket: fx-legacy's `store` session is
        built without a messages window; `--window messages` is refused (rc 3)."""
        r = self.project("store", self.fx.path("fx-legacy"))
        self.assertEqual(r.returncode, 0, r.stderr)
        names = [n for _, n, _ in self.pt.windows("store")]
        self.assertIn("project", names)
        self.assertNotIn("messages", names)
        r = self.project("store", self.fx.path("fx-legacy"), "--window", "messages")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertNotIn("messages", [n for _, n, _ in self.pt.windows("store")])

    @unittest.skipUnless(support.have_tmux(), support.TMUX_SKIP)
    def test_on_a_private_server_with_a_box(self):
        r = self.project("store", self.fx.path("fx-corp"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("messages", [n for _, n, _ in self.pt.windows("store")])


class IdentityIsTheStoreField(ProjectMailBase):
    """rca case 3: a record whose `name` is not its `store` (a store named
    `default` is mailed under its slug). The `store` field is the slug, never `name`."""

    def setUp(self):
        super().setUp()
        self.record("fx-corp")["name"] = "default"
        self.boxes("fx-corp/alpha")      # and no default/alpha: `name` finds nothing

    def test_store_field_wins(self):
        self.assertEqual(self.listed("alpha", "fx-corp").get("messages"),
                         f"{CMD} alpha --store fx-corp")

    def test_name_is_the_fallback(self):
        rec = self.record("fx-corp")
        rec["store"] = ""
        self.boxes("default/alpha")
        self.assertEqual(self.listed("alpha", path=self.fx.path("fx-corp")).get("messages"),
                         f"{CMD} alpha --store default")

    def test_never_the_path_basename(self):
        # the dir is fx-corp, the record says the store is `mailslug`
        self.record("fx-corp")["store"] = "mailslug"
        self.save()
        self.assertNotIn("messages", self.listed("alpha", "fx-corp"))
        self.boxes("mailslug/alpha")
        self.assertEqual(self.listed("alpha", "fx-corp").get("messages"),
                         f"{CMD} alpha --store mailslug")


class NoIdentity(ProjectMailBase):
    """rca case 4 and the foreman's no-identity rule."""

    def stray(self):
        """A store dir the registry does not hold, with a `store` project."""
        p = os.path.join(os.path.realpath(self.fx.base), "stores", "fx-stray")
        os.makedirs(os.path.join(p, "projects", "store"), exist_ok=True)
        return p

    def test_unregistered_store_gets_no_tab(self):
        # the bare host-global row exists (fx-corp's) - and must not be used
        self.boxes("store", "fx-corp/store")
        p = self.stray()
        self.assertNotIn("messages", self.listed("store", path=p))
        plan = self.plan("store", path=p)
        self.assertNotIn(":messages", plan)
        self.assertIn(" store_id=UNREGISTERED ", plan)

    def test_no_registry_keeps_the_bare_name(self):
        """No stores registered at all (a new user with no taskmaster): the bare name, as before."""
        self.data["stores"] = []
        self.boxes("alpha")
        got = self.listed("alpha", path=self.fx.path("fx-corp"))
        self.assertEqual(got.get("messages"), f"{CMD} alpha --store ''")
        # and that command still resolves the bare box
        cmd = shlex.split(got["messages"])
        r = support.run(CMD, *cmd[1:], "--print", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("box=alpha ", r.stdout)

    def test_a_failing_tm_is_no_registry(self):
        with open(os.path.join(self.fx.bin, "tm"), "w") as f:
            f.write("#!/bin/sh\necho 'tm: boom' >&2\nexit 1\n")
        self.boxes("alpha")
        self.assertEqual(self.listed("alpha", "fx-corp").get("messages"),
                         f"{CMD} alpha --store ''")


class StoreModeUnchanged(ProjectMailBase):
    """{store} is still the store view's identity in store mode (SV-92)."""

    def test_store_mode_messages(self):
        r = support.run("sessionview-session", "fx-legacy", "--store-view", "fx-legacy",
                        "--socket", self.pt.sock, "--store", self.fx.path("fx-legacy"),
                        "--print", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"send-keys -t =fx-legacy:messages {CMD} fx-legacy C-m", r.stderr)
        # store mode never asks the registry: it was given the identity
        self.assertFalse(any(line.startswith("store list") for line in self.fx.log()), self.fx.log())


if __name__ == "__main__":
    unittest.main()
