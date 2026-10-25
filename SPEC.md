# sessionview — specification

**sessionview is a controller and view for the `session` tools, drawn
beside tmux.** One sidebar lists the projects (tmux sessions) and the
seats (agents) on this machine and on named remote hosts. A click goes
there; a right-click gives a menu built from what is installed. The tab
bar shows which windows hold an agent. Nothing in sessionview is a
source of truth: every fact comes from `session list`, tmux, git and
`tm`, and every action is a `session`, `tmux`, `tm`, mail or plugin
command.

This spec describes sessionview 0.2.0. Where this spec and the code
disagree, the code is the bug.

sessionview was called Herd before 0.2.0; the state dir moves once, on
first run, from `~/.local/state/herd`. Its look and its plugin contract
are borrowed from herdr, a different tool.

## 1. Surfaces

- **The sessionview window** — `sessionview [SESSION]` in any terminal:
  a private outer tmux (the "frame", one session per terminal) holds two
  panes. Left = the sidebar under a supervisor (`q` reloads, `Q` quits,
  a crash holds the error on screen and waits, SIGHUP = clean reload);
  right = a tmux client attached to SESSION (default `main`) on its own
  server (`--sock`). The seam between them is a faint line; dragging it
  sets the sidebar's width, which is kept (`width`, and `fit` back to
  `fixed`). The frame dies with its terminal. A named SESSION must already
  exist on that server (else usage, exit 2; `sessionview session NAME`
  makes one). The frame needs a terminal (stdin and stdout a tty). Run
  inside tmux it takes over the caller's OWN client (`detach-client -E`)
  and no other: the caller's tty must be its pane's, and exactly one client
  must be on a session holding that pane's window (a session group or a
  linked window counts every such session; `lib/client.sh`); otherwise it
  refuses, exit 2, and touches nothing. The popup and
  `sessionview-sidebar-toggle` resolve "this client" by the same rule,
  never by "most recently active".
- **The sidebar** — one process, the view below, refreshed every
  `refresh` seconds (default 2). Also runs as a tmux popup (`prefix H` →
  `display-popup -E ... --popup`): the same view, and a jump closes it.
- **The tab bar** — tmux `status-format[0]` at the top of sessionview
  sessions (`tmux/frame.conf`, session-scoped, applied on attach and on
  every jump), or globally (`tmux/tabs-top.conf`). herdr's Mocha
  palette.
- **Helpers** — `sessionview-session NAME` (a project session with its
  configured tabs), `sessionview-newtab` (the tab bar's `+`).

## 2. The view

```text
 sessionview.dev                  <- the brand
 ✉ mail                           <- the user's own mail (user_mail_*)
 default ⋯                        <- the taskmaster STORE; name = its store
                                     view, ⋯ = Switch store
 ◐ webapp  feature/login  2🥚     <- PROJECTS: one tmux session each. glyph =
 ○ docs                              rollup of its seats; branch ONLY when off
 ● api                               the repo's default branch; 🥚 = ready
 build-host                          tags waiting. Then each REMOTE host,
   ● deploy                          dim, with its sessions.
 +                                <- new: open a SESSION (picker)
 agents           all · grouped   <- the seats heading: two toggles
 ◐ webapp-a1     opus4.1  41%     <- SEATS: glyph, name; model and context
 ● @build-host worker-3   -          at the right; "@host " in front of a
                                     remote seat
   +3 more                        <- when they do not fit
```

Every row is a format string in config (`project_format`,
`agent_format`, `store_format`, ...), so the columns above are the
defaults, not fixed. Rules:

- The branch shows only when the repo is **not** on its default branch.
  Default = `origin/HEAD`, else PROJECT.md `contributing:` when it names
  a real ref, else `master` if it exists, else `main`, else `master`.
  Cached 10 min per repo.
- **The ready badge** (`{ready}` in `project_format`): the number of
  ready tags waiting on the project's repo, then `ready_glyph` (an egg by
  default). A click on it opens the project's `ready_window` tab (default
  `git`, lazygit).
- The selected row is **bold and brighter** (`selected_fg`,
  `selected_bold`); the tell is the text, not a background band.
- **Grouped** (`group_by`) groups seats contiguously, in project-list
  order; grouped by session, remote seats group as `host:session`.
