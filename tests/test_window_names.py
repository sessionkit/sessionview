"""sessionview-config windows: an entry's `name` must be a string.

A name is what a window is matched by (the trusted command of the same name,
a pin in window_pins, the tab tmux makes). A `.sessionview` that gave a JSON
list as a name, `"name": ["git"]`, passed the name check (it took str() of
the value) and then traced back at the pin lookup (`unhashable type:
'list'`): the windows verb exited 1 and the session opened with no tabs.
Nothing ran; it was a denial of service from any cloned repo. Now a name
that is not a string is skipped and named on stderr, like any bad entry, and
the rest of the list still comes out.
"""
import json
import os
import unittest

from tests import support

NOT_STRINGS = (["git"], {"a": 1}, 7, True, None)


class WindowNames(unittest.TestCase):

    def setUp(self):
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self.repo = os.path.realpath(os.path.join(self.home, "work", "proj"))
        os.makedirs(self.repo)
        self.env = dict(env, SESSIONVIEW_CONFIG=os.path.join(self.home, "view.json"))

    def tearDown(self):
        self._scratch.__exit__(None, None, None)

    def layer(self, data, path=None):
        with open(path or os.path.join(self.repo, ".sessionview"), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def windows(self, *args):
        return support.run("sessionview-config", "windows", "--project", self.repo, *args, env=self.env)

    def entries(self):
        bad = [{"name": n, "position": i + 1, "when": "always", "cwd": "root"}
               for i, n in enumerate(NOT_STRINGS)]
        return bad + [{"name": "ok", "position": 50, "when": "always", "cwd": "root"}]

    def check(self, r, key):
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual([line.split("\t")[1] for line in r.stdout.splitlines()], ["ok"])
        for i, n in enumerate(NOT_STRINGS):
            with self.subTest(name=n):
                self.assertIn(f"{key}[{i}]: name {json.dumps(n)} is not a string (skipped)", r.stderr)

    def test_a_project_layer_name_that_is_not_a_string_is_skipped(self):
        self.layer({"windows": self.entries()})
        self.check(self.windows(), "windows")

    def test_with_pins_too(self):
        self.layer({"windows": self.entries(), "window_pins": {"git": True, "ok": False}})
        r = self.windows()
        self.check(r, "windows")
        self.assertEqual(r.stdout.split("\t")[6], "false", "the pin still applies to a good name")

    def test_store_windows_the_same(self):
        self.layer({"store_windows": self.entries()})
        self.check(self.windows("--key", "store_windows"), "store_windows")

    def test_the_home_layer_the_same(self):
        self.layer({"windows": self.entries()}, path=self.env["SESSIONVIEW_CONFIG"])
        self.check(self.windows(), "windows")

    def test_an_empty_name_is_still_skipped_as_before(self):
        self.layer({"windows": [{"name": "  "}, {"name": "ok"}]})
        r = self.windows()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("windows[0]: needs a name (skipped)", r.stderr)


if __name__ == "__main__":
    unittest.main()
