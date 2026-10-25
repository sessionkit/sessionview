"""`user_mail_command` is template-or-home only, like `agent_command`.

bin/sessionview-usermail types user_mail_command into a window with Enter.
It was safe only because that tool reads it with no --store and no
--project, so no untrusted layer was ever in the cascade. A future caller
passing --project would have re-opened the hole: a cloned repo's
`.sessionview` naming the command. Now it is one of the keys that run
something (EXEC_KEYS): a store or project layer that sets it is ignored and
named on stderr, and the trusted value stands.

Nothing runs: sessionview-config only prints.
"""
import json
import os
import unittest

from tests import support

PLANT = "touch planted-marker"
HOME = "mutt -F ~/my-muttrc"


class UserMailTrust(unittest.TestCase):

    def setUp(self):
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self.cfg = os.path.join(self.home, "view.json")
        self.env = dict(env, SESSIONVIEW_CONFIG=self.cfg)
        self.repo = os.path.realpath(os.path.join(self.home, "work", "repo"))
        self.store = os.path.realpath(os.path.join(self.home, "store"))
        os.makedirs(self.repo)
        os.makedirs(self.store)
        with open(os.path.join(support.CONFIG, "config.json"), encoding="utf-8") as f:
            self.template = json.load(f)["user_mail_command"]

    def tearDown(self):
        self._scratch.__exit__(None, None, None)

    def plant(self, d):
        path = os.path.join(d, ".sessionview")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"user_mail_command": PLANT}, f)
        return path

    def get(self, *args):
        r = support.run("sessionview-config", "get", "user_mail_command", *args, "--where", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        val, src = r.stdout.rstrip("\n").split("\t")
        return val, src, r.stderr

    def test_a_project_layer_cannot_set_it(self):
        dot = self.plant(self.repo)
        val, src, err = self.get("--project", self.repo)
        self.assertEqual(val, self.template)
        self.assertNotEqual(src, dot)
        self.assertIn(f"{dot}: user_mail_command ignored", err)

    def test_a_store_layer_cannot_set_it(self):
        dot = self.plant(self.store)
        val, src, err = self.get("--store", self.store, "--project", self.repo)
        self.assertEqual(val, self.template)
        self.assertNotEqual(src, dot)
        self.assertIn(f"{dot}: user_mail_command ignored", err)

    def test_the_home_layer_still_sets_it(self):
        r = support.run("sessionview-config", "set", "user_mail_command", HOME, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.plant(self.repo)
        val, src, _ = self.get("--project", self.repo)
        self.assertEqual((val, src), (HOME, self.cfg))


if __name__ == "__main__":
    unittest.main()
