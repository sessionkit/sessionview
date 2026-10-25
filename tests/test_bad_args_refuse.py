"""Input a verb cannot use refuses BEFORE it touches anything (SV-201): a
flag with no value, a missing ADDRESS, a word config does not know, a
surplus positional. The same refusal as an unknown flag (SV-200): exit 2,
nothing on stdout, ONE reason line on stderr naming what was wrong, then the
tool's COMPLETE usage, byte for byte what its --help prints.

"Before it touches anything" is measured the way tests/test_verb_help.py
measures it: each call runs in a fresh Sandbox (scratch HOME, PREFIX and
TMUX_TMPDIR, every path listed before and after, directories too) with a
RECORDER first on PATH for tmux, every python3.x, message, session and the
rest. Nothing may be made and no recorder may run. Only config, a Python
tool, may run the interpreter, and only on itself.

What each case did before (measured at 034ec3d):
- `usermail --socket` / `--session`: a reason and usage, but exit 1.
- `sidebar-toggle --frame` / `--tty`: `$2: unbound variable` under set -u,
  exit 1, no usage.
- `send` with no ADDRESS: one line of its own, exit 1.
- `config bogus`: made ~/.sessionkit/view/settings/view.json, THEN printed
  the usage and exited 1.
- autostart's decide form `SOCK SESSION "" foo`: ignored `foo`, exit 0,
  asked tmux and config, and config made view.json.
- `messages demo --store`: `$2: unbound variable`, exit 1, no usage.
  `messages demo --store --print`: --print became the store slug, and
  `message path --print/demo` ran.
- config with a known verb and a word missing or one too many (`get`,
  `set width`, `unset`, `dump x`): made view.json, then refused, exit 1
  (or exit 0 with the surplus word ignored).
- config `--project` / `--store` / `--key` with no value: the flag was
  dropped, exit 0, and view.json was made.

Only a MISSING value refuses. An EMPTY value is live input that callers
pass on purpose (EmptyValueStaysLive pins two of them).

The last class turns SV-200's reviewer probe 2 (a valid form of each tool
plus a trailing --bogus) into a suite test, so a refusal in a later slot
never regresses.
"""
import os
import shlex
import unittest

from tests import support
from tests import test_verb_help as vh

DISPATCHER = vh.DISPATCHER
CONFIG = "sessionview-config"


def tool(name):
    return os.path.join(support.BIN, name)


