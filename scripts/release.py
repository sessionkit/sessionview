#!/usr/bin/env python3
"""Cut a sessionview release. The ONE version lives in pyproject.toml; uv bumps it.

    python3 scripts/release.py patch|minor|major     bump, then release
    python3 scripts/release.py X.Y.Z                 set, then release
    python3 scripts/release.py --current             print the version
    ... --dry-run                                    say what would happen

Steps: uv version --frozen (bump or set) -> record the new version on
uv.lock's own root line (textual) -> mirror it into
.claude-plugin/plugin.json and marketplace.json where they carry a version
field (textual, formatting kept; a file with none is skipped) and into
src/sessionview/__init__.py's __version__ (required) -> stamp CHANGELOG.md's
[Unreleased] as [X.Y.Z] - date, with a fresh [Unreleased] above -> commit
"chore: release vX.Y.Z", the files by name -> annotated tag vX.Y.Z. Never
pushes: it prints the push line, the branch by name and then the one release
tag by its full refname, never a push of all tags (that sends every local
tag: fallback/*, export/*, ready/*). Refuses a dirty tree, a detached HEAD, a
missing CHANGELOG, a missing [Unreleased], a missing __version__, a uv.lock
without exactly one root sessionview block holding one version line, an
existing tag, a bad version spec, and it refuses before it writes anything.

A RELEASE NEVER RE-LOCKS. A plain `uv version X` (or --bump) is a project
write: it re-locks against the index (skipping the sync does not stop that),
and this script commits uv.lock. Cut before the deps are on PyPI, that fails
(unsatisfiable); with UV_FIND_LINKS set, it writes a local-path lock and the
release commits it. So `uv version` always runs with --frozen, which writes
pyproject only and resolves nothing, on the dry path too, so a rehearsal runs
the same uv call as the release. --frozen leaves uv.lock's own `[[package]]
name = "sessionview"` version line on the old version, so the script edits
that one line as text, as mirror() edits the manifests: the bytes uv's own
re-lock writes when the deps are unchanged, and `uv lock --check` passes after
it. The lock is checked BEFORE `uv version` writes anything, so a refusal
leaves pyproject untouched. It is stdlib-only, and `make release` runs it with
python3, never a re-locking `uv run`.

The shape is sessiontools' scripts/release.py. __version__ stays a literal so a
checkout that is not installed still knows its version; this script keeps it
equal to pyproject, and tests/test_release.py pins the copies equal.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PLUGIN = Path(".claude-plugin/plugin.json")
MARKET = Path(".claude-plugin/marketplace.json")
NAME = "sessionview"
INIT = Path("src/sessionview/__init__.py")
CHANGELOG = Path("CHANGELOG.md")
LOCK = Path("uv.lock")
PYPROJECT = Path("pyproject.toml")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
JSON_VERSION = re.compile(r'("version"\s*:\s*")[^"]+(")')
PY_VERSION = re.compile(r'^(__version__ = ")[^"]+(")$', re.M)


def sh(*args: str, dry: bool = False, capture: bool = False) -> str:
    print("  $", " ".join(args))
    if dry and not capture:
        return ""
    out = subprocess.run(args, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        sys.exit(f"release: {args[0]} failed: {out.stderr.strip() or out.stdout.strip()}")
    return out.stdout.strip()


def current() -> str:
    return sh("uv", "version", "--short", capture=True)


def check_spec(spec: str) -> None:
    if spec not in ("patch", "minor", "major") and not SEMVER.match(spec):
        sys.exit(f"release: '{spec}' is not patch|minor|major or X.Y.Z")


def bump(spec: str, dry: bool) -> str:
    """uv version, bump or set, --frozen: pyproject only, never a re-lock (see the docstring)."""
    args = ["uv", "version", "--bump", spec] if spec in ("patch", "minor", "major") else ["uv", "version", spec]
    args.append("--frozen")
    if dry:
        args.append("--dry-run")
    out = sh(*args, capture=True)  # "name old => new"
    return out.split("=>")[-1].strip()


def lock_root(text: str, name: str) -> tuple[int, int]:
    """The (start, end) span of the version VALUE on uv.lock's root line.

    The root is the one [[package]] block named `name` whose source is the
    project itself (editable or virtual "."), and it must hold exactly one
    top-level `version = "..."` line. Anything else is refused: no guess, no
    write.
    """
    starts = [m.start() for m in re.finditer(r"^\[\[package\]\]$", text, re.MULTILINE)]
    roots = []
    for i, start in enumerate(starts):
        block = text[start : starts[i + 1] if i + 1 < len(starts) else len(text)]
        if re.search(rf'^name = "{re.escape(name)}"$', block, re.MULTILINE) and re.search(
            r'^source = \{ (?:editable|virtual) = "\." \}$', block, re.MULTILINE
        ):
            roots.append((start, block))
    if len(roots) != 1:
        sys.exit(
            f"release: {LOCK} has {len(roots)} root [[package]] blocks for {name} (editable or virtual "
            f'source "."), not one - refusing; nothing was written'
        )
    start, block = roots[0]
    versions = list(re.finditer(r'^version = "([^"]*)"$', block, re.MULTILINE))
    if len(versions) != 1:
        sys.exit(
            f"release: {LOCK}'s root {name} block has {len(versions)} version lines, not one - refusing; "
            "nothing was written"
        )
    return start + versions[0].start(1), start + versions[0].end(1)


def set_lock_root(text: str, span: tuple[int, int], version: str, dry: bool) -> None:
    """Write `version` onto the root line found by lock_root(), and nothing else."""
    old = text[span[0] : span[1]]
    print(f"  ~ {LOCK}: root version {old} -> {version} (textual; nothing resolved)")
    if not dry:
        LOCK.write_text(text[: span[0]] + version + text[span[1] :])


def branch() -> str:
    """The branch HEAD is on, by name: the push line names it. A detached HEAD is refused."""
    out = subprocess.run(["git", "symbolic-ref", "--short", "-q", "HEAD"], capture_output=True, text=True, check=False)
    name = out.stdout.strip()
    if out.returncode != 0 or not name:
        sys.exit("release: HEAD is detached - check out the release branch first; nothing was written")
    return name


def push_line(branch: str, tag: str) -> str:
    """The push to run after a release: the branch by name, then THIS tag by its refname.

    Never a push of all tags: that sends every local tag (fallback/*, export/*,
    ready/*).
    `make push` runs the same two pushes.
    """
    return f"git push origin {branch} && git push origin refs/tags/{tag}"


def mirror(path: Path, pattern: re.Pattern, version: str, dry: bool) -> bool:
    """Set the first version field in path. False when the file or the field is absent."""
    if not path.exists():
        return False
    text = path.read_text()
    new, n = pattern.subn(r"\g<1>" + version + r"\g<2>", text, count=1)
    if n != 1:
        print(f"  - {path}: no version field, skipped")
        return False
    print(f"  ~ {path}: version -> {version}")
    if not dry:
        path.write_text(new)
    return True


def preflight() -> tuple[str, tuple[int, int]]:
    """Everything that can refuse without knowing the new version, before any write.

    Returns uv.lock's text and its root version span, read before uv writes.
    """
    if not CHANGELOG.exists():
        sys.exit("release: CHANGELOG.md not found - a release without a changelog is refused")
    if "## [Unreleased]" not in CHANGELOG.read_text():
        sys.exit("release: CHANGELOG.md has no '## [Unreleased]' section - nothing to stamp")
    if not INIT.exists() or not PY_VERSION.search(INIT.read_text()):
        sys.exit(f'release: no `__version__ = "..."` line in {INIT} - it is a required copy')
    if not LOCK.exists():
        sys.exit(f"release: {LOCK} not found - the release records its version there; nothing was written")
    lock = LOCK.read_text()
    return lock, lock_root(lock, NAME)


def stamp(version: str, dry: bool) -> None:
    text = CHANGELOG.read_text()
    today = datetime.now().astimezone().date().isoformat()
    new = text.replace("## [Unreleased]", f"## [Unreleased]\n\n## [{version}] - {today}", 1)
    print(f"  ~ CHANGELOG.md: [Unreleased] -> [{version}] - {today}")
    if not dry:
        CHANGELOG.write_text(new)


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry = "--dry-run" in sys.argv
    if args == ["--current"]:
        print(current())
        return
    if len(args) != 1:
        sys.exit(__doc__)
    if subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=False).stdout.strip():
        sys.exit("release: the working tree is not clean - commit or stash first")
    check_spec(args[0])
    on = branch()
    lock, span = preflight()
    version = bump(args[0], dry=True)  # the plan: uv says what it would set, writes nothing
    tag = f"v{version}"
    if subprocess.run(["git", "tag", "-l", tag], capture_output=True, text=True, check=False).stdout.strip():
        sys.exit(f"release: tag {tag} already exists")
    if not dry:
        bump(args[0], dry=False)
    set_lock_root(lock, span, version, dry)
    files = [str(PYPROJECT), str(LOCK), str(CHANGELOG), str(INIT)]
    mirror(INIT, PY_VERSION, version, dry)
    for p in (PLUGIN, MARKET):
        if mirror(p, JSON_VERSION, version, dry):
            files.append(str(p))
    stamp(version, dry)
    files = [f for f in files if Path(f).exists()]
    sh("git", "add", "--", *files, dry=dry)
    sh("git", "commit", "-m", f"chore: release {tag}", dry=dry)
    sh("git", "tag", "-a", tag, "-m", f"sessionview {tag}", dry=dry)
    print(f"{'would release' if dry else 'released'} {tag}. Push is yours:")
    print(f"  {push_line(on, tag)}")


if __name__ == "__main__":
    main()
