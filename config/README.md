# config - JSON everywhere, no hidden defaults

`config.json` here is the **template**: every key, every default, explicit.
There are no hidden defaults, and it is JSON throughout, as Claude Code's
settings are. `bin/sessionview-config` owns the cascade, later wins:

1. `config/config.json` - the template (this dir)
2. `~/.sessionkit/view/settings/view.json` - yours, **made from the template
   on first read** (`SESSIONVIEW_CONFIG=` names another file)
3. `STORE/.sessionview` - a JSON file, or a dir holding `config.json`
4. `.sessionview` walked **up** from the project root, nearest wins

Layers 3 and 4 are **untrusted**: a cloned repo can carry a `.sessionview`,
so they never set a key that runs something. Trust is by a layer's
POSITION in the cascade, not its path. `agent_command` is read from layers
1-2 only. A `windows` / `store_windows` entry from layer 3 or 4 keeps its
data (position, name, when, cwd, focus, auto, console), but its `command`
is the one layers 1-2 give the same name, else none: a plain shell. Each key
ignored is named on stderr with its file.

An older install kept your file elsewhere; [Upgrading from
0.1.0](../docs/configuration.md#upgrading-from-010) has the move. While it
is there and `view.json` is not, `sessionview-config` reads nothing and
makes nothing: it exits 3, names both paths and prints the move to run
(the file, then any `config.json.before-*` backups and `neomuttrc` beside
it, then the empty old dir). The sidebar shows the same message as a note
and runs on the template. If both files are there, the new one is used and
a warning, on stderr and in the sidebar, names the old one: a walk-up
under your home dir would read it as an untrusted layer, so remove it.
Neither check opens the old file.

`sessionview-config dump --where` names the file that set each key. Keys starting
with `_` are notes.

## Keys

Look: herdr's, copied not invented. Rows are one line each, to save
space; ONE TAB in a format means "right-align the rest", herdr's paired
labels.

- `width` `refresh` - sidebar columns; seconds between renders.
- `popup_bg` - the tab-bar colour, reused for the menu box.
- `selected_fg` `selected_bold` - the selected row, a lot brighter. Not
  sampled from herdr yet.
- `project_format` `project_format2` `project_two_line`
  `project_expand_selected` `project_gap` - fields: name glyph windows
  attached repo branch branch_raw default git ready ready_n. Every project is one line;
  the selected one grows `project_format2` (always compact, the selected
  one expanded); `project_two_line` = all.
  `git` is the bare count of uncommitted paths, plus ⇡ahead ⇣behind
  💥conflicts, "" when clean, no brackets.
  `branch` is EMPTY on the default branch, so `master` does not repeat
  down the list. `project_gap` = blank rows between projects, 1 for a
  touchscreen.
- `ready_glyph` `ready_format` - the `{ready}` project field (and
  `{ready_n}`, the bare count): unmerged `ready/*` tags, the reviewed work
  waiting to be merged, as 3🥚 on the right of the row, "" when none, ?🥚
  when no default branch resolves. The count sits LEFT of the glyph, so the
  glyphs line up in a column. `ready_format: "{glyph}"` hides the count.
- `ready_window` - a click on the badge opens this tab of the project
  (default `git`: lazygit, where the tags are), then switches to it, so
  you see what the tags are; "" turns that off.
- `agent_format` `agent_format2` `agent_two_line` `agent_gap` (blank rows
  between agents, like `project_gap`) - fields: everything
  `session list --json` returns plus glyph idle idle_m runtime ctx window
  tab at. Naming recap/ctx costs a transcript read per seat.
- `agent_idle_orange` `agent_idle_blink` `agent_idle_red` - the `{idle_m}`
  field: an IDLE seat's whole minutes (`34m`), always four columns wide so
  the rows line up, and blank for a busy, waiting or blocked seat
  (`idle_s` is the time in the CURRENT state, so a seat busy for an hour
  has a large one too). A `shell` seat is idle: it is at its prompt while
  a background shell lives. Dim grey, then orange and bold from `agent_idle_orange` (45),
  red and bold from `agent_idle_red` (60), blinking from
  `agent_idle_blink`, which is 0, off, by default (55 starts the blink five
  minutes before red; it goes on blinking once red). All in minutes; 0 turns one off.
- `store_format` `mid_format` `agents_heading` `group_format` `collapse`
  - the fixed rows; `collapse` is "" (off) by default.
- `user_mail_command` `user_mail_socket` `user_mail_session`
  `user_mail_format` - the `✉ mail` row: YOUR own mail (your own mutt,
  separate from the projects' mail), under no store and no project,
  between the brand and the store row. A click runs `bin/sessionview-usermail`, which finds or
  creates ONE session (`mail`) on `user_mail_socket` (`default`, where
  `main` lives) with one `mail` window - a shell in `~` with the command
  typed in - and moves you there. The command is typed as is: no `-R`, no
  `-F`, your own rc, read-write; `neomutt` missing falls back to `mutt`;
  `""` (or neither on PATH) = no row. That session is hidden from the
  project rows while the row is drawn. An existing session is never
  changed, and a server that is not running is refused, never started.
- `group_by` (none|repo|project|session) `sort` `hide` `show_spaces`.
- `tab_glyphs` - write @sessionview_glyph per tmux window for the tab bar.
- **A light theme is not two keys.** Only `popup_bg` and `selected_fg` are
  configurable; the resting palette (`C_NAME` `#a6aec7`, `C_DIM` `#6c7185`,
  `C_DIMMER`, `C_BRANCH`) is code in `bin/tmux-sidebar`, tuned for a dark
  terminal, and pale text on a light background is unreadable. Until the
  palette is configurable, a light-terminal user gets the sidebar as
  shipped; there is no light default.
- `remotes` `remote_heading` `remote_refresh` - ssh hosts whose sessions
  and seats show under their own divider.
- `picker_order` (recent|alpha) - the new-session picker; tab flips it.
- `project_dirs` `project_dirs_depth` - directories that CONTAIN your
  checkouts. Every git repo found under them (up to `project_dirs_depth`
  levels) is offered by the new-session picker under its folder name, and
  is what that name opens. Merged with `tm project list`; tm wins a name
  collision. A path that does not exist is skipped in silence, so this is
  invisible to anyone who has not set it. Ships as `["~/workspace"]`, for
  someone with no task manager at all.
- `windows` - the standard tabs of a project session AND the new-tab
  picker's suggestions, one list.
  Each: `position` (sparse int), `name`, `when` (always | has_repo |
  has_projdir | has_mail | fallback - a named predicate, never an
  expression; has_mail = the project has a mailbox, `message path NAME`
  resolves one), `cwd`
  (root | repo | projdir - a named dir, never evaluated), `command`
  (optional, typed into the window; `{editor}` = VISUAL/EDITOR/nvim,
  `{readme}`, `{pmd}`, `{project}`), `focus` (the tab you land on, named
  not counted),
  `auto` (false = picker only; on a `fallback` entry true = opens with
  every session), `console` (true = a shell pane under the tab's own, in
  the same dir: one row until you select it, then 20% of the window, one
  row again when you select back; sized by hooks on that window only,
  nothing global; default false, the shipped `git` entry sets it).
  A project's `.sessionview` replaces the whole list, but never says what
  a tab runs: an entry's `command` comes only from layers 1-2, by name.
  `sessionview-config windows` prints it as TSV, pins applied.
- `store_windows` - the store view's tabs: the session the
  sidebar's store row opens, built by `sessionview-session NAME
  --store-view STORENAME --socket SOCK --store PATH`. The same fields as
  `windows`, its own list so a project's picker and pins never see a store
  entry; `sessionview-config windows --key store_windows` prints it. Store
  mode's own names: `when` has_store_project (the store project:
  `projects/store`, else `projects/<store>`, else none - no tasks tab, no
  error) | has_slipbox | has_scripts (the store root's `slipbox/`,
  `scripts/`) | has_store_mail (`message path <store>` resolves: the store
  box by the STORE's name, never the session's); `cwd` store | slipbox |
  scripts (projdir is the store project); `{store}` = the store's name,
  `{store_project}` = the store project's name. Ships tasks (a one-shot
  `tm task list`, never the live poller; you land on it), slipbox (the
  editor), scripts (a shell), messages (read-only), and a fallback shell.
  On an existing store session the tabs it lacks are ADDED; nothing is
  closed, renamed or reordered. Store mode never creates a session named
  `store` and never starts a down server (`tm store boot NAME` does).
- `neomuttrc` (a FILE beside this one, not a key) - how the `messages` tab
  shows a project's mail: threaded, oldest first, the root at the top.
  `bin/sessionview-messages` writes a
  per-folder rc that sources it, then `~/.sessionkit/view/settings/neomuttrc`
  if you have one - so yours overrides. neomutt runs `-R -F` there: read-only,
  and your `~/.muttrc` is never read.
- Errors go to ONE file: `~/.sessionkit/view/log/sessionview.log` - a failed
  tmux call (a new tab that never appeared), a `--window` that refused,
  an uncaught exception, each a line with time, socket, where, what.
  `tail -f` it when something silently does nothing.
- `log_level` - what that ONE file records: `error` (the default), `timing`
  (a line per click or key with its ms, and each command of 50 ms or more)
  or `debug` (every command, every mouse event). `$SESSIONVIEW_LOG_LEVEL`
  overrides it for one run.
- `window_pins` - your pins over that list, `{"name": true|false}`,
  written by ^p / right-click in the new-tab picker. A delta, so the list
  keeps flowing to you.
- `pinned_agents` - names held at the top, in this order: ONE list for
  two places. The start-an-agent picker lists them first, the rest of
  `session start --list-agents` after. The live
  agents list sorts a running agent whose name is pinned first, in pin
  order, whatever its project, status or idle; the rest keep the `sort`
  order. Grouped, the pinned rows sit above every group. `hide` and the
  current filter still apply first. Empty by default; `["alice", "bob"]`
  keeps alice and bob on top.
- `code_nvim` - sessionview-session starts nvim in the code window, listening on
  show-me's socket; off = a shell.
- `agent_command` - what "Start an agent" runs: an argv list, `{project}`
  `{agent}` `{dir}` `{socket}` filled in. Default:
  `["session", "start", "--tmux-target", "{project}", "--no-switch", "{agent}"]`;
  set `["tm", "kick", "{project}"]` when kick is ready. Read from layers
  1-2 only: a store's or project's value is ignored.
- `autostart_agent` - the agent sessionview starts when it opens. THREE
  states: `"ask"` (the shipped value - ask once on open, remember the
  answer), `""` (never), or a NAME (start it in its own window of the
  inner session). It is read for the session's own directory, so a
  project's `.sessionview` can name another agent, or `""` for none.
  Change the home choice with `^e` on an agent in the start-an-agent
  picker (`^e` again turns it off), or `sessionview-config set
  autostart_agent NAME`. Never takes the user's shell pane; never starts
  a second seat for an agent already running. `sessionview-autostart
  --status [SOCK SESSION]` says what it will do.
- `terminal` (iterm|ghostty|terminal, empty = work it out) - which terminal
  the Dreamcatcher dock app opens sessionview in. Empty falls back to a
  terminal already running, then iTerm, then Terminal - which is why a
  REBOOT (nothing running) lands on iTerm and not on what you use. Set it
  once and that stops. `bin/sessionview-terminal --why` says which rule
  answered.

## Editing it

`sessionview-config set KEY VALUE` / `unset KEY` write the **home layer
only** (`~/.sessionkit/view/settings/view.json`); stores and projects own the layers
below. A key that is not in the template is refused (`--force` overrides) —
that is what "no hidden defaults" buys. Values are typed by the template's
default: `true/false`, an integer, a JSON list, or a plain string.

The sidebar's **project menu > Settings** (`e`) is the same thing with a
screen: every key with its note, its default, and what it is now; `*` marks
what you have changed. `Config` (`c`) still opens the raw JSON in `$EDITOR`.
