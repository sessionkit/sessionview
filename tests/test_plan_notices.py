"""sessionview-session --print shows what the config cascade ignored.

A store's or project's `.sessionview` never sets what runs; each key it tried
is dropped and named on stderr by sessionview-config ("... ignored"). The
session builder sent that stderr to /dev/null, so the notices never showed,
not even in a --print plan, the one place you look to see what a session
will do. Under --print the windows list's notices now come through, once
each; a real run and --list-windows (the sidebar's call) stay quiet.

Nothing runs: --print on a private socket that is never started.
"""
import unittest

from tests import support
from tests.test_untrusted_config import UntrustedBase, planted, write_json


class PlanNotices(UntrustedBase):
    TAG = "notice"

    def test_print_names_each_ignored_key_once(self):
        plan = self.project_plan()
        for what in ("windows[pwn].command ignored", "windows[git].command ignored",
                     "agent_command ignored"):
            with self.subTest(what=what):
                self.assertEqual(plan.count(f"{self.dot}: {what}"), 1, plan)

    def test_print_names_a_skipped_entry(self):
        write_json(self.dot, planted(extra_windows=[{"name": "", "position": 3}]))
        plan = self.project_plan()
        self.assertIn("windows[2]: needs a name (skipped)", plan)

    def test_list_windows_stays_quiet(self):
        r = support.run("sessionview-session", "evil", "--socket", self.pt.sock,
                        "--store", self.fx.path("fx-legacy"), "--repo", self.repo,
                        "--list-windows", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("ignored", r.stderr)


if __name__ == "__main__":
    unittest.main()