class BadArgsRefuse(unittest.TestCase):

    def assert_refuses(self, argv, names, help=None, python_ok=None):
        """ARGV refuses: exit 2, empty stdout, a first stderr line holding
        NAMES (what was wrong), then exactly the --help text of HELP
        (default: ARGV's tool with --help). Nothing made, nothing run."""
        what = vh.shown(argv)
        help = help or [argv[0], "--help"]
        hrc, usage, herr, _, _ = vh.fresh_run(help)
        self.assertEqual(hrc, 0, f"{vh.shown(help)}: exit {hrc}; stderr {herr[-300:]!r}")
        self.assertGreaterEqual(len(usage.strip().splitlines()), 3,
                                f"{what}: usage too short: {usage!r}")
        rc, out, err, changed, calls = vh.fresh_run(argv)
        self.assertIsNotNone(rc, f"{what}: did not exit in {vh.TIMEOUT}s")
        if python_ok:
            calls = [c for c in calls if not (c.startswith("python ") and python_ok in c)]
        self.assertEqual(changed, [], f"{what}: touched {changed}")
        self.assertEqual(calls, [], f"{what}: ran {calls}")
        self.assertEqual(rc, 2, f"{what}: exit {rc}; stderr {err[-300:]!r}")
        self.assertEqual(out, "", f"{what}: printed on stdout: {out[:300]!r}")
        first, _, rest = err.partition("\n")
        for name in names:
            self.assertIn(name, first, f"{what}: the reason line does not name {name!r}: {first!r}")
        self.assertEqual(rest, usage, f"{what}: stderr after the reason is not the whole --help text; "
                                      f"stderr {err[:300]!r}")

    # -- a flag missing its value -----------------------------------------

    def test_usermail_flag_without_its_value(self):
        for argv in (["--socket"], ["--session"], ["--print", "--socket"],
                     ["--socket", "s", "--session"]):
            with self.subTest(argv=argv):
                self.assert_refuses([tool("sessionview-usermail"), *argv], [argv[-1]])

    def test_sidebar_toggle_flag_without_its_value(self):
        for argv in (["--frame"], ["--tty"], ["--hide", "--frame"], ["--show", "--tty"]):
            with self.subTest(argv=argv):
                self.assert_refuses([tool("sessionview-sidebar-toggle"), *argv], [argv[-1]])

    def test_messages_store_without_its_value(self):
        self.assert_refuses([tool("sessionview-messages"), "demo", "--store"], ["--store"])

    def test_messages_store_does_not_swallow_the_next_flag(self):
        # `--store --print` made SLUG=--print and ran `message path --print/demo`.
        for argv in (["demo", "--store", "--print"], ["--store", "--print", "demo"],
                     ["demo", "--store", "--bogus"]):
            with self.subTest(argv=argv):
                self.assert_refuses([tool("sessionview-messages"), *argv], ["--store"])

    # -- a missing or surplus positional ----------------------------------

    def test_send_without_an_address(self):
        self.assert_refuses([tool("sessionview-send")], ["ADDRESS"])

    def test_autostart_decide_form_refuses_a_surplus_word(self):
        # SOCK SESSION "" foo: the empty third slot is legal (no
        # --fresh-window), and `foo` after it is a word the grammar does not name.
        self.assert_refuses([tool("sessionview-autostart"), "nosock", "nosess", "", "foo"], ["foo"])

    # -- a word config does not know --------------------------------------

    def test_config_unknown_word_makes_no_view_json(self):
        for word in ("bogus", "lsit", "-"):
            with self.subTest(word=word):
                self.assert_refuses([tool(CONFIG), word], [word], python_ok=CONFIG)

    def test_config_wrong_arity_makes_no_view_json(self):
        # A known verb with a word missing or one too many fell past the
        # point where merged() seeds view.json, and only then refused.
        for words, names in ((["get"], ["get"]), (["get", "width", "x"], ["get", "x"]),
                             (["set"], ["set"]), (["set", "width"], ["set"]),
                             (["set", "width", "30", "x"], ["set", "x"]),
                             (["unset"], ["unset"]), (["unset", "width", "x"], ["unset", "x"]),
                             (["dump", "x"], ["dump", "x"]), (["windows", "x"], ["windows", "x"]),
                             (["path", "x"], ["path", "x"]), (["init", "x"], ["init", "x"])):
            with self.subTest(words=words):
                self.assert_refuses([tool(CONFIG), *words], names, python_ok=CONFIG)

    def test_config_flag_without_its_value(self):
        # A trailing --project / --store / --key read as None: the flag was
        # dropped and the answer came from the home layer, exit 0.
        for argv in (["get", "width", "--project"], ["dump", "--store"], ["windows", "--key"]):
            with self.subTest(argv=argv):
                self.assert_refuses([tool(CONFIG), *argv], [argv[-1]], python_ok=CONFIG)

    # -- the same, through the dispatcher ---------------------------------

    def test_through_the_dispatcher(self):
        cases = (
            (["usermail", "--socket"], ["--socket"], None),
            (["sidebar-toggle", "--frame"], ["--frame"], None),
            (["messages", "demo", "--store"], ["--store"], None),
            (["autostart", "nosock", "nosess", "", "foo"], ["foo"], None),
            (["config", "bogus"], ["bogus"], CONFIG),
        )
        for argv, names, ok in cases:
            with self.subTest(argv=argv):
                self.assert_refuses([DISPATCHER, *argv], names,
                                    help=[DISPATCHER, argv[0], "--help"], python_ok=ok)


