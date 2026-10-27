"""The changelog as the doc guards read it: CHANGELOG.md plus the fragments.

A change writes its entry to changelog.d/<slug>.md, and only the release
moves it into CHANGELOG.md. So a guard that reads CHANGELOG.md alone misses
every pending entry until the release commit:

- an absence guard (a phrase that must not ship) reads :func:`paths` or
  :func:`texts`, CHANGELOG.md and every fragment;
- a presence guard for an entry that may still be pending reads
  :func:`preview`, CHANGELOG.md with the fragments collated under
  [Unreleased] by scripts/release.py's own merge, as `make changelog` prints
  it and as the next release will write it;
- a guard that exempts CHANGELOG.md as history exempts a fragment the same
  way, through :func:`is_fragment`: a fragment's text is CHANGELOG text that
  has not been collated yet. changelog.d/README.md is no fragment, and is
  still checked.

The fragments are the ones the release collects (release.fragment_paths):
every *.md directly in changelog.d/ but its README.md.
"""
from __future__ import annotations

import contextlib
import functools
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
FRAGMENTS = ROOT / "changelog.d"


@functools.cache
def release():
    """scripts/release.py, loaded as a module once: the release's own code."""
    spec = importlib.util.spec_from_file_location("sessionview_release_docs", ROOT / "scripts" / "release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fragments(directory: Path = FRAGMENTS) -> list[Path]:
    """The live fragments, absolute, in the order the release collates them."""
    return release().fragment_paths(directory)


def is_fragment(rel: str) -> bool:
    """True for a repo path the release collects as a fragment: a *.md
    directly in changelog.d/, but not its README.md. The same rule as
    release.fragment_paths, on a path instead of a directory."""
    parts = Path(rel).parts
    return len(parts) == 2 and parts[0] == "changelog.d" and parts[1].endswith(".md") and parts[1] != "README.md"


def paths() -> list[Path]:
    """CHANGELOG.md, then every fragment."""
    return [CHANGELOG, *fragments()]


def texts() -> list[tuple[Path, str]]:
    """(path, text) for CHANGELOG.md and every fragment."""
    return [(p, p.read_text(encoding="utf-8")) for p in paths()]


def preview(text: str | None = None, frags: list[Path] | None = None) -> str:
    """The whole CHANGELOG with the fragments collated under [Unreleased],
    through release.py's own preview_text (its stamp's merge). By default the
    live CHANGELOG.md and the live fragments; a test passes its own planted
    text or fragments instead. Writes nothing."""
    frags = fragments() if frags is None else list(frags)
    if text is None:
        with contextlib.chdir(ROOT):  # release.py reads CHANGELOG.md from the cwd
            return release().preview_text(frags)
    if not frags:
        return text
    return release().collate(text, release().collect(frags), None)
