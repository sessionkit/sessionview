"""Guard: the README's Requirements, docs/dependencies.md and dependabot.yml.

The family's dependency standard asks three things of each repository:

- the README's `## Requirements` is short: the operating systems as
  checkboxes, then one line linking docs/dependencies.md. It is never a
  prerequisites list and names no Required or Optional tool;
- docs/dependencies.md has one entry per dependency, and a dependency whose
  class is not decided says `Status: pending a ruling` and gives no install
  step;
- .github/dependabot.yml looks daily, one entry per ecosystem the repository
  has: uv (uv.lock at the root), and github-actions only once there is a
  .github/workflows.

Also guarded here, since each was once wrong in the README: the commands the
wheel puts on PATH are named on the page, and every command a plugin
`requires` and every tool `sessionview-install --check` checks has an entry.
"""
import os
import re
import tomllib
import unittest

from tests import support

README = os.path.join(support.REPO, "README.md")
PAGE = os.path.join(support.REPO, "docs", "dependencies.md")
DEPENDABOT = os.path.join(support.REPO, ".github", "dependabot.yml")

#: The four whose class is held, and each one's heading on the page.
PENDING = ("Homebrew", "tmux", "notmuch", "ffmpeg")

#: The first screen's one sentence on the lock file, word for word as the
#: family's standard has it.
LOCK_SENTENCE = ("The full resolved set, every package at the version this repo "
                 "is tested with, is in [`uv.lock`][uv-lock].")

#: An install step: a package manager or installer told to install.
INSTALL_STEP = re.compile(r"\b(brew|uv tool|uv python|pip|port|apt(-get)?|dnf) install\b"
                          r"|xcode-select --install")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def section(text, heading, level="## "):
    """The body under HEADING (a line `<level>HEADING`), to the next heading of
    the same or a higher level. Raises ValueError when there is no such heading."""
    lines = text.splitlines()
    start = lines.index(level + heading) + 1
    depth = len(level.strip())
    out = []
    for line in lines[start:]:
        m = re.match(r"(#+) ", line)
        if m and len(m.group(1)) <= depth:
            break
        out.append(line)
    return "\n".join(out)


def pending_entry(page, name):
    """The `### [name][..]` (or `### name`) entry under Pending a ruling."""
    body = section(page, "Pending a ruling")
    m = re.search(r"(?m)^### \[?%s\]?(\[[^\]]*\])?\s*$" % re.escape(name), body)
    if not m:
        raise AssertionError(f"no ### {name} entry under Pending a ruling")
    rest = body[m.end():]
    nxt = re.search(r"(?m)^### ", rest)
    return rest[:nxt.start()] if nxt else rest


class Requirements(unittest.TestCase):
    def setUp(self):
        self.body = section(read(README), "Requirements")

    def test_operating_systems_as_checkboxes(self):
        boxes = re.findall(r"(?m)^- \[[ x]\] (\S+)", self.body)
        self.assertEqual(boxes, ["macOS", "Linux", "WSL", "Windows"])
        self.assertRegex(self.body, r"(?m)^- \[x\] macOS \(tested")

    def test_one_link_to_the_page(self):
        links = re.findall(r"\]\(([^)]+)\)", self.body)
        self.assertEqual(links, ["docs/dependencies.md"])

    def test_no_prerequisites_list(self):
        self.assertNotRegex(self.body, r"\*\*(Required|Optional):?\*\*")
        # Every list item is an operating-system checkbox: no tool is listed.
        items = [l for l in self.body.splitlines() if re.match(r"\s*[-*] ", l)]
        self.assertTrue(all(re.match(r"- \[[ x]\] ", l) for l in items), items)

    def test_the_readme_says_nothing_stale(self):
        text = read(README)
        self.assertNotIn("empty package", text)
        self.assertNotIn("Requirements are listed above", text)
        self.assertNotIn("no MTA", text)


