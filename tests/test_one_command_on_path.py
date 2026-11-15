"""`sessionview` is the one command on PATH.

The config, session and messages tools are verbs of it (`sessionview config`,
`sessionview session`, `sessionview messages`), never commands of their own:
"we wouldn't call them on their own". Three things keep it so:

- the wheel declares one console script, and its entry point runs
  bin/sessionview whatever name it was started by;
- no shipped file calls one of the three by its bare name, which would find
  nothing on PATH. A caller reaches the tool by path
  (`$SESSIONVIEW_ROOT/bin/sessionview-config`) or through the front door
  (`sessionview messages ...`, as the messages tabs type it);
- the checkout install links none of them (tests/test_install_guard.py).

The scan below reads code, not prose: a comment, a docstring or an error
prefix (`sessionview-config: ...`) may name the tool; only a command
position calls it.
"""
import ast
import importlib.util
import json
import os
import re
import tomllib
import unittest
from unittest import mock

from tests import support

OFF_PATH = ("sessionview-config", "sessionview-session", "sessionview-messages")
NAME = r"sessionview-(?:config|session|messages)(?![\w-])"
# A command position: the start of a line or a string, or after a shell
# separator, a substitution or a word that runs its argument. The name must
# end there as a word (a space, a quote or the end follows it), so an error
# prefix such as "sessionview-config: warning" is not a call.
CALL = re.compile(
    r"(?:^|[;&|(`{\"']|\$\(|\b(?:then|do|else|exec|command\s+-v|which|type|env|nohup|xargs)\b)"
    r"\s*" + NAME + r"(?=\s|$|[\"'`;)|&])", re.M)
# The trees a package or a checkout install ships; docs are prose.
SHIPPED = ("bin", "lib", "config", "tmux", "plugins", "macos", "skills")
TEXT_SUFFIXES = ("", ".sh", ".conf", ".applescript", ".json", ".py", ".toml")


def is_python(path, text):
    first = text.split("\n", 1)[0]
    return path.endswith(".py") or "python" in first or "\n'''exec'" in text[:200] \
        or text.startswith("#!/bin/sh\n'''")