class EmptyValueStaysLive(unittest.TestCase):
    """Only a MISSING value refuses. An EMPTY one is what live callers pass:
    the shipped messages tab types `--store ''` when there is no store
    registry, and sessionview-session calls config with `--store "$STORE"`."""

    def test_messages_store_empty_is_no_store(self):
        box = vh.Sandbox()
        self.addCleanup(box.cleanup)
        box._shim("message", f"printf '%s\\n' \"message $*\" >> {shlex.quote(box.log)}\n"
                             'mkdir -p "$HOME/box" && echo "$HOME/box"\n')
        box._shim("neomutt", "exit 0\n")          # only looked for: --print never starts it
        rc, out, err, _, calls = box.run([tool("sessionview-messages"), "demo", "--store", "", "--print"])
        self.assertEqual(rc, 0, err[-300:])
        self.assertIn("box=demo ", out)
        self.assertIn("message path demo", calls)

    def test_config_windows_store_empty_is_no_store(self):
        with support.scratch_env() as (env, root):
            r = support.run(CONFIG, "windows", "--store", "", "--project", root, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.strip(), "no windows rows")


class TrailingSlotRefuses(unittest.TestCase):
    """SV-200's reviewer probe 2, kept: a VALID form of each tool, then a
    trailing --bogus. Each refuses with exit 2, makes nothing and runs no
    recorder (config may run the interpreter on itself)."""

    CASES = (
        ["sessionview-session", "demo", "--print", "--bogus"],
        ["sessionview-messages", "demo", "--print", "--bogus"],
        ["sessionview-usermail", "--print", "--bogus"],
        ["sessionview-sidebar-toggle", "--hide", "--bogus"],
        ["sessionview-frame", "S", "--bogus"],
        ["sessionview-frame", "S", "--sock", "x", "--bogus"],
        ["sessionview-terminal", "--why", "--bogus"],
        ["sessionview-app-install", "--check", "--bogus"],
        ["sessionview-install", "--check", "--bogus"],
        ["sessionview-install", "--relink", "--bogus"],
        ["sessionview-from", "--bogus"],
        ["sessionview-config", "path", "--bogus"],
        ["sessionview-config", "get", "width", "--bogus"],
        ["tmux-sidebar", "--once", "--bogus"],
        ["tmux-sidebar", "--popup", "--bogus"],
        ["sessionview", "sidebar", "--bogus"],
        ["sessionview", "S", "--bogus"],
        ["tmux-send-agent", "--bogus"],
        ["sessionview-send", "--bogus"],
        ["sessionview-autostart", "nosock", "nosess", "--fresh-window", "--bogus"],
        ["sessionview-newtab", "foo", "/tmp", "--bogus"],
    )

    def test_a_trailing_unknown_flag_refuses_in_every_tool(self):
        config = tool(CONFIG)
        for case in self.CASES:
            with self.subTest(argv=case):
                rc, out, err, changed, calls = vh.fresh_run([tool(case[0]), *case[1:]])
                calls = [c for c in calls if not c.startswith("python " + config)]
                what = " ".join(case)
                self.assertEqual(changed, [], f"{what}: touched {changed}")
                self.assertEqual(calls, [], f"{what}: ran {calls}")
                self.assertEqual(rc, 2, f"{what}: exit {rc}; stderr {err[-300:]!r}")
                self.assertIn("--bogus", (err.splitlines() or [""])[0],
                              f"{what}: the reason line does not name --bogus: {err[:200]!r}")

    def test_every_tool_is_swept(self):
        # A tool added to bin/ later must join the sweep, not slip past it.
        self.assertEqual(sorted({c[0] for c in self.CASES}), vh.tools())


if __name__ == "__main__":
    unittest.main()
