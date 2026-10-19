"""Smoke: every shipped script parses, every shipped config file parses."""
import glob
import json
import os
import shutil
import subprocess
import tomllib
import unittest

from tests import support


def rel(p):
    return os.path.relpath(p, support.REPO)


class Scripts(unittest.TestCase):
    def test_found_some(self):
        kinds = {k for _, k in support.scripts()}
        self.assertIn("python", kinds)
        self.assertIn("bash", kinds)

    def test_python_compiles(self):
        for path, kind in support.scripts():
            if kind != "python":
                continue
            with self.subTest(script=rel(path)):
                with open(path, encoding="utf-8") as f:
                    compile(f.read(), path, "exec")   # no __pycache__ written

    def test_shell_parses(self):
        for path, kind in support.scripts():
            if kind not in ("bash", "sh"):
                continue
            shell = shutil.which(kind)
            if shell is None:
                self.skipTest(f"no {kind} on PATH")
            with self.subTest(script=rel(path), shell=kind):
                r = subprocess.run([shell, "-n", path], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)


class ConfigFiles(unittest.TestCase):
    def test_config_json_is_an_object(self):
        with open(os.path.join(support.CONFIG, "config.json"), encoding="utf-8") as f:
            d = json.load(f)
        self.assertIsInstance(d, dict)
        self.assertTrue(d)

    def test_plugin_manifests_parse(self):
        found = sorted(glob.glob(os.path.join(support.PLUGINS, "*", "plugin.toml")))
        self.assertTrue(found, "no plugins/*/plugin.toml")
        for path in found:
            with self.subTest(manifest=rel(path)):
                with open(path, "rb") as f:
                    d = tomllib.load(f)
                self.assertIsInstance(d.get("id"), str)
                self.assertIsInstance(d.get("actions"), list)

    def test_claude_plugin_json_parses(self):
        with open(os.path.join(support.REPO, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["name"], "sessionview")


if __name__ == "__main__":
    unittest.main()
