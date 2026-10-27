"""Releases: ONE version source, and scripts/release.py keeps the copies of it.

pyproject.toml holds the version. The plugin manifest, src/sessionview/__init__.py's
__version__ and uv.lock's own package entry are copies (and marketplace.json,
should it ever carry a version field). VersionCopies pins them equal on this
checkout, naming every file and its version when one drifts.

ReleaseScript runs scripts/release.py in a scratch git repo built from a copy of
the files it touches: a real run (mirror, stamp, one commit, an annotated tag,
nothing pushed), the dry run (changes nothing) and every refusal (each leaves the
tree as it found it). It needs uv; without it that class is a loud skip.

A release never re-locks. A plain `uv version X` (or --bump) re-resolves uv.lock
against the index, and the release commits uv.lock: cut before a dependency is
on PyPI it fails, and with UV_FIND_LINKS set it commits a lock of local paths.
FrozenVersion pins `--frozen` on every uv version call, dry and real; the
ReleaseScript lock tests run a REAL release (a dry run never locks, so it cannot
catch this) offline, against an empty uv cache of their own, so any resolve
fails, and check that uv.lock differs only in the root version line and that
`uv lock --check` passes after it. One floors a dependency at a version PyPI
does not have. The lock is checked before uv writes anything: a bad one is
refused with the tree as found.

The push is narrow: release.py prints, and `make push` runs, the branch by name
and then the ONE release tag by its full refname, never `--tags` (which sends
every local tag: fallback/*, export/*, ready/*). PushAdvice and MakeTargets pin
that, and `make release` and `make changelog` running python3, not a
re-locking `uv run`. The make recipes are read as text, never run.
"""
import contextlib
import importlib.util
import io
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
from unittest import mock

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
class ReleaseRepo(unittest.TestCase):
    """The scratch repo and its helpers, with no tests of its own: ReleaseScript
    here and test_release_fragments.FragmentRelease each run their cases in it."""

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
            # Offline, against an EMPTY cache of its own: any resolve fails, so a
            # re-lock cannot pass unseen by writing the same bytes from a warm cache.
            "UV_OFFLINE": "1", "UV_NO_CONFIG": "1", "UV_PYTHON_DOWNLOADS": "never",
            "UV_CACHE_DIR": os.path.join(self.tmp.name, "uv-cache"),
        })
        self.git("init", "-q", "-b", "master")
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


