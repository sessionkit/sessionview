"""sessionview-autostart's first-run question: text is on screen before the
slow launcher call, not after it (SV-96), and keys typed during that call
cannot answer the question (SV-124).

ask() runs only on a real terminal, so each test runs it in a pane of a
PRIVATE tmux server (`tmux -L sv-test-<pid>-<n> -f /dev/null`), with a fresh
HOME and a stub `session` first on PATH. The stub's `start --list-agents`
drops a marker when it is called and then BLOCKS until the test releases it,
so "before the list arrives" is a state the test holds open, not a race
against a sleep. Only that private server is ever touched, and it is killed
with -L; the default tmux server is never addressed.
"""
import itertools
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest

from tests import support

AUTOSTART = os.path.join(support.BIN, "sessionview-autostart")
_seq = itertools.count()

# The stub launcher. MARK is the directory it signals through.
STUB = """#!/bin/sh
case "$*" in
  *--list-agents*)
    : > "{mark}/called"
    i=0
    while [ ! -e "{mark}/release" ] && [ "$i" -lt 300 ]; do sleep 0.1; i=$((i + 1)); done
    if [ -f "{mark}/list" ]; then cat "{mark}/list"
    elif [ -n "{names}" ]; then printf '%s\\n' {names}
    fi
    ;;
  "list --json") echo '[]' ;;
  *) exit 0 ;;
esac
"""


def wait_for(pred, timeout):
    """Poll PRED until truthy or TIMEOUT seconds pass; return its last value."""
    end = time.monotonic() + timeout
    while True:
        v = pred()
        if v or time.monotonic() >= end:
            return v
        time.sleep(0.05)


