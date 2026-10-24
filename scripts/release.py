#!/usr/bin/env python3
"""Cut a sessionview release. The ONE version lives in pyproject.toml; uv bumps it.

    python3 scripts/release.py patch|minor|major     bump, then release
    python3 scripts/release.py X.Y.Z                 set, then release
    python3 scripts/release.py --current             print the version
    ... --dry-run                                    say what would happen

Steps: uv version (bump or set; re-locks uv.lock) -> mirror it into
.claude-plugin/plugin.json and marketplace.json where they carry a version
field (textual, formatting kept; a file with none is skipped) and into
src/sessionview/__init__.py's __version__ (required) -> stamp CHANGELOG.md's
[Unreleased] as [X.Y.Z] - date, with a fresh [Unreleased] above -> commit
"chore: release vX.Y.Z", the files by name -> annotated tag vX.Y.Z. Never
pushes: it prints the push line. Refuses a dirty tree, a missing CHANGELOG, a
missing [Unreleased], a missing __version__, an existing tag, a bad version
spec, and it refuses before it writes anything.

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
INIT = Path("src/sessionview/__init__.py")
CHANGELOG = Path("CHANGELOG.md")
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
    """uv version, bump or set. --no-sync: re-lock uv.lock, leave the venv alone."""
    args = ["uv", "version", "--bump", spec] if spec in ("patch", "minor", "major") else ["uv", "version", spec]
    args.append("--no-sync")
    if dry:
        args.append("--dry-run")
    out = sh(*args, capture=True)  # "name old => new"
    return out.split("=>")[-1].strip()


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


def preflight() -> None:
    """Everything that can refuse without knowing the new version, before any write."""
    if not CHANGELOG.exists():
        sys.exit("release: CHANGELOG.md not found - a release without a changelog is refused")
    if "## [Unreleased]" not in CHANGELOG.read_text():
        sys.exit("release: CHANGELOG.md has no '## [Unreleased]' section - nothing to stamp")
    if not INIT.exists() or not PY_VERSION.search(INIT.read_text()):
        sys.exit(f'release: no `__version__ = "..."` line in {INIT} - it is a required copy')


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
    preflight()
    version = bump(args[0], dry=True)  # the plan: uv says what it would set, writes nothing
    tag = f"v{version}"
    if subprocess.run(["git", "tag", "-l", tag], capture_output=True, text=True, check=False).stdout.strip():
        sys.exit(f"release: tag {tag} already exists")
    if not dry:
        bump(args[0], dry=False)
    files = ["pyproject.toml", "uv.lock", str(CHANGELOG), str(INIT)]
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
    print("  git push && git push --tags")


if __name__ == "__main__":
    main()
