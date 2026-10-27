#!/usr/bin/env python3
"""Cut a sessionview release. The ONE version lives in pyproject.toml; uv bumps it.

    python3 scripts/release.py patch|minor|major     bump, then release
    python3 scripts/release.py X.Y.Z                 set, then release
    python3 scripts/release.py --current             print the version
    python3 scripts/release.py --preview             print [Unreleased] as the next release will read it
    ... --dry-run                                    say what would happen

Steps: read the fragments in changelog.d/ -> uv version --frozen (bump or
set) -> record the new version on
uv.lock's own root line (textual) -> mirror it into
.claude-plugin/plugin.json and marketplace.json where they carry a version
field (textual, formatting kept; a file with none is skipped) and into
src/sessionview/__init__.py's __version__ (required) -> stamp CHANGELOG.md's
[Unreleased] as [X.Y.Z] - date, with a fresh [Unreleased] above, the
fragments' entries under it -> git rm the fragments, then check that git
tracks no fragment under changelog.d/ -> commit "chore: release vX.Y.Z", the
files by name and the deletions -> annotated tag vX.Y.Z. Never
pushes: it prints the push line, the branch by name and then the one release
tag by its full refname, never a push of all tags (that sends every local
tag: fallback/*, export/*, ready/*). Refuses a dirty tree, a detached HEAD, a
missing CHANGELOG, a missing [Unreleased], a missing __version__, a uv.lock
without exactly one root sessionview block holding one version line, a bad
fragment, a fragment git does not track, a tracked file under changelog.d/
that is not changelog.d/README.md or a fragment, an existing tag, a bad
version spec, and it refuses before it writes anything.

Fragments: each change writes changelog.d/<slug>.md, never CHANGELOG.md, so
two branches never clash on one file. The slug is the tail of the change's
branch name. Every *.md directly in changelog.d/ but README.md is a fragment.
They are read in file-name order, numbers compared as numbers (9, then 20,
then 999, then 1000). A fragment holds ### sections only, each with its
entries; text before the first ###, any other heading level, and a fragment
with no entries are refused, naming the file. A heading inside a code fence
is text.

SECTIONS picks the shape. A tuple of Keep a Changelog names (sessionview's):
only those sections are allowed, and same-named sections are merged, in the
tuple's order. None (another repo's headline shape): any "### <headline>"
starts a section, and each section is kept whole, in fragment order; nothing
is merged, within a fragment or across them. Either way the collated
sections go first under the new version, and the text that sat under
[Unreleased] follows them unchanged. No fragments is the plain stamp, byte
for byte.

--preview prints ## [Unreleased] with the pending fragments collated into
it, through the stamp's own merge. It reads the disk, so an uncommitted
fragment shows; it needs no uv, no git and no clean tree, and writes nothing.

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
FRAGMENTS = Path("changelog.d")
FRAGMENTS_README = FRAGMENTS / "README.md"
# The fragment shape. A tuple: Keep a Changelog sections only, merged in that
# order (sessionview's CHANGELOG). None: headline sections, kept whole,
# nothing merged.
SECTIONS: tuple[str, ...] | None = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")
UNRELEASED = "## [Unreleased]"
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
    if UNRELEASED not in CHANGELOG.read_text():
        sys.exit("release: CHANGELOG.md has no '## [Unreleased]' section - nothing to stamp")
    if not INIT.exists() or not PY_VERSION.search(INIT.read_text()):
        sys.exit(f'release: no `__version__ = "..."` line in {INIT} - it is a required copy')
    if not LOCK.exists():
        sys.exit(f"release: {LOCK} not found - the release records its version there; nothing was written")
    lock = LOCK.read_text()
    return lock, lock_root(lock, NAME)


# ---- fragments ---------------------------------------------------------------


def _name_key(path: Path) -> list:
    """File-name order, numbers compared as numbers: 999 before 1000.
    re.split with a group alternates text and digits, so the parts line up."""
    return [int(s) if s.isdigit() else s for s in re.split(r"(\d+)", path.name)]


def fragment_paths(directory: Path = FRAGMENTS) -> list[Path]:
    """The fragments to collect: every *.md in changelog.d/ but its README.md,
    in _name_key order. An absent directory has none."""
    if not directory.is_dir():
        return []
    found = [p for p in directory.glob("*.md") if p.is_file() and p.name != "README.md"]
    return sorted(found, key=_name_key)


def _git_files(directory: Path) -> list[str]:
    """What git tracks under directory, at any depth, as repo paths."""
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", directory.as_posix()], capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        sys.exit(f"release: git ls-files failed: {out.stderr.strip() or out.stdout.strip()}")
    return [p for p in out.stdout.split("\0") if p]


def check_tracked(fragments: list[Path], directory: Path = FRAGMENTS) -> None:
    """Before the bump: git and the collector must agree on changelog.d/.
    A tracked file there that is neither its README.md nor a fragment the
    collector reads would be left behind unread (a nested file, a .markdown);
    a fragment git does not track (one an ignore rule hides) would be
    collated and then fail the git rm. Each refuses, naming the files."""
    readme = (directory / "README.md").as_posix()
    collected = {p.as_posix() for p in fragments}
    tracked = set(_git_files(directory))
    stray = sorted(tracked - collected - {readme})
    if stray:
        sys.exit(
            f"release: tracked under {directory.as_posix()}/ but not a fragment the release reads: "
            f"{', '.join(stray)} - a fragment is {directory.as_posix()}/<slug>.md; rename or remove it"
        )
    untracked = sorted(collected - tracked)
    if untracked:
        sys.exit(
            f"release: a fragment git does not track (an ignore rule?): {', '.join(untracked)}"
            " - add it, or move it out of the directory"
        )


def check_left(directory: Path = FRAGMENTS) -> None:
    """After the git rm: git tracks nothing under changelog.d/ but its
    README.md. It reads git, not the glob that chose the fragments, so a
    fragment the glob missed cannot pass it."""
    readme = (directory / "README.md").as_posix()
    left = [p for p in _git_files(directory) if p != readme]
    if left:
        sys.exit(f"release: fragments still tracked after the git rm: {', '.join(left)} - nothing committed")


def _fence(line: str) -> bool:
    return line.lstrip().startswith(("```", "~~~"))


def _section_name(line: str) -> str | None:
    """The section a heading line opens, or None if a fragment may not hold it."""
    if not line.startswith("### "):
        return None
    name = line[4:].strip()
    if SECTIONS is None:
        return name or None
    return name if name in SECTIONS else None


def _shape() -> str:
    if SECTIONS is None:
        return "### <headline> sections"
    return ", ".join("### " + s for s in SECTIONS)


def parse_fragment(path: Path) -> list[tuple[str, str]]:
    """One fragment's sections, [(name, its entries)], in the order written.
    An empty section is dropped. Under a SECTIONS tuple a section named twice
    is one section; under None every section stands alone. Refused: a
    heading that is not a section, text before the first section, and a
    fragment with no entries at all. A heading inside a code fence is text."""
    chunks: list[tuple[str, list[str]]] = []  # (section, its lines), as written
    fenced = False
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not fenced and re.match(r"#{1,6}(\s|$)", line):
            name = _section_name(line)
            if name is None:
                sys.exit(f"release: {path}:{n}: '{line}' - a fragment holds only {_shape()}")
            chunks.append((name, []))
            continue
        if _fence(line):
            fenced = not fenced
        if not chunks:
            if line.strip():
                sys.exit(f"release: {path}:{n}: text outside a ### section: '{line}'")
            continue
        chunks[-1][1].append(line)
    sections: list[tuple[str, list[str]]] = []
    for name, lines in chunks:
        body = "\n".join(lines).strip("\n")
        if not body.strip():
            continue
        same = next((s for s in sections if s[0] == name), None) if SECTIONS is not None else None
        if same is not None:
            same[1].append(body)
        else:
            sections.append((name, [body]))
    if not sections:
        sys.exit(f"release: {path}: no entries - write some, or delete the fragment")
    return [(name, "\n".join(bodies)) for name, bodies in sections]


def read_fragments(paths: list[Path]) -> dict[Path, list[tuple[str, str]]]:
    """Every fragment parsed, so a bad one refuses before anything is written."""
    return {p: parse_fragment(p) for p in paths}


def collect(paths: list[Path]) -> str:
    """The fragments as one block of ### sections, as merge() lays them; "" for none."""
    return merge(read_fragments(paths))