@unittest.skipUnless(support.have_tmux(), support.TMUX_SKIP)
class FirstRunQuestion(unittest.TestCase):
    def start(self, names, raw=None):
        """Run the autostart's ask path in a private tmux pane; return (pane
        capture function, marker dir). RAW, if given, is the exact text the
        stub prints for --list-agents, in place of NAMES one per line."""
        tmp = tempfile.mkdtemp(prefix="sv-test-")
        self.addCleanup(shutil.rmtree, tmp, True)
        mark = os.path.join(tmp, "mark")
        stubs = os.path.join(tmp, "bin")
        os.mkdir(mark)
        os.mkdir(stubs)
        if raw is not None:
            with open(os.path.join(mark, "list"), "w") as f:
                f.write(raw)
        stub = os.path.join(stubs, "session")
        with open(stub, "w") as f:
            f.write(STUB.format(mark=mark, names=" ".join(names)))
        os.chmod(stub, 0o755)

        sock = f"sv-test-{os.getpid()}-{next(_seq)}"
        cm = support.scratch_env()
        env, self.home = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        env["PATH"] = stubs + os.pathsep + env.get("PATH", "")

        def tmux(*args, **kw):
            return subprocess.run(["tmux", "-L", sock, "-f", "/dev/null", *args],
                                  env=env, capture_output=True, text=True,
                                  timeout=10, **kw)

        # Kill ONLY our own -L server, even if an assertion fails, then remove
        # the socket file kill-server leaves behind (cleanups run LIFO).
        self.addCleanup(self.remove_socket, sock, env)
        self.addCleanup(tmux, "kill-server")
        # The autostart's own SOCK/SESSION args name this private server too,
        # so nothing it could do after an answer reaches a real one. The SV-96
        # tests never answer; the SV-124 tests do, and the stub `session` they
        # start exits at once. The trailing sleep keeps the pane up for the capture.
        cmd = f"{shlex.quote(AUTOSTART)} {shlex.quote(sock)} t; sleep 60"
        # -c: the session's directory is the scratch dir. autostart reads
        # autostart_agent for that directory, walking up for .sessionview
        # files, and a walk up from the checkout could reach a real
        # .sessionview above it.
        r = tmux("new-session", "-d", "-s", "t", "-x", "100", "-y", "20", "-c", tmp, cmd)
        self.assertEqual(r.returncode, 0, r.stderr)

        def screen():
            return tmux("capture-pane", "-p", "-t", "t").stdout

        self.keys = lambda *keys: tmux("send-keys", "-t", "t", *keys)
        return screen, mark

    @staticmethod
    def remove_socket(sock, env):
        # Where tmux put it for the CHILD's env (scratch_env drops TMUX_TMPDIR).
        base = env.get("TMUX_TMPDIR") or "/tmp"
        path = os.path.join(base, f"tmux-{os.getuid()}", sock)
        if sock.startswith("sv-test-") and os.path.exists(path):
            os.unlink(path)

    def assert_text_before_list(self, screen, mark, typeahead=None):
        called = wait_for(lambda: os.path.exists(os.path.join(mark, "called")), 10)
        self.assertTrue(called, "ask() never asked the launcher:\n" + screen())
        # The launcher is now blocked: whatever is on screen is all the user
        # has while it works. The headline alone is the SV-96 defect.
        shown = wait_for(lambda: "looking up agents" in screen(), 3)
        early = screen()
        self.assertTrue(shown, "nothing after the headline while the launcher works:\n" + early)
        self.assertIn("sessionview can start an agent", early)
        self.assertNotIn("Which", early)   # still before the list: the stub holds it
        if typeahead:
            typeahead()
        open(os.path.join(mark, "release"), "w").close()

    def test_menu_question_text_before_the_list_arrives(self):
        screen, mark = self.start(["cleo", "pat"])
        self.assert_text_before_list(screen, mark)
        asked = wait_for(lambda: "Which? (number" in screen(), 10)
        late = screen()
        self.assertTrue(asked, "the menu question never came:\n" + late)
        self.assertIn("1) cleo", late)
        self.assertIn("2) pat", late)

    # The launcher prints NAME<TAB>MARK, and a mark can hold a space
    # (`claude<TAB>built in`). Only the name is an agent: the menu once
    # offered "built" and "in". A line with no mark is a name alone.
    def test_menu_offers_only_the_name_field(self):
        screen, mark = self.start([], raw="claude\tbuilt in\nengineer\npat\tsome mark\n")
        self.assert_text_before_list(screen, mark)
        asked = wait_for(lambda: "Which? (number" in screen(), 10)
        late = screen()
        self.assertTrue(asked, "the menu question never came:\n" + late)
        self.assertIn("1) claude", late)
        self.assertIn("2) engineer", late)
        self.assertIn("3) pat", late)
        self.assertNotIn("4)", late)
        for word in ("built", "in", "some", "mark"):
            self.assertNotIn(f") {word}\n", late + "\n")
        got = self.answer(screen, ["3", "Enter"])
        self.assertEqual(got, "pat", "the number picked a mark word:\n" + screen())

    def test_free_text_question_text_before_an_empty_list(self):
        screen, mark = self.start([])
        self.assert_text_before_list(screen, mark)
        asked = wait_for(lambda: "Which agent?" in screen(), 10)
        self.assertTrue(asked, "the free-text question never came:\n" + screen())

    # SV-124. A key pressed during the wait answered the question that came
    # after it, so the typeahead is drained before the question is asked.
    def type_during_wait(self, screen, keys, echoed):
        """Type KEYS while the stub still holds the list, and wait until the
        terminal has echoed them, so they are in the tty's input queue before
        the list is released."""
        def go():
            r = self.keys(*keys)
            self.assertEqual(r.returncode, 0, r.stderr)
            seen = wait_for(lambda: echoed(screen()), 5)
            self.assertTrue(seen, "the typeahead never reached the pane:\n" + screen())
        return go

    def answer(self, screen, keys):
        """Type KEYS after the question is on screen; wait for ask() to say
        what it heard, and return the remembered autostart_agent."""
        r = self.keys(*keys)
        self.assertEqual(r.returncode, 0, r.stderr)
        said = wait_for(lambda: any(w in screen() for w in
                                    ("Set:", "Noted:", "No such choice")), 10)
        self.assertTrue(said, "ask() never answered:\n" + screen())
        cfg = os.path.join(self.home, ".sessionkit", "view", "settings", "view.json")
        with open(cfg) as f:
            return json.load(f).get("autostart_agent")

    def test_menu_a_stray_no_typed_during_the_wait_cannot_answer(self):
        screen, mark = self.start(["cleo", "pat"])
        stray = self.type_during_wait(
            screen, ["no", "Enter"],
            lambda s: any(ln.strip() == "no" for ln in s.splitlines()))
        self.assert_text_before_list(screen, mark, typeahead=stray)
        asked = wait_for(lambda: "Which? (number" in screen(), 10)
        self.assertTrue(asked, "the menu question never came:\n" + screen())
        got = self.answer(screen, ["1", "Enter"])
        self.assertEqual(got, "cleo", "the typeahead answered the question:\n" + screen())
        self.assertIn("Set: cleo.", screen())

    def test_free_text_only_keys_typed_after_the_question_count(self):
        screen, mark = self.start([])
        stray = self.type_during_wait(screen, ["zzz"], lambda s: "zzz" in s)
        self.assert_text_before_list(screen, mark, typeahead=stray)
        asked = wait_for(lambda: "Which agent?" in screen(), 10)
        self.assertTrue(asked, "the free-text question never came:\n" + screen())
        got = self.answer(screen, ["pat", "Enter"])
        self.assertEqual(got, "pat", "the typeahead reached the answer:\n" + screen())
        self.assertIn("Set: pat.", screen())


if __name__ == "__main__":
    unittest.main()
