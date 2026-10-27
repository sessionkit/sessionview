"""The sidebar's agent list asks the launcher (`session start --list-agents`)
and keeps only the NAME of each line. The launcher prints NAME<TAB>MARK, and a
mark can hold a space (`claude<TAB>built in`); a line may also be a name
alone. The sidebar runs in a subprocess under a scratch HOME with a stub
`session` first on PATH, never imported into this process."""
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
    print(json.dumps(m.registered_agents()))
''')


class RegisteredAgents(unittest.TestCase):
    def names(self, listing):
        """registered_agents() when the launcher prints LISTING."""
        with tempfile.TemporaryDirectory(prefix="sv-test-") as tmp, \
                support.scratch_env() as (env, home):
            with open(os.path.join(tmp, "list"), "w") as f:
                f.write(listing)
            stub = os.path.join(tmp, "session")
            with open(stub, "w") as f:
                f.write('#!/bin/sh\ncase "$*" in\n'
                        f'  *--list-agents*) cat "{tmp}/list" ;;\n'
                        '  *) exit 0 ;;\nesac\n')
            os.chmod(stub, 0o755)
            env["PATH"] = tmp + os.pathsep + env.get("PATH", "")
            r = subprocess.run([sys.executable, "-B", "-c", HARNESS, SIDEBAR],
                               env=env, capture_output=True, text=True,
                               timeout=30, cwd=support.REPO)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout.strip().splitlines()[-1])

    def test_name_field_only_when_the_mark_holds_a_space(self):
        self.assertEqual(self.names("claude\tbuilt in\nengineer\nworker\n"),
                         ["claude", "engineer", "worker"])

    def test_names_alone_one_per_line(self):
        self.assertEqual(self.names("cleo\npat\n"), ["cleo", "pat"])

    def test_blank_lines_and_empty_names_are_dropped(self):
        self.assertEqual(self.names("\npat\tmark\n\tstray mark\n  \n"), ["pat"])


if __name__ == "__main__":
    unittest.main()