- **all | current** (the heading's left toggle): current = the seats
  whose pane is in the selected project.
- The selected project row carries its menu as `⋯` at the right.
- **Overflow**: the seats block starts at half height only when that
  fits; otherwise it creeps up under the projects; if it still cannot
  fit, the last row is `+N more`, never a silent cut.
- **Sort** (`sort`, default rank then idle time): blocked and waiting <
  busy < idle < shell.
- **Glyphs**: `■` red blocked/waiting, `◐` yellow busy, `●` green idle,
  `○` dim shell. The same glyph appears in the tab bar for a window that
  holds a seat (rollup), via the window options `@sessionview_glyph` /
  `@sessionview_glyph_fg`, written by the sidebar on change and cleared
  on exit (`tab_glyphs`).
- Width is a wish, put back on the pane every render: `fit: fixed` (the
  default) is `width` columns; `fit: auto` fits the widest row, clamped
  to `width_min` and `width_max`. A drag on the seam becomes the new
  `width`. Only a drag counts: before a client is attached the pane is
  changed by the frame itself (its split, its resize), and that is never
  remembered. A terminal resize, of the height or the width, is never a
  drag either: the sidebar puts the wish back, and it is the only writer
  of its width (the frame sets no resize hook). It reads its width from
  tmux, not from its terminal size, which can lag a resize. The frame's
  window is born at the size of the terminal that opens it, so attaching
  changes no width, and the frame hands the sidebar the widths it set up,
  so a drag made before the sidebar's first redraw is a drag too.
- esc backs out of any view.

## 3. Actions

- Click a project → `switch-client -c <sessionview client> -t SESSION`,
  after giving the session the sessionview look. Click a seat → the
  same on whichever store's tmux server it lives, then `select-window` /
  `select-pane`.
- Click a remote row → a local session named after the host, with one
  window per remote session running `ssh -t host tmux attach` (the
  seat's window and pane are selected first); raised if it already
  exists.
- Click the store name → that store's own session and its store view
  (`store_windows` tabs). `⋯` (or `s`) → Switch store, a menu over the
  sidebar.
- **new** (`+`) → the picker: taskmaster projects plus the git repos
  under `project_dirs`, most recently opened first (`picker_order`;
  recency from `recent.tsv` or the store project's mtime); typing
  filters, up/down move, enter opens the highlighted row or the typed
  name; open sessions are marked and a click on one just jumps. The
  same picker opens a new tab and starts an agent.
- **sessionview-session NAME [--repo DIR] [--plain] [--print]** builds
  the session from the `windows` list in config. Shipped tabs: `project`
  (the store project dir, the editor on PROJECT.md), `tasks`, `messages`
  (the project's mail, read-only, in neomutt; only when its mailbox
  exists), `repo` (a shell), `git` (lazygit, with a shell pane under it),
  `editor` (the README), and `shell` (the fallback when nothing else
  applies). An entry's `when` decides whether it applies to a project;
  some are picker-only. Every tab is a shell with the tool typed in.
  Repo = `tm project get NAME`'s git url as `~/Code/<url with : as />`
  minus `.git`, else a `~/Code/*/*/NAME` glob, else a repo found under
  `project_dirs`, else none. `--plain` / `SESSIONVIEW_PROFILE=0` = one
  shell.
- **Tab bar**: click selects; drag reorders (`MouseDrag1Status
  swap-window -d -t=`); `+` opens the new-tab picker; a dim `×` closes
  the tab. The `×` is on by default; `@sessionview_tab_close 0` turns
  it off.
- **Right-click** → the menu of §5. Menus, prompts and confirms draw
  **inside the sidebar** (a tmux menu would appear in the other pane).
- **The agent pane menu** is a different thing: right-click in one of
  your OWN panes (not the sidebar) that holds an agent, and tmux's pane
  menu gains Speak / Continue / Read Clipboard / Park / Succeed → that
  agent, each a subject-only mail (`bin/tmux-send-agent`, via
  sessionmail's `message send`). It is a tmux `bind-key` in
  `tmux/agent-menu.conf`, global to the server, so it is **opt-in**
  (`pane_menu`, default false): turning it on replaces your own
  right-click menu. The frame loads it at every launch when it is on;
  without the frame, one `source-file -q` line in `~/.tmux.conf`.

## 4. Contract with the tools it calls

What sessionview runs, and what each tool must keep true. Besides these
it runs `ps` (to place a seat by its pid, and to read its voice and tm
flags), `pbcopy` (Copy name), and the commands config names: each
tab's `command`, `user_mail_command`, `agent_command`.

- **`session list --json [--no-recap] [--no-context]`** — the seats.
  `--no-recap` / `--no-context` are passed unless a format displays the
  recap or the context. Fields used: `name short session_id pid agent
  status repo project cwd tmux_socket tmux_pane runtime_s idle_s
  context_pct context_used context_peak context_model` (+ `recap` when
  a format asks). `status` ∈ busy | idle | shell | waiting | blocked.
  `tmux_socket` names the tmux server (`-L`) and `tmux_pane` the seat's
  pane on it, or null. Pane ids repeat across servers, so a local seat
  without `tmux_socket` is placed by its pid's ancestry on the viewed
  server; only a seat with no pid (or no `ps`) falls back to the pane id
  it reports. A remote seat is placed by its pane id on its own host.
- **`session start --list-agents`** — the agents the picker offers.
  Starting one runs `agent_command` (default `session start
  --tmux-target {project} --no-switch {agent}`).
- **Remotes** — for each host in `remotes`, one ssh call per
  `remote_refresh` (default 5 s): `session list --json` plus tmux
  `list-panes` / `list-sessions`, with `BatchMode`; the sidebar keeps
  no control socket of its own. With `remote_connect = "ride"` (the
  default) it asks `ssh -O check HOST` and uses only a control master
  you already hold, otherwise it shows `not connected · ssh HOST`;
  `auto` connects by itself. A remote attach runs with
  `TERM=xterm-256color` (a host without the local terminal's terminfo
  refuses tmux otherwise).
- **Mail** — every mail action runs `bin/sessionview-send ADDRESS ...`,
  which is sessionmail's `message send ADDRESS ...` sent as you
  (`bin/sessionview-from` resolves the name, from `$SESSIONVIEW_FROM`
  and `mail_from` down to `$USER`). ADDRESS is the seat's **session id**
  where it has one (the exact seat). sessionview never writes a maildir.
  The `messages` tab finds a mailbox with `message path` and opens it
  read-only in `neomutt -R`; its folder list comes from notmuch when
  notmuch is installed and indexes the `Type` and `Project` headers.
- **`tm`** — `tm store list -f json`, `tm project list -f json --store
  S`, `tm store boot NAME` (to open a store whose server is down), `tm
  project get NAME` (the repo url); the taskmaster plugin adds `tm kick`.
- **git** — `git -C REPO` `rev-parse`, `symbolic-ref`, `status` and
  `for-each-ref` (the branch, the git status, the ready tags). Read only.
- **tmux** — the substrate: every view and jump is a tmux command.

## 5. Plugins — `plugins/NAME/plugin.toml` (from herdr's contract)

A plugin is a directory `plugins/NAME/` with a `plugin.toml` manifest
(`SESSIONVIEW_PLUGINS=` names another plugin dir). A bad manifest is
reported on stderr and skipped.

- `requires = ["tm", "~/path"]` — a bare word must be on PATH, a path
  must exist; otherwise the plugin contributes **nothing** (hidden, not
  greyed).
- `[[actions]]`: `id title key contexts` (`agent` | `project` |
  `store`), optional `when` (a context field that must be truthy,
  `!field` negates, a list means all; false → **greyed**: it exists, it
  does not apply), and **one** `command = [argv]`: no shell ever sees
  the text. `{agent.name}`-style placeholders are filled from the row;
  a missing field greys the item. Optional: `prompt = "label"` (typed
  text → `{input}` and a subject-safe `{input_subject}`), `confirm =
  "text"` (y/n first), `body = "text"` (written to a 0600 file, its
  path is `{body}`). `"./name"` runs a script in the plugin dir;
  multi-step work ships a script.
- Env for the command: `SESSIONVIEW_CONTEXT_JSON`,
  `SESSIONVIEW_PLUGIN_ID`, `SESSIONVIEW_PLUGIN_ROOT`,
  `SESSIONVIEW_ACTION_ID`; cwd = the plugin dir. A non-zero exit shows
  its first stderr line in the note box.
- Contexts:
  - `agent.*` = name short session_id address pane window status agent
    repo cwd pid context_pct voice tm host rsession
  - `project.*` = name path repo branch branch_raw default git ready
    tm_dir socket super super_seat super_sid super_pane engineer_seat
    engineer_sid
  - `store.*` = name socket
- The shipped plugins: **session** owns the agent verbs (Message,
  Continue, Settle, Stand down, Succeed) and starting an agent;
  **voicemode** adds Speak; **taskmaster** keeps project things (Tasks,
  Kick, Message super, Speak super) and Kick on the store row. The
  builtins (Rename, New tab, Config, Settings, Close, Copy name, Jump
  to, Keys) use the same shape.
- Remote seats: mail and speak items are greyed (there is no
  cross-host address form yet); Jump to opens the ssh tab.

## 6. Config — `config.json`, JSON everywhere

`bin/sessionview-config` owns one cascade; a later layer wins:

1. `config/config.json`: the template, with every key and every default,
   explicit.
2. `~/.sessionkit/view/settings/view.json`: yours, made from the template
   on first read. If it is absent and an older install's file is present
   (see Upgrading in docs/configuration.md), nothing is made or read:
   `sessionview-config` exits 3 and names both paths and the move. If both
   are present, the new one is used and a warning names the old one, which
   a walk-up under the home dir would read as an untrusted layer.
3. `STORE/.sessionview`.
4. `.sessionview`, walked up from the project root.

A store's or a project's `.sessionview` may reorder tabs and add plain
ones, but never sets a `command`: commands come only from the template
and your home file. Keys are described in `config/README.md`. One TAB
in a format = "right-align the rest". Rows and layout live in config,
and so do two colours (`selected_fg`, `popup_bg`); the rest do not yet
(the glyph palette is in the sidebar, the tab bar's in the tmux confs).
`get KEY --where` names the file that decided.

## 7. Known limits

- A remote seat has no cross-host mail address yet, so Message and
  Speak are greyed for `@host` rows.
- A remote seat's voice and tm are read from local `ps` argv; over ssh
  they are unknown, so Speak is greyed. `session list --json` could
  carry them.
- Hover is impossible in a tmux status line, so the tab `×` is either
  always shown or off.
- `switch-client` moves the whole client: a sidebar pane inside the
  session would be left behind. That is why the sidebar runs in the
  frame or as a popup.
- The sidebar tells a drag from a terminal resize by whether the
  frame's window width changed since its last redraw. A drag and a width
  resize of the terminal between two redraws read as a resize, and the
  drag is put back: drag again.
