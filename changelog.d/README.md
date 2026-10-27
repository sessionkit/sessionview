# changelog.d: one fragment per change

**Write your change's changelog entry here, never in `CHANGELOG.md`.** Two
branches that both edit `CHANGELOG.md` clash on it, and a line added just
before a release can merge cleanly under the wrong version. Two branches
that each add their own file here never clash. The release moves the
entries into `CHANGELOG.md`.

## The file

- **One file per change:** `changelog.d/<slug>.md`, for example
  `changelog.d/badge-cache-store.md`. The slug is the change's short name:
  the tail of its branch name, lower-case words joined by single hyphens.
  The name carries no tracker ID, the same as the text.
- **One slug, one file.** If the name is taken, choose a longer slug. Two
  names that differ only in a number's leading zeros (`step-7.md` and
  `step-07.md`) are the same name to the release, and the suite refuses
  them.
- **A change that updates its entry edits its own fragment.** It never adds
  a second one, and never renames the first.
- **A change no user would notice writes no fragment** (tests only, internal
  tooling, CI). Its description says so, in these words:
  `Changelog: none, no user-visible change`.
- **Every `*.md` here but this README is a fragment.** Nothing else belongs
  in `changelog.d/`: no other file name, no sub-directory. The release
  refuses a file it would not read.

## What a fragment holds

One or more Keep a Changelog sections, each with its bullets, exactly as
the entry should read in `CHANGELOG.md`. The sections are `### Added`,
`### Changed`, `### Deprecated`, `### Removed`, `### Fixed` and
`### Security`. This is an entry from `## [0.3.1]`:

```markdown
### Fixed

- The docs no longer say the wheel is an empty package: it carries the
  whole tool and puts four commands on PATH.
```

The release refuses, before it bumps the version and naming the file:

- a `###` heading that is not one of the six;
- text before the first `###`;
- any other heading level (`#`, `##`, `####` and deeper), so a fragment can
  never add a version heading;
- a fragment with no entries.

A heading inside a code fence is text, not a heading.

A fragment never names a version or `[Unreleased]`: the release puts it
under the right one.

**No relative links.** A link written to work from here breaks once the
entry is moved into `CHANGELOG.md`, and one written for `CHANGELOG.md` is
broken here. Name the file in a code span instead: `README.md`, not a link
to it. An in-page `#anchor` counts as relative too. A full web address to
a page outside this repo is fine.

The text rules are the same as for `CHANGELOG.md`: neutral public prose, no
tracker IDs, no private names, paths or host names, and example times only.

## Reading what is pending

`make changelog` prints `## [Unreleased]` with every fragment here collated
into it, as the next release will write it. It uses the release's own
merge, writes nothing, and needs no clean tree. Each file here is also its
own entry, verbatim.

## At release

`make release` (`scripts/release.py`) collects every fragment into
`CHANGELOG.md` under the new `## [X.Y.Z] - date` heading, then `git rm`s
them in the release commit. A release commit holds no fragment.

- **Sections are merged by name, in Keep a Changelog order:** every
  fragment's `### Added` bullets under one `### Added`, then `### Changed`,
  and so on down to `### Security`.
- **Within a section, order is by file name, with numbers compared as
  numbers:** `badge-cache-store.md` before `dock-app-iterm.md`, and
  `step-9.md` before `step-20.md`. An author has no say in where an entry
  lands, and the same files always give the same changelog.
- **Anything still under `## [Unreleased]` in `CHANGELOG.md`** follows the
  fragments under the new version, unchanged. It should be empty: the suite
  fails a branch that writes there.
- `python3 scripts/release.py patch --dry-run` lists the fragments it
  would collect and touches nothing.

## Fixing an entry (a scrub)

- **Not released yet:** edit the fragment, on your branch.
- **Released:** edit the entry in place in `CHANGELOG.md`, under its version.
- **Both at once:** a branch edits a fragment that a release has since
  collated and removed. Git stops the merge with a modify/delete conflict on
  the fragment. Resolve it in three steps:
  1. apply the fragment's new text to the collated entry in `CHANGELOG.md`;
  2. `git rm` the fragment;
  3. run `make scan`.

  **Never resolve it by keeping the deletion alone.** That drops the fix
  silently, and the old text stays in `CHANGELOG.md`.
