"""The state dir moves once from its pre-release name, ~/.local/state/herd,
to ~/.local/state/sessionview, and two of its files take their new names.

The trigger is a bare `sessionview` with no terminal: the frame path sources
lib/state.sh, then the frame refuses (not a tty) and touches nothing else. It
was `sessionview -h` until SV-197, and `sessionview config path` until SV-200:
asking for help touches nothing, and a routed verb is exec'd before
lib/state.sh, so only a tool that uses the state dir (the frame, the sidebar,
session, messages) sources it, after its own flags."""
import os
import subprocess
import unittest

from tests.support import BIN, REPO, scratch_env


def run_frame_path(env):
    """`sessionview` with stdin and stdout not a tty: state.sh, then refused."""
    return subprocess.run([os.path.join(BIN, "sessionview")], env=env, cwd=REPO,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)


class StateMigration(unittest.TestCase):
    def seed(self, home):
        old = os.path.join(home, ".local", "state", "herd")
        os.makedirs(os.path.join(old, "mutt"))
        for name, text in (("herd-recent.tsv", "main\n"), ("herd.tty", "/dev/ttys001\n")):
            with open(os.path.join(old, name), "w") as fh:
                fh.write(text)
        return old, os.path.join(home, ".local", "state", "sessionview")

    def test_1_old_dir_moves_and_files_are_renamed(self):
        with scratch_env() as (env, home):
            old, new = self.seed(home)
            r = run_frame_path(env)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("not a terminal", r.stderr)
            self.assertFalse(os.path.exists(old))
            self.assertEqual(sorted(os.listdir(new)), ["frame.tty", "mutt", "recent.tsv"])
            with open(os.path.join(new, "recent.tsv")) as fh:
                self.assertEqual(fh.read(), "main\n")

    def test_2_an_existing_new_dir_is_never_overwritten(self):
        with scratch_env() as (env, home):
            old, new = self.seed(home)
            os.makedirs(new)
            run_frame_path(env)
            self.assertTrue(os.path.isdir(old))
            self.assertEqual(os.listdir(new), [])

    def test_3_a_custom_state_dir_leaves_the_old_one_alone(self):
        with scratch_env() as (env, home):
            old, _ = self.seed(home)
            env["SESSIONVIEW_STATE"] = os.path.join(home, "elsewhere")
            run_frame_path(env)
            self.assertTrue(os.path.isdir(old))
            self.assertTrue(os.path.isdir(env["SESSIONVIEW_STATE"]))


if __name__ == "__main__":
    unittest.main()