def docstring_nodes(tree):
    """The Constant nodes that are docstrings: the first statement of a
    module, class or function, when it is a string."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                out.add(id(body[0].value))
        # `__doc__ = """..."""`, the polyglot tools' usage
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__doc__"
                                                for t in node.targets):
            out.add(id(node.value))
    return out


# In Python a string that only names the tool is common (a path part for
# os.path.join, a message's prefix), so a string calls it only as an argv's
# first word, after a shell separator inside it, or as a shell line: the name
# at its start, then an argument (a placeholder, a flag, a variable, a quote,
# an UPPER-case word or one of the tools' verbs).
IN_LINE = re.compile(
    r"(?:[;&|(`]|\$\(|\b(?:then|do|else|exec|command\s+-v|which|type|env|nohup|xargs)\b)"
    r"\s*" + NAME + r"(?=\s|$|[\"'`;)|&])")
LINE_START = re.compile(
    r"^\s*" + NAME + r"\s+(?:[{$\"'-]|[A-Z][A-Z_]*\b|"
    r"(?:get|set|unset|dump|list|windows|path|init|edit)(?=\s|$))")


def python_calls(text):
    """Each string a Python file holds (docstrings aside) that calls a bare
    name."""
    tree = ast.parse(text)
    docs = docstring_nodes(tree)
    argv0 = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
            argv0.add(id(node.elts[0]))
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)) or id(node) in docs:
            continue
        v = node.value
        if (id(node) in argv0 and v.strip() in OFF_PATH) or IN_LINE.search(v) or LINE_START.search(v):
            hits.append((node.lineno, v[:80]))
    return hits


def json_calls(text):
    """Each JSON string value that calls a bare name; `_key` notes are prose."""
    hits = []

    def walk(v, key=""):
        if isinstance(v, dict):
            for k, x in v.items():
                if not str(k).startswith("_"):
                    walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, str) and CALL.search(v):
            hits.append((key, v[:80]))
    walk(json.loads(text))
    return hits


def shell_calls(text):
    """Each non-comment line that calls a bare name (sh, tmux conf,
    AppleScript, neomuttrc)."""
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        s = line.lstrip()
        if s.startswith(("#", "--")):
            continue
        if CALL.search(line):
            hits.append((n, line.strip()[:80]))
    return hits


# The one place a bare name may stand as a command: the config tool's table
# of the old shipped tab commands, which it reads as `sessionview messages`
# (an older home file holds them). Data, matched exactly, never run.
ALLOWED = {
    os.path.join("bin", "sessionview-config"): {
        "sessionview-messages {project} --store {store}",
        "sessionview-messages {project}",
        "sessionview-messages {store}",
    },
}


def calls(path, text):
    if path.endswith(".json"):
        return json_calls(text)
    if is_python(path, text):
        allowed = ALLOWED.get(os.path.relpath(path, support.REPO), set())
        return [h for h in python_calls(text) if h[1] not in allowed]
    return shell_calls(text)


def shipped_files():
    for top in SHIPPED:
        for root, dirs, files in os.walk(os.path.join(support.REPO, top)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                path = os.path.join(root, name)
                if os.path.splitext(name)[1] in TEXT_SUFFIXES or name == "neomuttrc":
                    yield path


class TheWheel(unittest.TestCase):
    def test_one_console_script(self):
        with open(os.path.join(support.REPO, "pyproject.toml"), "rb") as f:
            scripts = tomllib.load(f)["project"]["scripts"]
        self.assertEqual(scripts, {"sessionview": "sessionview:main"})

    def load(self):
        spec = importlib.util.spec_from_file_location(
            "sessionview_entry", os.path.join(support.REPO, "src", "sessionview", "__init__.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_the_entry_point_routes_only_sessionview(self):
        mod = self.load()
        self.assertEqual(mod.PUBLIC, ("sessionview",))
        # Started by any name (an old console script left behind by an
        # upgrade, a renamed link), it runs the front door, never a helper.
        for argv0 in ("sessionview", *OFF_PATH, "anything"):
            with self.subTest(argv0=argv0), \
                    mock.patch.object(mod.sys, "argv", [f"/x/bin/{argv0}", "path"]), \
                    mock.patch.dict(mod.os.environ, {}, clear=False), \
                    mock.patch.object(mod.os, "execv") as execv:
                mod.main()
                tool, argv = execv.call_args.args
                self.assertEqual(tool, str(mod.DATA / "bin" / "sessionview"))
                self.assertEqual(argv, [tool, "path"])


class NoBareCaller(unittest.TestCase):
    def test_the_scan_sees_a_call(self):
        # The probe: each shape a bare call has taken, and the shapes that
        # only name the tool.
        self.assertTrue(json_calls('{"windows": [{"command": "sessionview-messages {project}"}]}'))
        self.assertTrue(shell_calls('x="$(command -v sessionview-config >/dev/null && sessionview-config get a)"'))
        self.assertTrue(shell_calls("  sessionview-session NAME --print"))
        self.assertTrue(shell_calls('bind x run-shell "sessionview-config set width 3"'))
        self.assertTrue(python_calls('import subprocess\nsubprocess.run(["sessionview-config", "path"])\n'))
        self.assertTrue(python_calls('cmd = "cd x; sessionview-session demo"\n'))
        self.assertFalse(shell_calls('"$SESSIONVIEW_ROOT/bin/sessionview-config" get width'))
        self.assertFalse(shell_calls('echo "sessionview-session: NAME required" >&2'))
        self.assertFalse(shell_calls("# sessionview-config set pane_menu true"))
        self.assertFalse(python_calls('"""sessionview-session builds it."""\n'))
        self.assertFalse(python_calls('x = f"sessionview-config: {e}"\n'))
        self.assertTrue(python_calls('w = "sessionview-messages {project} --store {store}"\n'))
        self.assertFalse(python_calls('import os\nos.path.join(ROOT, "bin", "sessionview-config")\n'))
        self.assertFalse(python_calls('note("sessionview-config path: no home file")\n'))
        self.assertFalse(json_calls('{"_windows": "via sessionview-messages, open by default"}'))

    def test_no_shipped_file_calls_a_bare_helper(self):
        found = {}
        for path in shipped_files():
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            if not re.search(NAME, text):
                continue
            hits = calls(path, text)
            if hits:
                found[os.path.relpath(path, support.REPO)] = hits
        self.assertEqual(found, {}, "a shipped caller runs a tool that is not on PATH; "
                                    "call it by path or as `sessionview VERB`")

    def test_the_messages_tabs_go_through_the_front_door(self):
        with open(os.path.join(support.REPO, "config", "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        for key in ("windows", "store_windows"):
            with self.subTest(key=key):
                cmd = [w["command"] for w in cfg[key] if w.get("name") == "messages"]
                self.assertEqual(len(cmd), 1, cmd)
                self.assertTrue(cmd[0].startswith("sessionview messages "), cmd[0])

    def test_the_app_installer_asks_its_own_config_tool(self):
        with open(os.path.join(support.BIN, "sessionview-app-install"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn('"$ROOT/bin/sessionview-config" get fullscreen', text)
        self.assertNotIn("command -v sessionview-config", text)
        # SESSIONVIEW_ROOT is unset there under `set -u`.
        self.assertNotIn("$SESSIONVIEW_ROOT/bin/sessionview-config", text)


if __name__ == "__main__":
    unittest.main()