def merge(parsed: dict[Path, list[tuple[str, str]]]) -> str:
    """collect's merge, over fragments already read (dicts keep their order).
    SECTIONS None: every section whole, fragment by fragment, as written.
    A tuple: same names merged, in the tuple's order, entries in fragment order."""
    if SECTIONS is None:
        blocks = [f"### {name}\n\n{body}" for sections in parsed.values() for name, body in sections]
    else:
        blocks = []
        for name in SECTIONS:
            bodies = [body for sections in parsed.values() for n, body in sections if n == name]
            if bodies:
                blocks.append(f"### {name}\n\n" + "\n".join(bodies))
    return "\n\n".join(blocks)


def _next_version(lines: list[str], start: int) -> int:
    """Index of the first '## ' line at or after start, outside a code fence,
    else len(lines)."""
    fenced = False
    for i in range(start, len(lines)):
        if _fence(lines[i]):
            fenced = not fenced
        elif not fenced and lines[i].startswith("## "):
            return i
    return len(lines)


def _read_changelog() -> str:
    if not CHANGELOG.exists():
        sys.exit("release: CHANGELOG.md not found - a release without a changelog is refused")
    text = CHANGELOG.read_text()
    if UNRELEASED not in text:
        sys.exit("release: CHANGELOG.md has no '## [Unreleased]' section - nothing to stamp")
    return text


