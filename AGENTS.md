# AGENTS.md

Instructions for any coding agent working in this repo.

## What this is

sessionview is a sidebar for tmux. It lists your projects (tmux sessions)
and your agents, on this machine and on remote hosts. A click goes there;
a right-click opens a menu built from the installed plugins. It is a view
and a controller for the `session` tools, and it holds no state of its
own: every fact comes from `session list`, tmux and git, and every action
is a `session`, `tmux` or plugin command.

## Read the spec before you build

[SPEC.md](SPEC.md) is the contract: the rules of the view, the contract
with `session`, the plugin manifest, config and known limits. Read the
section you are about to change first. Where the spec and the code
disagree, the code is the bug. If a change needs the spec to move, change
the spec in the same commit.

## Layout

- `bin/` the commands: `sessionview`, the frame, the sidebar
  (`tmux-sidebar`), config, autostart, install.
- `lib/` shared shell (`python.sh` finds a Python 3.11+, `state.sh` the
  state directory) and the config screen.
- `src/sessionview/` the wheel's entry point. It runs its namesake from
  the bundled `bin/`.
- `plugins/` menu contributions (session, taskmaster, voicemode), one
  manifest each.
- `tmux/` the tmux confs; `macos/` the Dock app; `skills/` agent skills.
- `tests/` stdlib `unittest`.

## Build and test

Needs Python 3.11 to 3.14 and tmux 3.x. The package is stdlib only,
with no Python dependencies.

    make test      # the suite, about 90 s
    make check     # what this machine has and lacks
    make install   # install the commands
    make app       # the macOS Dock app
    make scan      # pre-publish leak check (needs SESSIONKIT_SCAN)

Stock macOS puts Python 3.9 first on PATH. `make test` finds a newer
one; to choose, `make test PYTHON=/path/to/python3`.

## Rules

- Tests never touch real state. Run each in a scratch HOME
  (`scratch_env` in `tests/support.py`) and pass the session dir (`-c`). Without
  them a test reads the real home settings
  (`~/.sessionkit/view/settings/view.json`), and a walk-up from the checkout
  looking for `.sessionview` reads a real store or project layer.
- Do not bind `^O`. On macOS it never reaches a cbreak-mode TUI (the
  terminal driver eats it as VDISCARD).
- This repo is public. No personal names, hostnames, internal tools or
  private infrastructure in code, comments or docs. `make scan` passes
  before a push.
