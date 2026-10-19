"""bin/sessionview-config against a scratch home file (SESSIONVIEW_CONFIG):
set, get, unset round-trip, and the template is the default."""
import json
import os
import unittest

from tests import support


class ConfigRoundTrip(unittest.TestCase):
    def setUp(self):
        self._ctx = support.scratch_env()
        self.env, self.home = self._ctx.__enter__()
        self.cfg = os.path.join(self.home, "scratch", "config.json")
        self.env["SESSIONVIEW_CONFIG"] = self.cfg
        with open(os.path.join(support.CONFIG, "config.json"), encoding="utf-8") as f:
            self.template = json.load(f)

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def cli(self, *args):
        return support.run("sessionview-config", *args, env=self.env)

    def test_path_is_the_scratch_file(self):
        r = self.cli("path")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), self.cfg)

    def test_first_read_makes_home_file_from_template(self):
        r = self.cli("get", "terminal")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.rstrip("\n"), self.template["terminal"])
        self.assertTrue(os.path.isfile(self.cfg))
        for d in (".sessionkit", ".sessionview"):
            self.assertFalse(os.path.exists(os.path.join(self.home, d)),
                             f"wrote under ~/{d} despite SESSIONVIEW_CONFIG")

    def test_set_get_unset_string(self):
        r = self.cli("set", "terminal", "ghostty")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.cli("get", "terminal", "--where")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.rstrip("\n").split("\t"), ["ghostty", self.cfg])
        with open(self.cfg, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["terminal"], "ghostty")
        r = self.cli("unset", "terminal")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.cli("get", "terminal", "--where")
        self.assertEqual(r.stdout.rstrip("\n").split("\t")[1],
                         os.path.join(support.CONFIG, "config.json"))

    def test_set_bool_is_typed_by_the_template(self):
        self.assertIsInstance(self.template["fullscreen"], bool)
        want = not self.template["fullscreen"]
        r = self.cli("set", "fullscreen", "true" if want else "false")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.cli("get", "fullscreen", "--json")
        self.assertEqual(json.loads(r.stdout), want)

    def test_unknown_key_is_refused(self):
        r = self.cli("set", "no_such_key_sv", "x")
        self.assertEqual(r.returncode, 2)
        if os.path.exists(self.cfg):
            with open(self.cfg, encoding="utf-8") as f:
                self.assertNotIn("no_such_key_sv", json.load(f))


if __name__ == "__main__":
    unittest.main()


class OneConfigCommand(unittest.TestCase):
    """`sessionview-config` is both the engine and the screen: `list` prints
    the screen's rows, and with no terminal a bare call prints the usage."""

    def test_list_prints_every_template_key(self):
        with support.scratch_env() as (env, _):
            r = support.run("sessionview-config", "list", env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("autostart_agent", r.stdout)

    def test_bare_without_a_terminal_prints_usage(self):
        with support.scratch_env() as (env, _):
            r = support.run("sessionview-config", env=env)
            self.assertEqual(r.returncode, 1)
            self.assertIn("the settings screen", r.stderr)
