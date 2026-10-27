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

Three layers, so the guard holds on every host:

- osacompile builds the script into a scratch dir under $TMPDIR. On a Mac
  without iTerm this was red before the fix and is green after it. On a Mac
  WITH iTerm it is green either way, so it cannot catch a regression there:
- a host-independent scan: no `application "iTerm"` (tell, using terms from,
  or by bundle id) may appear outside a string literal or a comment;
- where iTerm is absent, the iTerm branch's string fails to compile as a
  CATCHABLE error, the one the applet turns into an alert naming iTerm. It is
  skipped where iTerm may be installed, because there it would open a window.

Nothing is written to ~/Applications: the outputs are temp dirs, removed.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from tests import support

SRC = os.path.join(support.REPO, "macos", "SessionView.applescript")

#: the skip reason off a Mac. Loud, so a skip is never read as a pass.
OSACOMPILE_SKIP = "SKIPPED: needs osacompile (macOS only)"

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


@unittest.skipUnless(shutil.which("osascript"), "SKIPPED: needs osascript (macOS only)")
class NoItermRunTest(unittest.TestCase):
    """Without iTerm, the iTerm branch fails as an error the applet catches."""

    def test_iterm_string_fails_catchably_without_iterm(self):
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
            r = subprocess.run(["osascript", path], capture_output=True, text=True,
                               timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout.strip(), r"^caught -\d+$")


if __name__ == "__main__":
    unittest.main()