def collate(text: str, block: str, heading: str | None) -> str:
    """text with block put under [Unreleased], ahead of the body already there.
    heading (a version line) goes between them and leaves [Unreleased] empty;
    None keeps the collated entries in [Unreleased], as the preview reads."""
    lines = text.splitlines(keepends=True)
    at = next((i for i, line in enumerate(lines) if line.rstrip("\n") == UNRELEASED), None)
    if at is None:
        sys.exit("release: CHANGELOG.md has no line that is exactly '## [Unreleased]' - nowhere to collect to")
    end = _next_version(lines, at + 1)
    before, body, after = "".join(lines[:at]), "".join(lines[at + 1 : end]), "".join(lines[end:])
    under = block + ("\n\n" + body.strip("\n") if body.strip() else "")
    top = f"{UNRELEASED}\n\n{heading}" if heading else UNRELEASED
    return f"{before}{top}\n\n{under}\n" + ("\n" + after if after else "")


def stamp(version: str, dry: bool, fragments: list[Path] = ()) -> None:
    text = _read_changelog()
    today = datetime.now().astimezone().date().isoformat()
    heading = f"## [{version}] - {today}"
    if not fragments:
        new = text.replace(UNRELEASED, f"{UNRELEASED}\n\n{heading}", 1)
        print(f"  ~ CHANGELOG.md: [Unreleased] -> [{version}] - {today}")
    else:
        parsed = read_fragments(list(fragments))
        new = collate(text, merge(parsed), heading)
        print(f"  ~ CHANGELOG.md: [Unreleased] -> [{version}] - {today}, with {len(fragments)} fragment(s):")
        for p, sections in parsed.items():
            print(f"      + {p.as_posix()} ({len(sections)} section(s): {', '.join(name for name, _ in sections)})")
    if not dry:
        CHANGELOG.write_text(new)


def preview_text(fragments: list[Path]) -> str:
    """CHANGELOG.md as it reads with the fragments collated under
    [Unreleased], through the stamp's own merge. Writes nothing."""
    text = _read_changelog()
    if not fragments:
        return text
    return collate(text, collect(list(fragments)), None)


def preview(fragments: list[Path]) -> str:
    """Only the [Unreleased] section of preview_text: what --preview prints."""
    lines = preview_text(fragments).splitlines(keepends=True)
    at = next((i for i, line in enumerate(lines) if line.rstrip("\n") == UNRELEASED), None)
    if at is None:  # the plain-stamp CHANGELOG may carry it mid-line only
        sys.exit("release: CHANGELOG.md has no line that is exactly '## [Unreleased]' - nothing to preview")
    return "".join(lines[at : _next_version(lines, at + 1)]).rstrip("\n") + "\n"


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry = "--dry-run" in sys.argv
    if args == ["--current"]:
        print(current())
        return
    if args == ["--preview"]:
        sys.stdout.write(preview(fragment_paths()))
        return
    if len(args) != 1:
        sys.exit(__doc__)
    if subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=False).stdout.strip():
        sys.exit("release: the working tree is not clean - commit or stash first")
    check_spec(args[0])
    on = branch()
    lock, span = preflight()
    fragments = fragment_paths()
    check_tracked(fragments)  # git and the collector agree, before anything is written
    read_fragments(fragments)  # a bad fragment refuses here, before anything is written
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
    stamp(version, dry, fragments)
    if fragments:
        sh("git", "rm", "-q", "--", *(p.as_posix() for p in fragments), dry=dry)
    if not dry:
        check_left()  # git, not the glob: no fragment rides into the release commit
    files = [f for f in files if Path(f).exists()]
    sh("git", "add", "--", *files, dry=dry)
    sh("git", "commit", "-m", f"chore: release {tag}", dry=dry)
    sh("git", "tag", "-a", tag, "-m", f"sessionview {tag}", dry=dry)
    print(f"{'would release' if dry else 'released'} {tag}. Push is yours:")
    print(f"  {push_line(on, tag)}")


if __name__ == "__main__":
    main()
