"""^e in the agent picker sets autostart_agent in the home layer; ^e on the
agent that already has it turns autostart off. The sidebar runs in a
subprocess under a scratch HOME, never imported into this process."""
import json
import os
import subprocess
import sys
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
    notes = []
    m.note = lambda text, title="note": notes.append(text)
    for name in sys.argv[2:]:
        m.set_autostart(name)
    print(json.dumps(notes))
''')


class StartOnOpen(unittest.TestCase):
    def run_picks(self, *names):
        with support.scratch_env() as (env, home):
            r = subprocess.run([sys.executable, "-B", "-c", HARNESS, SIDEBAR, *names],
                               env=env, capture_output=True, text=True, timeout=30, cwd=support.REPO)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(os.path.join(home, ".sessionkit", "view", "settings", "view.json")) as fh:
                return json.load(fh).get("autostart_agent"), json.loads(r.stdout.strip().splitlines()[-1])

    def test_pick_sets_the_agent(self):
        val, notes = self.run_picks("pat")
        self.assertEqual(val, "pat")
        self.assertIn("pat starts when sessionview opens", notes)

    def test_same_pick_again_turns_it_off(self):
        val, notes = self.run_picks("pat", "pat")
        self.assertEqual(val, "")
        self.assertIn("no agent starts on open", notes)

    def test_plain_claude_is_refused(self):
        val, notes = self.run_picks("-")
        self.assertEqual(val, "ask")


if __name__ == "__main__":
    unittest.main()
