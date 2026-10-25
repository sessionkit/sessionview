"""bin/tmux-send-agent: a pane title is shown LITERALLY, never as a format.

A pane's title is set by whatever runs in the pane (OSC 2), so it is the
pane's text, not ours. tmux-send-agent shows it in a `display-message`
status line; without -l, tmux expanded a `#{...}` in it (a title of
`a #{host}` showed the host name). Every status line it shows is now
literal: the title, and the `message send` error it may echo.

The probe is harmless: `#{session_name}` of a private server, whose session
name is known. No client is attached, so a status line is shown nowhere: a
`tmux` shim first on PATH adds -p to the tool's display-message, and the
REAL tmux prints to stdout exactly what it would have shown (the same
expansion, or none under -l).

tmux runs on a private socket only (support.private_tmux). The tool calls a
bare `tmux`, so it is pointed at that server by TMUX (the socket path),
under the scratch TMUX_TMPDIR where no default server exists.
"""
import os
import shlex
import shutil
import unittest

from tests import support

SESSION = "svtitle"
FORMAT = "#{session_name}"


class TitleIsLiteral(unittest.TestCase):

    def setUp(self):
        support.require_tmux()
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self._pt = support.private_tmux("title")
        self.pt = self._pt.__enter__()
        r = self.pt.tmux("-f", "/dev/null", "new-session", "-d", "-s", SESSION, "-x", "80", "-y", "24")
        self.assertEqual(r.returncode, 0, r.stderr)
        sock = self.pt.tmux("display-message", "-p", "#{socket_path}").stdout.strip()
        self.pane = self.pt.tmux("display-message", "-p", "-t", f"={SESSION}:", "#{pane_id}").stdout.strip()
        self.bin = os.path.join(self.home, "bin")
        os.makedirs(self.bin)
        real = shutil.which("tmux")
        shim = os.path.join(self.bin, "tmux")
        with open(shim, "w") as f:
            f.write('#!/bin/sh\n[ "$1" = display-message ] && { shift; set -- display-message -p "$@"; }\n'
                    f'exec {shlex.quote(real)} "$@"\n')
        os.chmod(shim, 0o755)
        self.env = self.pt.env(env)
        self.env["PATH"] = self.bin + os.pathsep + self.env.get("PATH", "")
        self.env["TMUX"] = f"{sock},0,0"
        self.env["SESSIONVIEW_FROM"] = "tester"
        self.env["SESSIONVIEW_CONFIG"] = os.path.join(self.home, "none.json")

    def tearDown(self):
        self._pt.__exit__(None, None, None)
        self._scratch.__exit__(None, None, None)

    def message_shim(self, body):
        p = os.path.join(self.bin, "message")
        with open(p, "w") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(p, 0o755)

    def title(self, text):
        """Set the pane's title to TEXT exactly, as OSC 2 would. select-pane
        -T expands formats itself, so a # is doubled to arrive as one."""
        r = self.pt.tmux("select-pane", "-t", self.pane, "-T", text.replace("#", "##"))
        self.assertEqual(r.returncode, 0, r.stderr)
        got = self.pt.tmux("display-message", "-p", "-t", self.pane, "#{pane_title}").stdout.rstrip("\n")
        self.assertEqual(got, text)

    def send(self):
        return support.run("tmux-send-agent", self.pane, "hello", env=self.env)

    def test_a_title_with_no_address_is_shown_literally(self):
        self.message_shim("exit 0\n")
        self.title(f"pre {FORMAT} post")
        r = self.send()
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn(f"no agent address in pane title 'pre {FORMAT} post'", r.stdout)
        self.assertNotIn(f"pre {SESSION} post", r.stdout)

    def test_a_send_error_is_shown_literally(self):
        self.message_shim(f"echo 'refused {FORMAT}' >&2\nexit 1\n")
        self.title("x super.demo")
        r = self.send()
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn(f"send FAILED -> super.demo: refused {FORMAT}", r.stdout)
        self.assertNotIn(f"refused {SESSION}", r.stdout)

    def test_a_good_send_still_reports(self):
        self.message_shim("exit 0\n")
        self.title("x super.demo")
        r = self.send()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("sent 'hello' -> super.demo (from tester)", r.stdout)


if __name__ == "__main__":
    unittest.main()
