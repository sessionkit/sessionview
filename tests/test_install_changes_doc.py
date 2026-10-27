"""Guard: the README's `## What an install changes` keeps up with the code.

The section is one list for an install and an uninstall: what each step puts
on a Mac and what takes it away. It was measured on a scratch home, and each
check below is a fact in it that a later change to the code could make false
without anyone touching the README:

- the commands the wheel puts on PATH are the pyproject's console scripts;
- the plugin's skills are the folders under skills/, and the plugin has no
  hooks, as the section says;
- each file the sidebar writes in the state folder is named;
- sessionview writes no launchd service, as the section says;
- `## Uninstall` comes right after the section, and its commands name the
  plugin and the package by the names the manifests give them;
- the folders it names, and the ones the uninstall removes, are the state
  and log folders lib/state.sh makes, and the old state folder an upgrade
  leaves behind; no line names ~/Library/Logs, which sessionview never
  writes to.
"""
import glob
import json
import os
import re
import tomllib
import unittest

from tests import _changelog, support

README = os.path.join(support.REPO, "README.md")
SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")
STATE_SH = os.path.join(support.REPO, "lib", "state.sh")
PLUGIN_DIR = os.path.join(support.REPO, ".claude-plugin")

#: state("NAME") or state(f"NAME") in the sidebar. frame.tty is only READ
#: there, as a fallback for a frame's own frame-PID.tty, which the section
#: names.
STATE_FILE = re.compile(r'\bstate\(f?"([^"]+)"\)')
READ_ONLY_STATE = {"frame.tty"}
#: A name built from an f-string, and the form the section writes it in. A new
#: templated name fails the test until it is named here and in the section.
TEMPLATED_STATE = {
    "plugin-{plug['id']}-{a['id']}.txt": "plugin-PLUGIN-ACTION.txt",
    "sidebar-remote-{host}.json": "sidebar-remote-HOST.json",
}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def section(text, heading):
    """The body under `## HEADING`, to the next `## ` heading."""
    lines = text.splitlines()
    start = lines.index("## " + heading) + 1
    out = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        out.append(line)
    return "\n".join(out)


def state_sh_dirs():
    """The new state dir, the log dir and the old state dir, as lib/state.sh
    names them under $HOME (read from it, so these tests hold no copy)."""
    text = read(STATE_SH)
    found = {}
    for var in ("_sv_n", "_sv_ld", "_sv_o"):
        m = re.search(r'^\s*' + var + r'="\$HOME(/[^"$]+)"$', text, re.M)
        if not m:
            raise AssertionError(f"lib/state.sh sets no {var}=\"$HOME/...\"")
        found[var] = m.group(1)
    return found["_sv_n"], found["_sv_ld"], found["_sv_o"]


def bullet(body, label):
    """The top-level bullet that starts `- **LABEL`, with its sub-lines."""
    out, inside = [], False
    for line in body.splitlines():
        if line.startswith("- "):
            inside = line.startswith("- **" + label)
        if inside:
            out.append(line)
    if not out:
        raise AssertionError(f"no bullet '- **{label}' in What an install changes")
    return "\n".join(out)


class WhatAnInstallChanges(unittest.TestCase):
    def setUp(self):
        self.readme = read(README)
        self.body = section(self.readme, "What an install changes")

    def test_uninstall_follows_it(self):
        headings = [l[3:] for l in self.readme.splitlines() if l.startswith("## ")]
        i = headings.index("What an install changes")
        self.assertEqual(headings[i + 1], "Uninstall")

    def test_path_names_every_console_script(self):
        with open(os.path.join(support.REPO, "pyproject.toml"), "rb") as f:
            scripts = tomllib.load(f)["project"]["scripts"]
        path = bullet(self.body, "PATH")
        for name in scripts:
            self.assertIn(f"`{name}`" if name != "sessionview" else "/sessionview`", path, name)

    def test_plugin_names_every_skill(self):
        plugin = bullet(self.body, "Plugin")
        skills = sorted(os.path.basename(os.path.dirname(p))
                        for p in glob.glob(os.path.join(support.REPO, "skills", "*", "SKILL.md")))
        self.assertTrue(skills)
        for name in skills:
            self.assertIn(f"`{name}`", plugin, name)

    def test_no_hooks_is_still_true(self):
        self.assertIn("and no hooks", " ".join(bullet(self.body, "Plugin").split()))
        manifest = json.loads(read(os.path.join(PLUGIN_DIR, "plugin.json")))
        self.assertNotIn("hooks", manifest)
        for p in ("hooks/hooks.json", ".claude-plugin/hooks.json"):
            self.assertFalse(os.path.exists(os.path.join(support.REPO, p)), p)

    def test_every_state_file_is_named(self):
        folders = bullet(self.body, "Folders")
        written = set(STATE_FILE.findall(read(SIDEBAR))) - READ_ONLY_STATE
        self.assertTrue(written)
        for name in sorted(written):
            if "{" in name:
                self.assertIn(name, TEMPLATED_STATE, "a new templated state file: name it")
                name = TEMPLATED_STATE[name]
            self.assertIn(f"`{name}`", folders, name)
        self.assertIn("`frame-PID.tty`", folders)

    def test_no_launchd_service_is_still_true(self):
        self.assertIn("none", bullet(self.body, "Services"))
        tools = glob.glob(os.path.join(support.BIN, "*")) + glob.glob(os.path.join(support.REPO, "lib", "*"))
        for p in tools:
            if os.path.isfile(p):
                text = read(p)
                self.assertNotIn("LaunchAgents", text, p)
                self.assertNotIn("launchctl", text, p)

    def test_uninstall_names_the_plugin_and_the_package(self):
        body = section(self.readme, "Uninstall")
        market = json.loads(read(os.path.join(PLUGIN_DIR, "marketplace.json")))
        plugin = market["plugins"][0]["name"]
        self.assertIn(f"claude plugin uninstall {plugin}@{market['name']}", body)
        self.assertIn(f"claude plugin marketplace remove {market['name']}", body)
        with open(os.path.join(support.REPO, "pyproject.toml"), "rb") as f:
            package = tomllib.load(f)["project"]["name"]
        self.assertIn(f"uv tool uninstall {package}", body)

    def test_folders_name_the_state_and_log_dirs(self):
        folders = bullet(self.body, "Folders")
        for d in state_sh_dirs():
            self.assertIn(f"`~{d}/`", folders, d)

    def test_uninstall_removes_both_new_dirs_and_the_old_one(self):
        body = section(self.readme, "Uninstall")
        for d in state_sh_dirs():
            self.assertIn(f'"${{HOME:?}}{d}"', body, d)

    def test_no_line_names_library_logs(self):
        # An absence guard: CHANGELOG.md and every pending fragment (_changelog.paths).
        docs = [README, os.path.join(support.REPO, "SPEC.md"), *map(str, _changelog.paths())]
        for pattern in ("docs/*.md", "config/*", "skills/*/SKILL.md", "skills/*/references/*.md"):
            docs += glob.glob(os.path.join(support.REPO, pattern))
        self.assertGreater(len(docs), 5)
        for p in docs:
            if os.path.isfile(p):
                self.assertNotIn("Library/Logs", read(p), p)


if __name__ == "__main__":
    unittest.main()
