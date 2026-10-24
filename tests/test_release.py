"""Releases: ONE version source, and scripts/release.py keeps the copies of it.

pyproject.toml holds the version. The plugin manifest, src/sessionview/__init__.py's
__version__ and uv.lock's own package entry are copies (and marketplace.json,
should it ever carry a version field). VersionCopies pins them equal on this
checkout, naming every file and its version when one drifts.

ReleaseScript runs scripts/release.py in a scratch git repo built from a copy of
the files it touches: a real run (mirror, stamp, one commit, an annotated tag,
nothing pushed), the dry run (changes nothing) and every refusal (each leaves the
tree as it found it). It needs uv; without it that class is a loud skip.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from datetime import datetime

from tests import support

REPO = support.REPO
NAME = "sessionview"
UV_SKIP = "SKIPPED: needs uv, which is not on PATH (release.py sets the version with uv version)"

#: What release.py reads or writes, copied into each scratch repo.
FILES = (
    "pyproject.toml", "uv.lock", "README.md", "LICENSE", "CHANGELOG.md",
    ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
    "src/sessionview/__init__.py", "scripts/release.py",
)


def read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return f.read()


def versions(root):
    """Every copy of the version in the tree at root: {where: version}."""
    found = {"pyproject.toml [project].version": tomllib.loads(read(root, "pyproject.toml"))["project"]["version"]}
    found[".claude-plugin/plugin.json version"] = json.loads(read(root, ".claude-plugin/plugin.json"))["version"]
    market = json.loads(read(root, ".claude-plugin/marketplace.json"))
    if "version" in market.get("metadata", {}):
        found[".claude-plugin/marketplace.json metadata.version"] = market["metadata"]["version"]
    for entry in market.get("plugins", []):
        if entry.get("name") == NAME and "version" in entry:
            found[".claude-plugin/marketplace.json plugins[sessionview].version"] = entry["version"]
    m = re.search(r'^__version__ = "([^"]+)"$', read(root, "src/sessionview/__init__.py"), re.M)
    found["src/sessionview/__init__.py __version__"] = m.group(1) if m else "(no __version__ line)"
    own = [p for p in tomllib.loads(read(root, "uv.lock"))["package"] if p["name"] == NAME]
    found["uv.lock [[package]] sessionview version"] = own[0]["version"] if len(own) == 1 else f"({len(own)} entries)"
    return found


def table(found):
    return "\n".join(f"  {where}: {v}" for where, v in found.items())


class VersionCopies(unittest.TestCase):
    def test_every_copy_states_the_pyproject_version(self):
        found = versions(REPO)
        self.assertEqual(len(set(found.values())), 1,
                         f"version drift; scripts/release.py sets them together:\n{table(found)}")

    def test_init_version_is_a_literal(self):
        # The uninstalled checkout (tests, bin/) must know its version without
        # importlib.metadata; release.py rewrites exactly this line.
        self.assertRegex(read(REPO, "src/sessionview/__init__.py"), re.compile(r'^__version__ = "\d+\.\d+\.\d+"$', re.M))


@unittest.skipUnless(shutil.which("uv"), UV_SKIP)
class ReleaseScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sv-release-")
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "repo")
        for rel in FILES:
            dst = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(REPO, rel), dst)
        home = os.path.join(self.tmp.name, "home")
        os.makedirs(home)
        self.env = {k: os.environ[k] for k in support.KEEP if k in os.environ}
        self.env.update({
            "HOME": home, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "UV_OFFLINE": "1", "UV_NO_CONFIG": "1",
        })
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")
        self.version = versions(self.root)["pyproject.toml [project].version"]

    def git(self, *args):
        out = subprocess.run(["git", *args], cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, f"git {' '.join(args)}: {out.stderr}")
        return out.stdout.strip()

    def release(self, *args):
        return subprocess.run([sys.executable, "-B", "scripts/release.py", *args], cwd=self.root,
                              env=self.env, capture_output=True, text=True, timeout=120)

    def write(self, rel, text):
        with open(os.path.join(self.root, rel), "w", encoding="utf-8") as f:
            f.write(text)

    def commit_all(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def snapshot(self):
        return (self.git("rev-parse", "HEAD"), self.git("status", "--porcelain"), self.git("tag", "-l"),
                {rel: read(self.root, rel) for rel in FILES if os.path.exists(os.path.join(self.root, rel))})

    def refused(self, args, message):
        before = self.snapshot()
        out = self.release(*args)
        self.assertNotEqual(out.returncode, 0, out.stdout)
        self.assertIn(message, out.stderr)
        self.assertEqual(self.snapshot(), before, "a refusal must leave the tree, HEAD and tags as found")
        return out

    # -- the real run --------------------------------------------------------

    def test_set_mirrors_stamps_commits_and_tags(self):
        out = self.release("9.9.9")
        self.assertEqual(out.returncode, 0, out.stderr)
        found = versions(self.root)
        self.assertEqual(set(found.values()), {"9.9.9"}, table(found))
        today = datetime.now().astimezone().date().isoformat()
        changelog = read(self.root, "CHANGELOG.md")
        self.assertIn(f"## [Unreleased]\n\n## [9.9.9] - {today}\n", changelog)
        self.assertEqual(changelog.count("## [Unreleased]"), 1)
        # one commit, the files by name, nothing left over
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "2")
        self.assertEqual(self.git("log", "-1", "--format=%s"), "chore: release v9.9.9")
        self.assertEqual(self.git("status", "--porcelain"), "")
        changed = set(self.git("show", "--name-only", "--format=", "HEAD").splitlines())
        self.assertEqual(changed, {"pyproject.toml", "uv.lock", "CHANGELOG.md",
                                   ".claude-plugin/plugin.json", "src/sessionview/__init__.py"})
        # an annotated tag on that commit
        self.assertEqual(self.git("cat-file", "-t", "v9.9.9"), "tag")
        self.assertEqual(self.git("rev-parse", "v9.9.9^{}"), self.git("rev-parse", "HEAD"))
        self.assertEqual(self.git("tag", "-l", "--format=%(contents:subject)", "v9.9.9"), "sessionview v9.9.9")
        # never pushes: it prints the line instead
        self.assertIn("git push && git push --tags", out.stdout)
        self.assertNotIn("$ git push", out.stdout)

    def test_bump_patch(self):
        major, minor, patch = map(int, self.version.split("."))
        want = f"{major}.{minor}.{patch + 1}"
        out = self.release("patch")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(set(versions(self.root).values()), {want})
        self.assertEqual(self.git("cat-file", "-t", f"v{want}"), "tag")

    def test_marketplace_without_a_version_is_skipped(self):
        market = json.loads(read(self.root, ".claude-plugin/marketplace.json"))
        self.assertFalse("version" in market.get("metadata", {}) or any("version" in p for p in market["plugins"]),
                         "marketplace.json gained a version field; this test assumes none")
        out = self.release("9.9.9")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(".claude-plugin/marketplace.json: no version field, skipped", out.stdout)

    def test_marketplace_with_a_version_is_mirrored(self):
        rel = ".claude-plugin/marketplace.json"
        self.write(rel, read(self.root, rel).replace('"metadata": {', f'"metadata": {{\n    "version": "{self.version}",', 1))
        self.commit_all("marketplace carries a version")
        out = self.release("9.9.9")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(read(self.root, rel))["metadata"]["version"], "9.9.9")
        self.assertIn(rel, self.git("show", "--name-only", "--format=", "HEAD").splitlines())

    def test_current_prints_the_version(self):
        out = self.release("--current")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip().splitlines()[-1], self.version)

    # -- the dry run ---------------------------------------------------------

    def test_dry_run_prints_the_plan_and_changes_nothing(self):
        before = self.snapshot()
        out = self.release("9.9.9", "--dry-run")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("would release v9.9.9", out.stdout)
        self.assertIn("$ git tag -a v9.9.9", out.stdout)
        self.assertEqual(self.snapshot(), before)

    # -- the refusals --------------------------------------------------------

    def test_refuses_a_dirty_tree(self):
        self.write("CHANGELOG.md", read(self.root, "CHANGELOG.md") + "\nstray\n")
        self.refused(["9.9.9"], "working tree is not clean")

    def test_refuses_an_untracked_file(self):
        self.write("stray.txt", "x\n")
        self.refused(["9.9.9"], "working tree is not clean")

    def test_refuses_a_missing_changelog(self):
        self.git("rm", "-q", "CHANGELOG.md")
        self.git("commit", "-q", "-m", "no changelog")
        self.refused(["9.9.9"], "CHANGELOG.md not found")

    def test_refuses_a_changelog_without_unreleased(self):
        self.write("CHANGELOG.md", read(self.root, "CHANGELOG.md").replace("## [Unreleased]", "## [Later]"))
        self.commit_all("no unreleased")
        self.refused(["9.9.9"], "no '## [Unreleased]' section")

    def test_refuses_a_missing_version_line(self):
        rel = "src/sessionview/__init__.py"
        self.write(rel, re.sub(r'^__version__ = .*\n', "", read(self.root, rel), flags=re.M))
        self.commit_all("no __version__")
        self.refused(["9.9.9"], "__version__")

    def test_refuses_an_existing_tag(self):
        self.git("tag", "v9.9.9")
        self.refused(["9.9.9"], "tag v9.9.9 already exists")

    def test_refuses_a_bad_spec(self):
        for spec in ("9.9", "v9.9.9", "huge"):
            with self.subTest(spec=spec):
                self.refused([spec], "is not patch|minor|major or X.Y.Z")

    def test_refuses_no_argument(self):
        self.refused([], "Cut a sessionview release")


if __name__ == "__main__":
    unittest.main()
