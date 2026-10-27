---
name: sessionview
description: >-
  sessionview - a sidebar for tmux that shows your projects (tmux
  sessions) and your agents (Claude Code seats), here and on remote hosts,
  and lets you open a project, start an agent on it, and message it. Use
  when a user asks how to use the sidebar, where its config lives, how to
  open a project or start an agent, or when you must show the user a window.
---

# sessionview

One terminal window: a sidebar on the left (`bin/tmux-sidebar`), your tmux
session on the right. The sidebar is the front door; `sessionview` opens it.

Several agents in one seat? See the sessionkit skill's card, "Several agents in one seat".

## Commands (`bin/`)

- `sessionview` — open the frame (sidebar + your session) in this terminal.
- `sessionview-session NAME` — open a project as a tmux session, its tabs
  from config's `windows` list (`references/tabs.md`); an existing one is kept.
- `sessionview-config get KEY [--project DIR] [--where]` / `dump` / `path` — the
  config. JSON everywhere, no hidden defaults: `config/config.json` is the
  template; `~/.sessionkit/view/settings/view.json` is made from it on first
  read; `STORE/.sessionview` and a project's `.sessionview` layer on top.
  An older install's file is never read (see Upgrading in
  docs/configuration.md): alone, it makes `sessionview-config` refuse
  (exit 3, the move to run, on stderr and in the sidebar); beside the new
  file, it gets a warning to remove it.
- `session start`, `session list` — from sessiontools
  (`uv tool install sessiontools`). Optional: without `session` the sidebar
  still shows projects (tmux sessions), but no agent rows and no Start an
  agent.
- Mail is sessionmail's `message send TO -s SUBJECT -f FILE` (and
  `message list` / `message read`), never `session mail send`.

## The sidebar

- Top: the store row: its name opens that store's session and store view;
  its `⋯` (or `s`) opens Switch store; right-click it to Kick the GC. Projects, one row each; click
  opens it. `new` opens the picker (type to filter, Enter opens).
- `menu` or right-click a project: Rename, New tab, Close, Config (opens
  the config in `$EDITOR`), and plugin actions - **Start an agent** (`a`,
  Enter = a plain claude; `agent_command` in config says what runs).
- Agents: one row per seat, glyph = state; right-click: Message, Continue,
  Settle, Stand down, Succeed, Jump to, Copy name.
- `q` reloads the sidebar (new code, new config); `Q` quits.

## More detail (`references/`)

- `tabs.md`: the tab types, one `tab-NAME.md` each: project, tasks,
  messages, repo, git, editor, shell.
- `tab-config.md`: the `windows` list, pinning, the config layers.
- `sidebar.md`: glyphs, the ready badge, keys, menus, errors.

## Show-and-tell (for a helping agent)

Move the human's view without touching their keyboard: `show-me pane:ID`
focuses a pane, `show-me FILE:10-20` opens a file at those lines. A launched
seat cannot run `tmux-show`: it is not on its PATH.

## Neighbours

`show-me` (open a file or URL in the right place - its own repo, install it
beside this plugin), `tmux`, `lazygit`, `neovim`, `claude-code` (this
plugin's driving skills), `session` (seats, mail).
