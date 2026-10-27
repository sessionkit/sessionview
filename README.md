# sessionview

A sidebar for tmux, in the spirit of herdr: your projects (tmux sessions)
and your agents (seats), here and on remote hosts, one click away, with a
right-click menu built from what is installed. Session's TUI — a
controller and view for the `session` tools, drawn beside tmux.

Install from PyPI: `uv tool install sessionview` (see [Install](#install)).

    sessionview

In this terminal, that puts the sidebar on the left and a tmux session
on the right; a private outer tmux holds the two panes. The session is
one tmux already has: your default assistant's, else the one you last
attached, else the newest. Only when tmux has no session at all does
sessionview make one, named `main`.
`sessionview NAME` attaches the session NAME instead, which must exist.
In any tmux client, `prefix H` opens the same sidebar as a popup.
Every verb, its form and an example: [the sessionview command](docs/sessionview.md).

Read [SPEC.md](SPEC.md) first: what sessionview is, the rules of the view, the
contract with `session`, the plugin manifest, config, known limits.
This repo is the **reference implementation**: session integrates from
the spec; this stays comparable and runnable.

## Requirements

- [x] macOS (tested on macOS 27, Apple silicon)
- [ ] Linux
- [ ] WSL
- [ ] Windows

The direct dependencies and the tools a user meets, what needs each one,
and how to upgrade it: [dependencies](docs/dependencies.md).

## Features

Grouped by component, named in the terms a comparison matrix would use.

**Sidebar** — projects (tmux sessions) above, agents (seats) below.

- *Collapsible* — the `◧` glyph at the far left of the tab bar hides it
  and shows it again; it keeps running, nothing restarts, and it comes
  back at the width it had.
- *Resizable* — drag the border. The width you drag to is remembered
  for the next open.
- *Auto-sizing* (`fit: auto`) — fits its contents: the widest row plus
  one, between `width_min` and `width_max`. Grows at once, gives width
  back after a few quiet redraws. Chrome never changes the width; only
  your content does. A drag switches back to a fixed width.
- *Remote hosts* — sessions and agents on other machines, over an ssh
  control master you already hold. The sidebar never opens a connection
  of its own, so a hardware key is never asked for a touch by a redraw.

### Menus

- *Overflow menu* — three dots `⋯` at the right of the selected session
  open its menu (rename, new tab, config, settings, start an agent,
  close). Right-click opens the same menu on any row.
- *Light dismiss* — a click outside an open menu closes it, and so does
  a click into the main pane (focus leaves the sidebar).
- *Keyboard* — ↑↓ / j k move, the letter or enter picks, esc closes.

**Tabbed windows** — the tab bar on top: one tab per tmux window, the
name once the window is named, the number until then; click to select,
drag to reorder, `+` for a new tab, `×` to close (with a confirm). New
tab - the `+`, or the session menu - is a picker: the session's standard
windows (`windows` in config: repo, git, project, tasks, editor, shell)
listed, typing narrows, enter opens the highlighted one or a plain tab
of the name you typed. The same picker starts an agent (the `+` under
agents, or the menu): the names `session start` knows, pinned ones first.

### Agents

- *Start an agent* — `+` under the agents list, or *Start an agent* on a
  project's menu. The list you pick from is the launcher's own
  (`session start --list-agents`), so it cannot offer a name that will
  not start. An agent already running is never started twice.
- *Agents have a home* — an agent's own file says where it wakes
  (`start: directory:`); a project's menu starts it in the project.
- *Consent on first open* — the first time it opens, sessionview asks
  which agent to start whenever it opens, and remembers the answer. It
  says *sessionview can start an agent for you each time it opens*, lists
  your agents by number and asks `Which? (number, name, or "n")`. When it cannot get the
  list it asks `Which agent? (a name, or "no" to never ask again)`. `n` or
  `no` means never; `autostart_agent` in Settings changes it later.

**Settings** — every setting, its default, its note and where its value
comes from, in a small screen (project menu → Settings); the rows come
from the template, so a new key needs no second edit.

**Your terminal** — the dock app opens sessionview in the terminal you
use (`terminal` in config: iterm, ghostty or terminal), not whichever
happened to be running.

**Standard tmux** — the frame is an outer tmux holding two panes; every
view is a tmux session, window or pane. No daemon, no GUI toolkit, no
tmux fork or plugin manager.

## Terminals

Tested: Terminal.app, iTerm2, Ghostty (macOS). The sidebar needs mouse
reporting and focus reporting from the terminal; anything that gives
tmux those should work, but only the three above have been driven by
hand. Blink Shell on iPad is wanted and not yet connecting.

## Layout

    bin/tmux-sidebar     the view, the clicks, the menus (Python 3.11+, stdlib)
    bin/sessionview             the front door (the frame) + the sidebar supervisor
    bin/sessionview-frame       the frame: outer tmux, sidebar pane + client pane
    bin/sessionview-session     a project session with its configured tabs (repo / git / project / tasks)
    bin/sessionview-newtab      the tab bar's "+": the new-tab picker, in a popup
    bin/sessionview-config      settings: no verb opens the screen; list / get / set / unset / dump / path
    bin/sessionview-autostart   the consent-on-open question; --start NAME is the + under agents
    bin/sessionview-sidebar-toggle  hide / show the sidebar (the ◧ glyph)
    bin/sessionview-terminal    which terminal the dock app opens
    tmux/frame.conf       the sessionview look, session-scoped (sourced with S= and SESSIONVIEW_ROOT=)
    tmux/tabs-top.conf   the same look, global and OPTIONAL (source-file it from ~/.tmux.conf
                         to have it outside sessionview too; the frame applies frame.conf itself)
    config/config.json   every default, explicit; ~/.sessionkit/view/settings/view.json is made from it
    plugins/*/           plugin.toml (+ scripts): session, voicemode, taskmaster
    .claude-plugin/      sessionview is a Claude Code plugin; its skills load as
    skills/*/SKILL.md    sessionview:NAME - sessionview, tmux, lazygit, neovim,
                         claude-code: short, safe driving skills with tools

Paths resolve from the checkout (`SESSIONVIEW_ROOT`); state lives in
`~/.sessionkit/view/state` (`SESSIONVIEW_STATE`) and the log in
`~/.sessionkit/view/log` (`SESSIONVIEW_LOG`). Its direct dependencies:
[dependencies](docs/dependencies.md).

## Install

From PyPI:

    uv tool install sessionview
    sessionview install

That puts `sessionview`, `sessionview-config`, `sessionview-session` and
`sessionview-messages` on PATH; `sessionview install` then checks every
requirement and links nothing.

From a checkout:

    git clone https://github.com/sessionkit/sessionview ~/Code/sessionview
    ~/Code/sessionview/bin/sessionview-install

That links the tools into `~/.local/bin` (`make install` in the checkout
does the same) and checks every requirement,
saying PASS / WARN / MISSING with the fix for each (tmux below 3.7 is
the one that bites: an older tmux satisfies `brew install tmux`
silently). It installs nothing else and never edits your shell config.
`sessionview-install --check` reports without changing anything. Then,
in a new terminal: `sessionview`.

The installer never moves links that already run another checkout (a
second clone, a git worktree, or `uv tool install`'s commands): it lists
them, changes nothing and exits 3. `--check` lists the same links as
WARN lines. Run `bin/sessionview-install --relink` from the checkout you
want to run, or set `PREFIX=DIR` to install somewhere else. A bare `make`
only lists the targets; installing is always `make install`.

The Claude Code plugin brings sessionview's skills. From a clone:
`claude plugin marketplace add <path-to-clone>`, then
`claude plugin install sessionview@sessionview`.

show-me (github.com/mbailey/show-me) is referenced, not bundled.

### Dock app (macOS, optional)

    sessionview install --app

That builds `SessionView.app` from `macos/SessionView.applescript` and
puts it in `~/Applications` (`make app` in a checkout does the same);
drag it to the Dock and one click opens sessionview in your preferred
terminal (see Terminals above). It is a front door, not the product --
`sessionview` in any shell does the same job.

On a cold click the app reuses the window Terminal opens for itself at
launch, rather than adding a second one. If your Terminal profile runs a
command of its own (Settings > Profiles > Shell > Run command) that
window is busy, so the app opens its own and you get two.

Full screen on click is off by default; turn it on with

    sessionview-config set fullscreen true

On Terminal.app that needs Accessibility permission for SessionView
(System Settings > Privacy & Security > Accessibility) -- the app asks
in a dialog the first time rather than failing quietly. iTerm and
Ghostty need no permission.

Rebuilding the app (`make app`) gives it a fresh ad-hoc signature, which
macOS treats as a different app -- so the Accessibility permission has to
be granted again after every rebuild. A stable signing identity would fix
that; the app does not have one yet.

## What an install changes

`uv tool install sessionview` changes two places and fills uv's own
cache, and it touches no shell startup file and nothing in `~/.claude`.
`sessionview install` after it checks the requirements and changes
nothing. Everything else below appears only when you run the verb named
beside it. Each line says what puts it there and what takes it away.

- **PATH:** `~/.local/bin/sessionview`, `sessionview-config`,
  `sessionview-session` and `sessionview-messages`, or in
  `UV_TOOL_BIN_DIR` when that is set. uv says so if the folder is not on
  your PATH, and edits no shell file. `uv tool uninstall` removes them.
  From a checkout instead, `bin/sessionview-install` (or `make install`)
  links the checkout's `bin/sessionview*` tools and `tmux-sidebar` into
  `~/.local/bin`, or into `PREFIX/bin` when `PREFIX` is set, and makes
  nothing else. [Uninstall](#uninstall) has the line that deletes them.
- **The program:** `~/.local/share/uv/tools/sessionview/`, its own
  Python environment, or in `UV_TOOL_DIR`. sessionview has no Python
  dependencies: the environment holds sessionview and the files it ships
  (its tools, the tmux confs, the sidebar's plugins and the Dock app's
  source). `uv tool uninstall` removes it. If uv finds no Python 3.11 or
  newer, it downloads one into its own folder (`uv python dir`,
  `~/.local/share/uv/python/` by default). `uv tool uninstall` leaves
  that Python; `uv python uninstall` removes it.
- **uv's cache:** the install fills it with what it downloaded and
  built. It is uv's, shared by everything uv installs, not sessionview's.
  `uv cache dir` prints where it is (`~/.cache/uv` by default, or
  `UV_CACHE_DIR`). `uv tool uninstall` leaves it; `uv cache clean
  sessionview` drops this package's entries, and `uv cache prune` drops
  the ones nothing uses.
- **Folders, each made by a verb you run:**
  - `~/.sessionkit/view/state/`: the state folder, mode 0700, made the
    first time `sessionview` opens (or `sessionview session` or
    `sessionview messages` runs). `SESSIONVIEW_STATE` names another
    folder instead. Each file sessionview makes in it is private (mode
    0600). In it:
    - `frame-PID.tty`, one while each frame is open. The frame deletes
      it when it closes; a frame killed outright can leave it behind.
    - `recent.tsv`, a line each time `sessionview session` opens a
      project, for the picker's order.
    - `picker-order`, when you flip the picker's sort.
    - `sidebar-mail.txt`, the last message typed at the sidebar's
      message prompt.
    - `plugin-PLUGIN-ACTION.txt`, the text a plugin's menu item last
      sent (the session plugin's Message or Continue, say), one for
      each item you have used.
    - `sidebar-remote-HOST.json`, what the sidebar last saw from each
      host in your `remotes` setting.
    - `mutt/`, an rc file for each box `sessionview messages` opens.
  - `~/.sessionkit/view/log/`: the log folder, mode 0700, made at the
    same time. It holds `sessionview.log` ([Logs](#logs)).
    `SESSIONVIEW_LOG` names another log file. When `SESSIONVIEW_STATE`
    is set, the log is `sessionview.log` in that folder instead.
  - `~/.local/state/sessionview/`: the state folder of releases before
    this one. Nothing new is made there. On an upgrade, the first start
    hard-links `recent.tsv`, `picker-order`, `sidebar-mail.txt` and each
    file in `mutt/` into the new state folder. The old names are kept,
    so the two names are one file, and a sidebar still running from
    before the upgrade stays correct. The old folder is left in place,
    with the old `sessionview.log`, `sidebar-mouse.log`, the frame pins
    and the plugin and remote files, which are not carried over. One
    line is added to the end of the old log, naming the new one. Each
    start sets the old folder to mode 0700, so the old names are private
    too; the files in it keep their modes. An
    older release's `~/.local/state/herd/` is renamed to this folder
    first, when only the herd one exists.
  - `~/Applications/SessionView.app`: `sessionview install --app` (or
    `make app` in a checkout), or in `DEST` when that is set. It is
    built in a temporary folder that is deleted after, and a rebuild
    replaces it.
- **Services (launchd agents):** none. sessionview runs no daemon and
  writes nothing in `~/Library/LaunchAgents/`. While a frame is open it
  runs a tmux server of its own, `sessionview-frame`, beside yours; the
  server exits when the last frame closes.
- **Plugin and skills, optional:** `claude plugin marketplace add` and
  `claude plugin install` ([Install](#install)). Claude Code names the
  marketplace and the plugin in `~/.claude/settings.json`
  (`extraKnownMarketplaces`, `enabledPlugins`), lists them in
  `~/.claude/plugins/`, and keeps a copy in
  `~/.claude/plugins/cache/sessionview/`. The plugin brings five skills
  (`sessionview`, `tmux`, `lazygit`, `neovim`, `claude-code`) and no
  hooks. Uninstalling the plugin takes it out of the settings and leaves
  the cached copy.
  The sidebar's own plugins (`plugins/`: session, taskmaster, voicemode)
  ship inside the program and install nothing. `SESSIONVIEW_PLUGINS`
  names a folder of your own.
- **Settings:** the install writes none.
  `~/.sessionkit/view/settings/view.json` is made from the shipped
  template the first time anything reads your settings: `sessionview`,
  or a `sessionview-config` verb such as `get` (`path` only prints it).
  `sessionview-config set` writes it. `SESSIONVIEW_CONFIG` names another
  file instead. `~/.sessionkit/view/settings/neomuttrc` is there only if
  you write it.
- **Your tmux server, while it runs:** a frame binds keys on the tmux
  server it attaches to: `prefix H` (the sidebar as a popup) and three
  mouse bindings on the status line (`MouseDown1Status`,
  `MouseDown1StatusRight`, `MouseDrag1Status`). It gives each session it
  opens the sessionview look, with options set on that session only.
  With `pane_menu` on, it also binds a right-click in a pane
  (`MouseDown3Pane`), in place of yours, and sets two global
  `@sessionview_agent_menu_` options. Nothing is written to
  `~/.tmux.conf`: these last until that tmux server exits.
- **Outside these folders, only on a verb:** with `fullscreen` on, the
  Dock app on Terminal.app needs the Accessibility permission you grant
  in System Settings, and macOS keeps it there until you turn it off.
  *Start an agent* runs `session start`, and a message from the menu is
  sent with `message`: what those make is in sessiontools' and
  sessionmail's own lists. The `editor` tab, when it runs neovim,
  listens on a socket in `$TMPDIR` while it runs. With no `TMPDIR`, the
  socket goes in `XDG_RUNTIME_DIR`, or in `~/.local/run`, which is made
  then and stays.

## Uninstall

Close every sessionview frame first. Then remove the plugin, if you
installed it, and the command. Skip the lines for what you never
installed:

```console
claude plugin uninstall sessionview@sessionview
claude plugin marketplace remove sessionview
uv tool uninstall sessionview
```

Installed from a checkout instead, delete the links it made, and the
checkout if you want it gone:

```console
rm ~/.local/bin/sessionview ~/.local/bin/sessionview-* ~/.local/bin/tmux-sidebar
```

That leaves what the verbs made, listed above. The Dock app, the
plugin's cached copy, and the state and log folders are sessionview's
alone. To delete them:

```bash
rm -rf "${HOME:?}/Applications/SessionView.app"
rm -rf "${HOME:?}/.claude/plugins/cache/sessionview"
rm -rf "${HOME:?}/.sessionkit/view/state" "${HOME:?}/.sessionkit/view/log"
rm -rf "${HOME:?}/.local/state/sessionview"
```

The last line is for an upgrade from an earlier release: it removes the
old state folder, with the old log in it.

uv's cache stays too, with the other things uv installed; `uv cache
clean sessionview` drops this package's entries. The key bindings go
when your tmux server next exits.

The rest is your data: delete it by hand only if you want it gone.
`~/.sessionkit/view/settings/` holds your settings, and the kit's other packages
keep theirs beside it in `~/.sessionkit/`.

## Keys and clicks

- sidebar: click a project or seat → go there; right-click, or the `⋯`
  on the selected project → its menu; `+` between the lists → a session
  picker (type to filter, ↑↓, enter); `+` at the bottom → start an
  agent; the store name → that store's session and store view, its `⋯`
  (or `s`) → Switch store, right-click → Kick; `all · grouped` on the agents
  heading are toggles; drag the border to resize; `q` reloads, `Q`
  quits, esc backs out of any view
- tab bar: `◧` at the far left hides/shows the sidebar; click selects,
  drag reorders, `+` new tab (the picker); a close `×`, on by default;
  `tmux set -g @sessionview_tab_close 0` turns it off
- menu: ↑↓ / j k move, the letter or enter picks, esc or a click
  anywhere else closes
- agent panes (opt-in): right-click an agent's pane for Speak, Continue,
  Read Clipboard, Park or Succeed; each mails that agent. Turn it on
  with `sessionview-config set pane_menu true`. It replaces your own tmux right-click menu, which is
  why it is off by default. Using tmux without session view? Add
  `source-file -q /path/to/sessionview/tmux/agent-menu.conf` to
  `~/.tmux.conf` and reload.

The look follows herdr's; its colours were matched from herdr's own window.

## Configuration

- **Settings:** JSON, in layers, a later one winning. The template
  `config/config.json` holds every key and its default.
  `~/.sessionkit/view/settings/view.json` is yours, made from it on first
  use; a store's and a project's `.sessionview` come after it.
  `sessionview-config set KEY VALUE` writes yours, and
  `sessionview-config dump --where` names the file behind each key.
  An older install's settings are never read. Moving them is one step,
  in [Upgrading from 0.1.0](docs/configuration.md#upgrading-from-010).
  Until then sessionview makes nothing and refuses: `sessionview-config`
  exits 3 and prints the move to run, and the sidebar shows the same
  message. If the old file is left beside the new one, it uses the new one
  and warns you to remove the old one.
- **Your neomutt view:** `~/.sessionkit/view/settings/neomuttrc`,
  optional, read after the shipped `config/neomuttrc`.
- **Plugins:** `plugins/<name>/plugin.toml` in the checkout.
- **Environment:** `SESSIONVIEW_CONFIG` (another file for yours),
  `SESSIONVIEW_FROM` (the name mail is sent as, else `mail_from`, else
  `$USER`; `sessionview from` prints the name in effect), `SESSIONVIEW_STATE`
  (state, default `~/.sessionkit/view/state`), `SESSIONVIEW_LOG` (the log
  file, default `~/.sessionkit/view/log/sessionview.log`),
  `SESSIONVIEW_PLUGINS` (another plugin directory).
- sessionview does not read the kit's settings cascade today, only these.

Every file, variable and tmux option is in
[Configuration](docs/configuration.md),
and every key in
[Settings](docs/settings.md).

## Logs

- `~/.sessionkit/view/log/sessionview.log`: what went wrong, one
  entry each, starting with the time (a failed tmux call, an uncaught
  error with its traceback). Follow it with
  `tail -f ~/.sessionkit/view/log/sessionview.log` when a click
  seems to do nothing.
- **After an upgrade:** the log of earlier releases,
  `~/.local/state/sessionview/sessionview.log`, stays where it is and
  is never moved. Its last line names the new log, and the new log's
  first line names the old one.
- **Levels:** `log_level` in your settings (or `$SESSIONVIEW_LOG_LEVEL`
  for one run). `error`, the default, logs only what went wrong.
  `timing` adds a line per click or key with its milliseconds, and each
  command that took 50 ms or more, so a slow click names its slow part.
  `debug` adds every command and every mouse event (what the old
  `sidebar-mouse.log` held).
- `$SESSIONVIEW_LOG` names another log file. Without it, a
  `$SESSIONVIEW_STATE` that names another folder keeps the log there, as
  `sessionview.log`. It is not rotated: turn `timing` or `debug` on
  while you look, then back to `error`.
- **Health:** `sessionview install --check`: exit 0 and `ready` when
  every requirement is present, exit 1 with each MISSING one named
  otherwise. It checks the machine, not a running sidebar.
