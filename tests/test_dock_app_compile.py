"""The Dock app compiles on a Mac without iTerm (SV-212).

AppleScript looks an application's dictionary up when a script is COMPILED.
iTerm's words (`create window with default profile command`, `fullscreen`)
are in iTerm's dictionary only, so a plain `tell application "iTerm"` block
made macos/SessionView.applescript fail to compile on any Mac without iTerm:
osacompile exited 1 with `Expected end of line, etc. but found class name.
(-2741)` and `sessionview install --app` built nothing, for every
Terminal-only user. The iTerm block is now a source string run by `run
script ... with parameters {cmd, wantFull}`, compiled only when that branch
runs.

Four layers, so the guard holds on every host:

- osacompile builds the script into a scratch dir under $TMPDIR. On a Mac
  without iTerm this was red before the fix and is green after it. On a Mac
  WITH iTerm it is green either way, so it cannot catch a regression there:
- a host-independent scan: no `application "iTerm"` (tell, using terms from,
  or by bundle id) may appear outside a string literal or a comment;
- where iTerm is absent, the iTerm branch's string fails to compile as a
  CATCHABLE error, the one the applet turns into an alert naming iTerm. This
  probe is OFF by default, on every host: compiling a string that tells iTerm,
  on a Mac without iTerm, can block osascript on a GUI prompt that waits for
  someone to answer it, so an unattended `make test` would hang. Set
  SESSIONVIEW_TEST_ITERM_PROBE=1, at a screen where you can answer that
  prompt, to run it. It still skips where iTerm may be installed, because
  there it would open a window, and it gives up after a short timeout, kills
  osascript and FAILS, never hangs;
- a host-independent read of the iTerm branch: that prompt is real, and the
  shipped app hit it too (the compiler looks iTerm up by name and waits on a
  "Where is iTerm?" chooser), so before the string is compiled the branch
  asks whether iTerm exists, with a check that holds no application
  reference and so cannot prompt, and goes to the alert when it does not.

Nothing is written to ~/Applications: the outputs are temp dirs, removed.
"""
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests import support

SRC = os.path.join(support.REPO, "macos", "SessionView.applescript")

#: the skip reason off a Mac. Loud, so a skip is never read as a pass.
OSACOMPILE_SKIP = "SKIPPED: needs osacompile (macOS only)"

#: the opt-in for the osascript probe of the iTerm string. Only "1" opts in.
PROBE_ENV = "SESSIONVIEW_TEST_ITERM_PROBE"

#: seconds the opted-in probe may take before osascript is killed. A catchable
#: compile error comes back in well under a second; anything near this is a
#: prompt waiting for an answer.
PROBE_TIMEOUT = 20

#: the default skip: why the probe is off, and how to turn it on.
PROBE_SKIP = ("SKIPPED: off by default. Compiling a string that tells iTerm, on a "
              "Mac without iTerm, can block osascript on a GUI prompt, and an "
              "unattended run would hang. To run it, set " + PROBE_ENV + "=1 at a "
              "screen where you can answer that prompt")

#: an application named in code by name or bundle id, the shapes that make
#: the COMPILER fetch that app's dictionary: tell / using terms from /
#: a bare `application "X"` reference, with or without `id`.
APP_REF_TAIL = re.compile(r"\bapplication\s+(?:id\s+)?$", re.I)