class Page(unittest.TestCase):
    def setUp(self):
        self.page = read(PAGE)

    def test_first_screen(self):
        # The point of the page, before any table: required, optional,
        # pending a ruling, and the upgrade lines.
        head = self.page[:self.page.index("\n|")]
        for label in ("**Required:**", "**Optional:**", "**Pending a ruling:**", "**Upgrade:**"):
            with self.subTest(label=label):
                self.assertIn(label, head)
        for name in PENDING:
            with self.subTest(pending=name):
                self.assertIn(name, head[head.index("**Pending a ruling:**"):])

    def test_first_screen_points_at_the_lock_file(self):
        # The page lists the direct dependencies; uv.lock holds the rest.
        head = self.page[:self.page.index("\n|")]
        self.assertIn(LOCK_SENTENCE, head)
        self.assertIn("direct dependencies", head)

    def test_lock_link_resolves(self):
        m = re.search(r"(?m)^\[uv-lock\]: (\.\./uv\.lock)$", self.page)
        self.assertIsNotNone(m, "no [uv-lock]: ../uv.lock link line")
        self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(PAGE), m.group(1))))
        # The standard's own check, as its grep reads it.
        self.assertRegex(self.page, r"(?m)^\[[^]]+\]: \.\./uv\.lock$")

    def test_nothing_calls_the_page_the_full_list(self):
        for path in (PAGE, README):
            with self.subTest(path=os.path.basename(path)):
                text = read(path)
                self.assertNotIn("Everything sessionview depends on", text)
                self.assertNotIn("What sessionview depends on", text)
                self.assertNotRegex(text, r"(?i)\bfull list\b")

    def test_pending_entries_have_status_and_no_install_step(self):
        for name in PENDING:
            with self.subTest(name=name):
                entry = pending_entry(self.page, name)
                self.assertRegex(entry, r"(?m)^Status: pending a ruling\.")
                self.assertIsNone(INSTALL_STEP.search(entry), entry)
                for word in ("**What uses it:**", "**Without it:**", "**Where it comes from today:**"):
                    self.assertIn(word, entry)

    def test_held_tools_have_no_class(self):
        # A held tool is not a row of the Required or Optional table.
        for heading in ("Required", "Optional"):
            body = section(self.page, heading)
            rows = [l for l in body.splitlines() if l.startswith("| ")]
            for name in PENDING:
                with self.subTest(table=heading, name=name):
                    self.assertFalse(any(re.match(r"\| \[?%s\b" % re.escape(name), r) for r in rows))

    def test_neomutt_is_optional_as_the_check_says(self):
        # `--check` says WARN, not MISSING, for a missing neomutt: the messages
        # tab is made only when sessionmail (optional) is installed. The page's
        # class follows the check: an Optional row, nowhere under Required.
        installer = read(os.path.join(support.BIN, "sessionview-install"))
        self.assertIn('say WARN "neomutt not on PATH', installer)
        self.assertNotRegex(installer, r'fail "neomutt')
        head = self.page[:self.page.index("\n|")]
        required = re.search(r"(?s)\*\*Required:\*\*(.*?)\n- \*\*", head).group(1)
        self.assertNotIn("neomutt", required)
        optional = re.search(r"(?s)\*\*Optional:\*\*(.*?)\n- \*\*", head).group(1)
        self.assertIn("neomutt", optional)
        rows = {h: [l for l in section(self.page, h).splitlines() if l.startswith("| [neomutt]")]
                for h in ("Required", "Optional")}
        self.assertEqual(len(rows["Optional"]), 1, rows)
        self.assertEqual(rows["Required"], [])
        self.assertIn("WARN", rows["Optional"][0])
        self.assertNotIn("MISSING", rows["Optional"][0])

    def test_wheel_commands_are_named(self):
        with open(os.path.join(support.REPO, "pyproject.toml"), "rb") as f:
            scripts = tomllib.load(f)["project"]["scripts"]
        self.assertEqual(len(scripts), 4)
        body = section(self.page, "sessionview itself")
        for name in scripts:
            with self.subTest(script=name):
                self.assertIn(f"`{name}`", body)

    def test_no_python_dependencies_claimed_correctly(self):
        with open(os.path.join(support.REPO, "pyproject.toml"), "rb") as f:
            self.assertEqual(tomllib.load(f)["project"]["dependencies"], [])
        self.assertIn("no Python package dependencies", self.page)

    def test_every_plugin_requirement_has_an_entry(self):
        for path in sorted(os.listdir(os.path.join(support.REPO, "plugins"))):
            toml = os.path.join(support.REPO, "plugins", path, "plugin.toml")
            if not os.path.isfile(toml):
                continue
            with open(toml, "rb") as f:
                requires = tomllib.load(f).get("requires", [])
            for cmd in requires:
                if "/" in cmd:      # a path: another plugin installed, not a command
                    continue
                with self.subTest(plugin=path, requires=cmd):
                    self.assertIn(f"(`{cmd}`)", self.page)

    def test_every_checked_tool_has_an_entry(self):
        installer = read(os.path.join(support.BIN, "sessionview-install"))
        checked = set(re.findall(r"command -v (\w+)", installer))
        self.assertTrue({"tmux", "neomutt", "notmuch", "session", "tm"} <= checked, checked)
        for cmd in sorted(checked):
            with self.subTest(tool=cmd):
                self.assertRegex(self.page, r"\b%s\b" % re.escape(cmd))
        self.assertIn("sessionview install --check", self.page)


class Dependabot(unittest.TestCase):
    def test_the_standard_file(self):
        # Read as text: the suite is stdlib only, and the file is four keys.
        lines = [l for l in read(DEPENDABOT).splitlines() if l.strip() and not l.lstrip().startswith("#")]
        self.assertEqual(lines, [
            "version: 2",
            "updates:",
            '  - package-ecosystem: "uv"',
            '    directory: "/"',
            "    schedule:",
            '      interval: "daily"',
        ])

    def test_ecosystems_match_the_repo(self):
        self.assertTrue(os.path.isfile(os.path.join(support.REPO, "uv.lock")))
        workflows = os.path.isdir(os.path.join(support.REPO, ".github", "workflows"))
        entries = [l for l in read(DEPENDABOT).splitlines() if not l.lstrip().startswith("#")]
        self.assertEqual(any("github-actions" in l for l in entries), workflows)


if __name__ == "__main__":
    unittest.main()