@unittest.skipUnless(shutil.which("uv"), UV_SKIP)
class ReleaseScript(ReleaseRepo):
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
        # never pushes: it prints the line instead, the branch and this one tag by name
        self.assertIn("  git push origin master && git push origin refs/tags/v9.9.9\n", out.stdout)
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

    def test_refuses_a_detached_head(self):
        # The push line names the branch; a release on no branch has none to name.
        self.git("checkout", "-q", "--detach")
        self.refused(["9.9.9"], "HEAD is detached")

    # -- a release never re-locks ----------------------------------------------

    def lock(self):
        return read(self.root, "uv.lock")

    def assert_only_the_root_line_moved(self, before, old, new):
        after = self.lock()
        a, b = before.splitlines(keepends=True), after.splitlines(keepends=True)
        self.assertEqual(len(a), len(b), "uv.lock gained or lost lines: something re-locked")
        self.assertEqual([(x, y) for x, y in zip(a, b) if x != y],
                         [(f'version = "{old}"\n', f'version = "{new}"\n')])
        self.assertEqual(root_line(after), f'version = "{new}"')  # the changed line IS the root line
        self.assertEqual(after, with_root(before, old, new))

    def test_a_bump_changes_only_the_root_lock_line(self):
        before, new = self.lock(), next_patch(self.version)
        out = self.release("patch")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assert_only_the_root_line_moved(before, self.version, new)
        self.assertEqual(root_line(self.git("show", f"v{new}:uv.lock") + "\n"), f'version = "{new}"')
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".venv")), "something synced an environment")

    def test_a_bump_changes_no_dependency_pin(self):
        # Every [[package]] block but the root one, and the root's own deps, byte for byte.
        def pins(lock):
            return [p for p in tomllib.loads(lock)["package"] if p["name"] != NAME], \
                   {k: v for k, v in own_package(lock).items() if k != "version"}
        before = self.lock()
        out = self.release("minor")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(pins(self.lock()), pins(before))

    def test_a_dependency_pypi_does_not_have_still_releases(self):
        # The family cut: a dependency floored at a release not yet on PyPI. A re-lock
        # is unsatisfiable here (offline, empty cache); the release must not need one.
        text = read(self.root, "pyproject.toml")
        floored = text.replace("dependencies = []", 'dependencies = ["sessionkit>=99.0.0"]', 1)
        self.assertNotEqual(floored, text, "pyproject.toml has no `dependencies = []` line to floor")
        self.write("pyproject.toml", floored)
        self.commit_all("floor a dependency at an unreleased version")
        before, new = self.lock(), next_patch(self.version)
        out = self.release("patch")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assert_only_the_root_line_moved(before, self.version, new)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_lock_check_passes_offline_after_a_release(self):
        pre = subprocess.run(["uv", "lock", "--check"], cwd=self.root, env=self.env, capture_output=True, text=True)
        if pre.returncode != 0:
            self.skipTest(f"SKIPPED: uv lock --check does not pass offline before the release: {pre.stderr.strip()}")
        out = self.release("patch")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        check = subprocess.run(["uv", "lock", "--check"], cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertEqual(self.git("status", "--porcelain"), "", "uv lock --check wrote something")

    def test_dry_run_reports_the_lock_edit_and_writes_nothing(self):
        before, new = self.snapshot(), next_patch(self.version)
        out = self.release("patch", "--dry-run")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("--frozen", out.stdout)
        self.assertIn(f"uv.lock: root version {self.version} -> {new}", out.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_a_bad_lock_is_refused_before_anything_is_written(self):
        cases = ((no_root, "has 0 root [[package]] blocks"), (two_roots, "has 2 root [[package]] blocks"),
                 (two_versions, "has 2 version lines"), (not_the_root_source, "has 0 root [[package]] blocks"))
        good = self.lock()
        for mangle, says in cases:
            mangled = mangle(good)
            self.assertNotEqual(mangled, good, mangle.__name__)
            self.write("uv.lock", mangled)
            self.commit_all(f"a lock release.py must refuse: {mangle.__name__}")
            for dry in (False, True):
                with self.subTest(mangle=mangle.__name__, dry=dry):
                    out = self.refused(["patch", *(["--dry-run"] if dry else [])], says)
                    self.assertIn("nothing was written", out.stderr)
                    self.assertNotIn("uv version", out.stdout, "refused AFTER uv ran")

    def test_refuses_a_missing_lock(self):
        self.git("rm", "-q", "uv.lock")
        self.git("commit", "-q", "-m", "no lock")
        self.refused(["9.9.9"], "uv.lock not found")


# -- uv.lock helpers ------------------------------------------------------------

ROOT_HEAD = f'[[package]]\nname = "{NAME}"\nversion = '
ROOT_BLOCK = re.compile(rf'^\[\[package\]\]\nname = "{NAME}"\n.*?(?=^\[\[package\]\]$|\Z)', re.M | re.S)


def own_package(lock):
    (own,) = [p for p in tomllib.loads(lock)["package"] if p["name"] == NAME]
    return own


def root_line(lock):
    m = re.search(rf'^\[\[package\]\]\nname = "{NAME}"\n(version = "[^"]*")\n', lock, re.M)
    assert m, f"no root {NAME} block in uv.lock"
    return m.group(1)


def with_root(lock, old, new):
    """lock with the root version line, and only it, moved from old to new."""
    assert lock.count(f'{ROOT_HEAD}"{old}"\n') == 1
    return lock.replace(f'{ROOT_HEAD}"{old}"\n', f'{ROOT_HEAD}"{new}"\n')


def next_patch(version):
    major, minor, patch = version.split(".")
    return f"{major}.{minor}.{int(patch) + 1}"


def no_root(lock):
    return ROOT_BLOCK.sub("", lock, count=1)


def two_roots(lock):
    return lock + "\n" + ROOT_BLOCK.search(lock).group(0)


def two_versions(lock):
    return re.sub(rf'^(name = "{NAME}"\nversion = "[^"]*"\n)', r'\1version = "0.0.0"\n', lock, count=1, flags=re.M)


def not_the_root_source(lock):
    """The sessionview block present, but sourced from an index: not the project."""
    return re.sub(rf'^(name = "{NAME}"\nversion = "[^"]*"\n)source = \{{ editable = "\." \}}$',
                  r'\1source = { registry = "https://pypi.org/simple" }', lock, count=1, flags=re.M)


def load_release():
    spec = importlib.util.spec_from_file_location("release_under_test", os.path.join(REPO, "scripts", "release.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FrozenVersion(unittest.TestCase):
    """Every `uv version` set and bump carries --frozen, dry and real: no uv needed."""

    def test_uv_version_is_frozen_on_both_paths(self):
        release = load_release()
        for spec in ("patch", "minor", "major", "9.8.7"):
            for dry in (False, True):
                with self.subTest(spec=spec, dry=dry):
                    done = subprocess.CompletedProcess([], 0, stdout=f"{NAME} 0.3.0 => 9.8.7\n", stderr="")
                    with mock.patch.object(release.subprocess, "run", return_value=done) as run, \
                            contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(release.bump(spec, dry), "9.8.7")
                    (call,) = run.call_args_list
                    argv = list(call.args[0])
                    self.assertIn("--frozen", argv)
                    self.assertEqual("--dry-run" in argv, dry)
                    # The dry argv is the real argv plus --dry-run: a rehearsal runs the same call.
                    self.assertEqual([a for a in argv if a != "--dry-run"],
                                     ["uv", "version", "--bump", spec, "--frozen"]
                                     if spec in ("patch", "minor", "major") else ["uv", "version", spec, "--frozen"])

    def test_no_uv_version_call_lacks_frozen(self):
        # Every call that can write a version; the read (--short) never locks.
        text = read(REPO, "scripts/release.py")
        self.assertNotIn("--no-sync", text)
        self.assertIn('args.append("--frozen")', text)

    def test_lock_root_finds_the_one_version_value(self):
        release = load_release()
        lock = read(REPO, "uv.lock")
        start, end = release.lock_root(lock, NAME)
        self.assertEqual(lock[start:end], versions(REPO)["pyproject.toml [project].version"])
        self.assertTrue(lock[:start].endswith(ROOT_HEAD + '"'))


class PushAdvice(unittest.TestCase):
    """The printed push line: the branch by name, then exactly one tag, by refname."""

    def test_push_line_names_the_branch_and_one_tag(self):
        line = load_release().push_line("master", "v1.2.3")
        self.assertEqual(line, "git push origin master && git push origin refs/tags/v1.2.3")
        self.assertEqual(re.findall(r"refs/tags/\S+", line), ["refs/tags/v1.2.3"])
        for broad in ("--tags", "--follow-tags", "--all", "--mirror"):
            self.assertNotIn(broad, line)

    def test_no_push_of_all_tags_anywhere(self):
        for rel in ("scripts/release.py", "Makefile"):
            for broad in ("--tags", "--follow-tags"):
                with self.subTest(rel=rel, flag=broad):
                    self.assertNotIn(broad, read(REPO, rel))


def recipe(target):
    """The recipe lines of a Makefile target, as text: never run."""
    lines = read(REPO, "Makefile").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
    out = []
    for line in lines[start + 1:]:
        if not line.startswith("\t"):
            break
        out.append(line.strip())
    return out


class MakeTargets(unittest.TestCase):
    def test_make_release_runs_python3_not_uv_run(self):
        self.assertEqual(recipe("release"), ["@python3 scripts/release.py $(or $(VERSION),$(BUMP))"])

    def test_make_changelog_runs_python3_not_uv_run(self):
        self.assertEqual(recipe("changelog"), ["@python3 scripts/release.py --preview"])

    def test_make_push_pushes_the_branch_and_one_tag_by_name(self):
        body = " ".join(recipe("push"))
        for broad in ("--tags", "--follow-tags", "--all", "--mirror", "push origin HEAD"):
            self.assertNotIn(broad, body)
        self.assertIn('git push origin "$$branch"', body)
        self.assertIn('git push origin "refs/tags/$$tag"', body)
        # The tag is checked before ANY push, the branch's included.
        self.assertLess(body.index("refs/tags/$$tag\" >/dev/null"), body.index("git push"))

    def test_make_push_recipe_against_a_fake_git(self):
        # The recipe's shell, run with a git on PATH that records its argv and pushes
        # nothing: a missing tag pushes nothing; a present one pushes branch then tag.
        body = "\n".join(line[1:] if line.startswith("@") else line for line in recipe("push")).replace("$$", "$")
        with tempfile.TemporaryDirectory(prefix="sv-push-") as tmp:
            shim = os.path.join(tmp, "bin")
            os.makedirs(shim)
            log = os.path.join(tmp, "argv")
            for tool, script in (
                ("git", '#!/bin/sh\necho "git $*" >> "$LOG"\n'
                        'case "$1" in symbolic-ref) echo rel-branch;; rev-parse) [ -n "$HAVE_TAG" ];; esac\n'),
                ("uv", '#!/bin/sh\necho "uv $*" >> "$LOG"\necho 1.2.3\n'),
            ):
                path = os.path.join(shim, tool)
                with open(path, "w") as f:
                    f.write(script)
                os.chmod(path, 0o755)
            for have_tag, rc, pushes in (("", 1, []), ("1", 0, ["git push origin rel-branch",
                                                                 "git push origin refs/tags/v1.2.3"])):
                with self.subTest(have_tag=bool(have_tag)):
                    if os.path.exists(log):
                        os.remove(log)
                    env = {"PATH": shim + os.pathsep + "/usr/bin:/bin", "LOG": log, "HAVE_TAG": have_tag}
                    out = subprocess.run(["/bin/sh", "-c", body], cwd=tmp, env=env, capture_output=True, text=True)
                    self.assertEqual(out.returncode, rc, out.stderr)
                    with open(log) as f:
                        calls = f.read().splitlines()
                    self.assertEqual([c for c in calls if c.startswith("git push")], pushes)
                    if not have_tag:
                        self.assertIn("nothing pushed", out.stderr)


if __name__ == "__main__":
    unittest.main()
