"""autostart_agent is read for the session's own directory: a project's
.sessionview overrides the home choice, so one agent does not start in
every project."""
import json
import os
import subprocess
import unittest
import uuid

from tests import support


@unittest.skipUnless(support.have_tmux(), support.TMUX_SKIP)
class AutostartProjectLayer(unittest.TestCase):
    def status(self, home_choice, project_choice):
        with support.scratch_env() as (env, home):
            settings = os.path.join(home, ".sessionkit", "view", "settings")
            os.makedirs(settings)
            with open(os.path.join(settings, "view.json"), "w") as fh:
                json.dump({"autostart_agent": home_choice}, fh)
            proj = os.path.join(home, "proj")
            os.makedirs(proj)
            if project_choice is not None:
                with open(os.path.join(proj, ".sessionview"), "w") as fh:
                    json.dump({"autostart_agent": project_choice}, fh)
            sock = "sv-test-" + uuid.uuid4().hex[:8]
            tmux = ["tmux", "-L", sock, "-f", "/dev/null"]
            subprocess.run(tmux + ["new-session", "-d", "-s", "p", "-c", proj], env=env, check=True)
            try:
                return support.run("sessionview-autostart", "--status", sock, "p", env=env).stdout
            finally:
                subprocess.run(tmux + ["kill-server"], env=env, capture_output=True)

    def test_project_off_beats_home_agent(self):
        self.assertIn("(off)", self.status("cleo", ""))

    def test_project_names_another_agent(self):
        self.assertIn("autostart_agent=pat", self.status("cleo", "pat"))

    def test_no_project_file_keeps_the_home_choice(self):
        self.assertIn("autostart_agent=cleo", self.status("cleo", None))


if __name__ == "__main__":
    unittest.main()
