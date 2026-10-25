"""The [+] popup: no tmux format is spliced into its shell command.

tmux/frame.conf binds the tab bar's [+] to `display-popup ... -d DIR CMD`.
CMD is a shell string. It carried `--popup '#{pane_current_path}'`, safe only
because display-popup does not expand formats in CMD (the value arrived
literally and was never used). If it ever did, a directory name would be
spliced into a shell line. Now CMD names no format at all, and
sessionview-newtab --popup takes the popup's own directory, $PWD: the -d
argument, which tmux expands as an ARGUMENT, never as shell.

No tmux runs here: a `tmux` stub first on PATH logs its argv, so the tab a
popup would make is read, not made.
"""
import os
import shlex
import subprocess
import unittest

from tests import support


def popup_binding():
    """The words of frame.conf's [+] binding (`tmux bind ... display-popup ...`)."""
    with open(os.path.join(support.REPO, "tmux", "frame.conf"), encoding="utf-8") as f:
        for line in f:
            if "MouseDown1StatusRight" in line and "display-popup" in line:
                return shlex.split(line, comments=True)
    raise AssertionError("frame.conf has no [+] display-popup binding")


class PopupCommand(unittest.TestCase):

    def test_the_popup_shell_command_names_no_format(self):
        words = popup_binding()
        cmd = words[-1]
        self.assertIn("bin/sessionview-newtab --popup", cmd)
        self.assertNotIn("#{", cmd)

    def test_the_popup_directory_is_still_the_panes(self):
        words = popup_binding()
        self.assertEqual(words[words.index("-d") + 1], "#{pane_current_path}")


class PopupDirectory(unittest.TestCase):

    def setUp(self):
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self.cwd = os.path.realpath(os.path.join(self.home, "work", "proj"))
        os.makedirs(self.cwd)
        stubs = os.path.join(self.home, "stubs")
        os.makedirs(stubs)
        self.log = os.path.join(self.home, "tmux.log")
        stub = os.path.join(stubs, "tmux")
        with open(stub, "w") as f:
            f.write(f'#!/bin/sh\nprintf "%s\\n" "$@" > {shlex.quote(self.log)}\n')
        os.chmod(stub, 0o755)
        self.env = dict(env, PATH=stubs + os.pathsep + env.get("PATH", ""))
        self.env.pop("TMUX", None)
        self.env.pop("TMUX_PANE", None)

    def tearDown(self):
        self._scratch.__exit__(None, None, None)

    def popup(self, *args):
        """Enter at the plain name box: an unnamed tab, made by the stub."""
        r = subprocess.run([os.path.join(support.BIN, "sessionview-newtab"), "--popup", *args],
                           env=self.env, cwd=self.cwd, input="\n",
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.log) as f:
            return f.read().splitlines()

    def test_no_dir_means_the_popups_own_directory(self):
        argv = self.popup()
        self.assertEqual(argv[:1], ["new-window"])
        self.assertEqual(argv[argv.index("-c") + 1], self.cwd)

    def test_an_explicit_dir_still_wins(self):
        other = os.path.join(self.home, "elsewhere")
        os.makedirs(other)
        argv = self.popup(other)
        self.assertEqual(argv[argv.index("-c") + 1], other)


if __name__ == "__main__":
    unittest.main()