def segments(source):
    """Split AppleScript SOURCE into (kind, text) runs, kind one of
    "code", "string", "comment". A string is "..." with backslash escapes;
    a comment is `--` or `#` to the end of the line, or a nested `(* *)`."""
    out, code, i, n = [], [], 0, len(source)

    def flush():
        if code:
            out.append(("code", "".join(code)))
            code.clear()

    while i < n:
        c = source[i]
        if c == '"':
            flush()
            j = i + 1
            while j < n and source[j] != '"':
                j += 2 if source[j] == "\\" else 1
            out.append(("string", source[i + 1:j]))
            i = j + 1
        elif source.startswith("--", i) or c == "#":
            flush()
            j = source.find("\n", i)
            j = n if j < 0 else j
            out.append(("comment", source[i:j]))
            i = j
        elif source.startswith("(*", i):
            flush()
            depth, j = 1, i + 2
            while j < n and depth:
                if source.startswith("(*", j):
                    depth, j = depth + 1, j + 2
                elif source.startswith("*)", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            out.append(("comment", source[i:j]))
            i = j
        else:
            code.append(c)
            i += 1
    flush()
    return out


def iterm_refs_in_code(source):
    """Every iTerm application reference in CODE: an `application "..."` or
    `application id "..."` whose string names iTerm. One inside a string
    literal (the run-script source) or a comment is not code, so not counted."""
    hits, segs = [], segments(source)
    for (kind, text), (nkind, ntext) in zip(segs, segs[1:]):
        if kind == "code" and nkind == "string" and APP_REF_TAIL.search(text) \
                and "iterm" in ntext.lower():
            hits.append(ntext)
    return hits


def iterm_may_be_installed():
    """True unless every probe says iTerm is absent. Spotlight can be off,
    so the plain directory checks back it up; any doubt counts as present."""
    for d in ("/Applications", os.path.expanduser("~/Applications")):
        if os.path.exists(os.path.join(d, "iTerm.app")):
            return True
    if not shutil.which("mdfind"):
        return True
    try:
        r = subprocess.run(["mdfind", "kMDItemCFBundleIdentifier == 'com.googlecode.iterm2'"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return True
    return r.returncode != 0 or bool(r.stdout.strip())


def probe_opted_in(environ=None):
    """True only when PROBE_ENV is exactly "1" in ENVIRON (os.environ)."""
    return (os.environ if environ is None else environ).get(PROBE_ENV) == "1"


class ProbeTimeout(Exception):
    """A bounded child outlived its timeout and was killed. .pid is the child's."""

    def __init__(self, argv, timeout, pid):
        super().__init__(f"{argv[0]} still running after {timeout}s; killed")
        self.pid = pid


def run_bounded(argv, timeout):
    """Run ARGV, capturing text output, and return its CompletedProcess. If it
    outlives TIMEOUT seconds, kill it and its process group, reap it and raise
    ProbeTimeout: never a hang, never a stray child left behind."""
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.kill()
        proc.communicate()
        raise ProbeTimeout(argv, timeout, proc.pid) from None
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


class ScanTest(unittest.TestCase):
    """The host-independent guard, and the scanner it rests on."""

    def test_source_names_iterm_only_inside_a_string(self):
        with open(SRC, encoding="utf-8") as f:
            source = f.read()
        self.assertEqual(iterm_refs_in_code(source), [],
                         "a literal iTerm application reference in code needs iTerm's "
                         "dictionary at COMPILE time; put the iTerm block in the "
                         "run-script string")

    def test_iterm_block_runs_from_a_string_with_parameters(self):
        with open(SRC, encoding="utf-8") as f:
            source = f.read()
        strings = [t for k, t in segments(source) if k == "string"]
        block = [t for t in strings if 'tell application \\"iTerm\\"' in t]
        self.assertEqual(len(block), 1, "one iTerm run-script source string")
        for stmt in ("on run {cmd, wantFull}", "activate",
                     "create window with default profile command cmd",
                     "set fullscreen of current window to true", "end run"):
            with self.subTest(stmt=stmt):
                self.assertIn(stmt, block[0])
        # the values go in as parameters, never spliced into the text
        self.assertIn("run script itermScript with parameters {cmd, wantFull}", source)
        self.assertNotRegex(source, r"itermScript\s*&|&\s*itermScript")

    def test_scanner_flags_code_refs_and_skips_strings_and_comments(self):
        for text in ('tell application "iTerm"\nactivate\nend tell',
                     'tell application "iTerm2" to activate',
                     'using terms from application "iTerm"\nend using terms from',
                     'tell application id "com.googlecode.iterm2"',
                     'set a to application "ITERM"'):
            with self.subTest(text=text):
                self.assertEqual(len(iterm_refs_in_code(text)), 1)
        for text in ('set s to "tell application \\"iTerm\\"\nend tell"',
                     '-- tell application "iTerm"',
                     '# tell application "iTerm"',
                     '(* tell application "iTerm" (* nested *) *)',
                     'tell application "Terminal"\nend tell',
                     'if isRunning("iTerm2") then return "iterm"',
                     'isInstalled("iTerm")'):
            with self.subTest(text=text):
                self.assertEqual(iterm_refs_in_code(text), [])

    def test_segments_keep_escaped_quotes_inside_the_string(self):
        self.assertEqual(segments('x "a \\"b\\" c" y'),
                         [("code", "x "), ("string", 'a \\"b\\" c'), ("code", " y")])


def iterm_branch(source):
    """The text of the main script's `if term is "iterm" then` branch, up to
    the next terminal's branch."""
    m = re.search(r'\nif term is "iterm" then\n(.*?)\nelse if term is ', source, re.S)
    return m.group(1) if m else None


def handler(source, name):
    """The text of handler NAME, `on NAME(...)` through `end NAME`."""
    m = re.search(r"\non " + name + r"\(.*?\nend " + name + r"\n", source, re.S)
    return m.group(0) if m else None


class ItermGuardTest(unittest.TestCase):
    """Without iTerm, compiling the iTerm string does not fail: AppleScript's
    compiler looks iTerm up by name and puts up a "Where is iTerm?" chooser that
    waits with no time limit, so the app hung and its alert was never shown.
    The branch now asks first, with a check that cannot prompt. Host-independent:
    this reads the source, it runs nothing."""

    GUARD = 'if not itermFound() then error'

    def setUp(self):
        with open(SRC, encoding="utf-8") as f:
            self.source = f.read()
        self.branch = iterm_branch(self.source)
        self.assertIsNotNone(self.branch, 'the `if term is "iterm"` branch')

    def test_guard_comes_before_the_run_script_inside_the_alert_try(self):
        run = self.branch.find("run script itermScript")
        guard = self.branch.find(self.GUARD)
        self.assertNotEqual(run, -1, "the run script line, in the iTerm branch")
        self.assertNotEqual(guard, -1, "the itermFound guard, in the iTerm branch")
        self.assertLess(guard, run, "the guard must run BEFORE the string is compiled")
        self.assertEqual(self.branch.count(self.GUARD), 1)
        # inside the same try as the run script, so its error reaches the alert
        try_at = self.branch.rfind("\n\ttry\n", 0, guard)
        on_error = self.branch.find("\ton error errMsg number errNum", run)
        self.assertNotEqual(try_at, -1, "a try before the guard")
        self.assertNotIn("end try", self.branch[try_at:guard])
        self.assertNotEqual(on_error, -1, "the on error after the run script")
        self.assertIn('display alert "SessionView cannot open iTerm"',
                      self.branch[on_error:])

    def test_guard_error_reaches_the_alert_not_the_silent_cancel(self):
        line = next((l for l in self.branch.splitlines() if self.GUARD in l), None)
        self.assertIsNotNone(line, "the itermFound guard, in the iTerm branch")
        m = re.search(r"\bnumber\s+(-?\d+)", line)
        self.assertIsNotNone(m, "the guard raises a numbered error")
        # -128 is re-raised silently by the handler, with no alert
        self.assertNotEqual(int(m.group(1)), -128)
        self.assertIn("if errNum is -128 then error number -128", self.branch)

    def test_check_cannot_prompt(self):
        body = handler(self.source, "itermFound")
        self.assertIsNotNone(body, "the itermFound handler")
        self.assertIn("do shell script", body)
        segs = segments(body)
        code = "".join(t for k, t in segs if k == "code")
        strings = [t for k, t in segs if k == "string"]
        # no application reference of any kind: that is what prompts
        self.assertNotRegex(code, r"(?i)\bapplication\b")
        self.assertNotRegex(code, r"(?i)\btell\b")
        self.assertEqual(iterm_refs_in_code(body), [])
        for text in strings:
            with self.subTest(text=text):
                self.assertNotRegex(text, r"(?i)\btell\s+application\b")
                self.assertNotRegex(text, r'(?i)\bapplication\s*(?:id\s*)?\(?\s*\\?["\']')
        # the probes: running, both Applications folders, LaunchServices by id
        joined = "\n".join(strings)
        for probe in ("pgrep -x iTerm2", "test -d /Applications/iTerm.app",
                      'test -d \\"$HOME/Applications/iTerm.app\\"',
                      "URLForApplicationWithBundleIdentifier('com.googlecode.iterm2')"):
            with self.subTest(probe=probe):
                self.assertIn(probe, joined)

    def test_helpers_find_nothing_in_a_script_without_them(self):
        self.assertIsNone(iterm_branch('if term is "ghostty" then\nend if\n'))
        self.assertIsNone(handler("on isRunning(p)\nend isRunning\n", "itermFound"))


@unittest.skipUnless(shutil.which("osacompile"), OSACOMPILE_SKIP)
class CompileTest(unittest.TestCase):
    """osacompile, into $TMPDIR scratch, never ~/Applications."""

    def test_script_compiles_to_an_app(self):
        with tempfile.TemporaryDirectory(prefix="sessionview-test-") as tmp:
            app = os.path.join(tmp, "SessionView.app")
            r = subprocess.run(["osacompile", "-o", app, SRC],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.isfile(os.path.join(app, "Contents", "Resources",
                                                         "Scripts", "main.scpt")))


OSASCRIPT_SKIP = "SKIPPED: needs osascript (macOS only)"


@unittest.skipUnless(shutil.which("osascript"), OSASCRIPT_SKIP)
class NoItermRunTest(unittest.TestCase):
    """Without iTerm, the iTerm branch fails as an error the applet catches.
    Opt-in only (PROBE_ENV): see the module docstring."""

    def test_iterm_string_fails_catchably_without_iterm(self):
        if not probe_opted_in():
            self.skipTest(PROBE_SKIP)
        if iterm_may_be_installed():
            self.skipTest("SKIPPED: iTerm may be installed here; running its branch "
                          "would open a window")
        with open(SRC, encoding="utf-8") as f:
            source = f.read()
        m = re.search(r'\tset itermScript to (".*?end run")\n', source, re.S)
        self.assertIsNotNone(m, "the iTerm run-script string")
        probe = ("set itermScript to " + m.group(1) + "\n"
                 "try\n"
                 "\trun script itermScript with parameters {\"true\", false}\n"
                 "\treturn \"ran\"\n"
                 "on error errMsg number errNum\n"
                 "\treturn \"caught \" & errNum\n"
                 "end try\n")
        with tempfile.TemporaryDirectory(prefix="sessionview-test-") as tmp:
            path = os.path.join(tmp, "probe.applescript")
            with open(path, "w", encoding="utf-8") as f:
                f.write(probe)
            try:
                r = run_bounded(["osascript", path], PROBE_TIMEOUT)
            except ProbeTimeout:
                self.fail(f"osascript did not return within {PROBE_TIMEOUT}s and was "
                          "killed: compiling the iTerm string without iTerm blocked, "
                          "most likely on a GUI prompt waiting for an answer, instead "
                          "of failing as an error the applet can catch")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout.strip(), r"^caught -\d+$")


class ProbeGuardTest(unittest.TestCase):
    """The probe's gate and bound, proved without running osascript on iTerm."""

    def run_probe_case(self):
        """Run NoItermRunTest into a fresh TestResult and return it."""
        result = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(NoItermRunTest).run(result)
        return result

    def never(self, name):
        return mock.patch.object(sys.modules[__name__], name,
                                 side_effect=AssertionError(name + " must not run"))

    def test_only_exactly_one_opts_in(self):
        for value in (None, "", "0", "true", "yes", " 1"):
            with self.subTest(value=value):
                env = {} if value is None else {PROBE_ENV: value}
                self.assertFalse(probe_opted_in(env))
        self.assertTrue(probe_opted_in({PROBE_ENV: "1"}))

    def test_probe_skips_by_default_and_runs_nothing(self):
        env = {k: v for k, v in os.environ.items() if k != PROBE_ENV}
        with mock.patch.dict(os.environ, env, clear=True), \
                self.never("run_bounded") as ran, \
                self.never("iterm_may_be_installed") as looked:
            result = self.run_probe_case()
        self.assertEqual((result.failures, result.errors), ([], []))
        self.assertEqual(len(result.skipped), 1)
        ran.assert_not_called()
        looked.assert_not_called()
        if shutil.which("osascript"):
            reason = result.skipped[0][1]
            self.assertEqual(reason, PROBE_SKIP)
            self.assertIn(PROBE_ENV + "=1", reason)
            self.assertIn("GUI prompt", reason)

    @unittest.skipUnless(shutil.which("osascript"), OSASCRIPT_SKIP)
    def test_opted_in_where_iterm_may_be_installed_still_skips(self):
        with mock.patch.dict(os.environ, {PROBE_ENV: "1"}), \
                mock.patch.object(sys.modules[__name__], "iterm_may_be_installed",
                                  return_value=True), \
                self.never("run_bounded") as ran:
            result = self.run_probe_case()
        self.assertEqual((result.failures, result.errors), ([], []))
        self.assertEqual(len(result.skipped), 1)
        self.assertIn("iTerm may be installed", result.skipped[0][1])
        ran.assert_not_called()

    @unittest.skipUnless(shutil.which("osascript"), OSASCRIPT_SKIP)
    def test_opted_in_timeout_is_a_failure_naming_the_prompt(self):
        calls = []

        def timed_out(argv, timeout):
            calls.append((argv[0], timeout))
            raise ProbeTimeout(argv, timeout, 0)

        with mock.patch.dict(os.environ, {PROBE_ENV: "1"}), \
                mock.patch.object(sys.modules[__name__], "iterm_may_be_installed",
                                  return_value=False), \
                mock.patch.object(sys.modules[__name__], "run_bounded",
                                  side_effect=timed_out):
            result = self.run_probe_case()
        self.assertEqual(calls, [("osascript", PROBE_TIMEOUT)])
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.failures), 1)
        self.assertIn("GUI prompt", result.failures[0][1])
        self.assertLessEqual(PROBE_TIMEOUT, 20)

    def test_run_bounded_returns_the_result(self):
        r = run_bounded([sys.executable, "-c", "import sys; print('ok'); "
                         "sys.stderr.write('e'); sys.exit(3)"], 30)
        self.assertEqual((r.returncode, r.stdout.strip(), r.stderr), (3, "ok", "e"))

    def test_run_bounded_kills_a_child_that_outlives_its_timeout(self):
        with self.assertRaises(ProbeTimeout) as cm:
            run_bounded([sys.executable, "-c", "import time; time.sleep(60)"], 0.5)
        with self.assertRaises(ProcessLookupError):
            os.kill(cm.exception.pid, 0)


if __name__ == "__main__":
    unittest.main()
