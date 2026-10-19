# sessionview

A sidebar for tmux, in the spirit of herdr: your projects (tmux sessions)
and your agents (seats), here and on remote hosts, one click away, with a
right-click menu built from what is installed. Session's TUI — a
controller and view for the `session` tools, drawn beside tmux.

Install from PyPI: `uv tool install sessionview` (see [Install](#install)).

    sessionview [SESSION]            # in this terminal: sidebar left, SESSION attached
                                     # right (a private outer tmux holds the two panes)
    prefix H                         # the same sidebar as a popup in any tmux client

Read [SPEC.md](SPEC.md) first: what sessionview is, the rules of the view, the
contract with `session`, the plugin manifest, config, known limits.
This repo is the **reference implementation**: session integrates from
the spec; this stays comparable and runnable.

## Requirements

Each line is measured against the code, not remembered;
`bin/sessionview-install --check` checks tmux, Python, `session`,
neomutt and notmuch's index on your machine.

- **Claude Code, and the plugin is the install.** The `sessionview`
  wheel is an empty package (one `__init__.py`, no `[project.scripts]`);
  everything arrives through the Claude Code plugin (its `bin/` and
  `skills/`).
  From a clone: `claude plugin marketplace add <path-to-clone>`, then
  `claude plugin install sessionview@sessionview`.
- **macOS** for the dock app (`macos/SessionView.applescript`, built by
  `osacompile`) and the sidebar's copy action (`pbcopy`). The sidebar and
  the frame are plain tmux + Python and should run on Linux, untested.
- **tmux >= 3.7** (measured on 3.7c: `join-pane -l`, `focus-events`,
  status ranges). An older tmux satisfies `brew install tmux` silently.
- **Python 3.11 to 3.14**, standard library only (`requires-python` in
  `pyproject.toml` is `>=3.11,<3.15`; the sidebar and the config tools).
- **bash**: macOS's 3.2 is enough; sessionview's own bash tools use no
  bash-4 construct.
- **sessionmail** (`message` on PATH) for every mail action: the
  sidebar's mail, the agent pane menu, and the session, taskmaster and
  voicemode plugins (each lists `message` in its `requires`). Mail is
  sent as you: `$USER`, unless `sessionview-config set mail_from NAME`
  (or `$SESSIONVIEW_FROM`) names your mail name; `sessionview-from`
  prints the name in effect.
- **neomutt** for the `messages` tab (`bin/sessionview-messages` runs
  `neomutt -R`; the tab exits 2 without it): `brew install neomutt`, built
  with notmuch (Homebrew's is). Measured on NeoMutt 20260616. The tab's
  sidebar (the box, Asks, Asks · threads) also needs **notmuch** with the
  `Type` and `Project` headers indexed:
  `notmuch config set index.header.Type Type`,
  `notmuch config set index.header.Project Project`, then
  `notmuch reindex '*'`. Without the index the Asks rows are every mail to
  `NAME+ask`; without notmuch the sidebar is hidden and the tab still
  opens the one folder.
- **postfix: not needed by sessionview itself.** sessionview never talks
  to an MTA; sessionmail's `message send` hands each mail to
  `/usr/sbin/sendmail` (or `$SESSIONMAIL_SENDMAIL`) and refuses with
  "no MTA" when there is none, so mail needs an MTA that delivers into
  sessionmail's maildirs (postfix, for one; see sessionmail's README).
  Without one, everything but mail still works.
- optional: **`session`** on PATH for agents (`session list`,
  `session start`), from sessiontools: `uv tool install sessiontools`.
  Without it the sidebar still lists projects (tmux sessions), but shows
  no agent rows and no Start an agent, and so none of the agent menu's
  mail items (Message, Continue, Settle, ...: the session plugin
  `requires` `session`). `message` itself still works from a shell.
- optional: `tm` (taskmaster menu items) and the voicemode plugin, whose
  menu items appear only when installed; ssh with ControlMaster for
  remote hosts.

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
- *Consent on first open* — Dreamcatcher asks once which agent to start
  when it opens (a numbered pick, or never), and remembers.

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
`~/.local/state/sessionview` (`SESSIONVIEW_STATE`). Requirements are listed above.

## Install

From PyPI:

    uv tool install sessionview
    sessionview install            # checks every requirement; links nothing

That puts `sessionview`, `sessionview-config`, `sessionview-session` and
`sessionview-messages` on PATH; `sessionview install` then only checks.

From a checkout:

    git clone https://github.com/sessionkit/sessionview ~/Code/sessionview
    ~/Code/sessionview/bin/sessionview-install     # or: make install

That links the tools into `~/.local/bin` and checks every requirement,
saying PASS / WARN / MISSING with the fix for each (tmux below 3.7 is
the one that bites: an older tmux satisfies `brew install tmux`
silently). It installs nothing else and never edits your shell config.
`sessionview-install --check` reports without changing anything. Then,
in a new terminal: `sessionview`.

show-me (github.com/mbailey/show-me) is referenced, not bundled.

### Dock app (macOS, optional)

    sessionview install --app   # or: make app

Builds `SessionView.app` from `macos/SessionView.applescript` and puts
it in `~/Applications`; drag it to the Dock and one click opens
sessionview in your preferred terminal (see Terminals above). It is a
front door, not the product -- `sessionview` in any shell does the same
job.

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
  `SESSIONVIEW_FROM` (the name mail is sent as), `SESSIONVIEW_STATE`
  (state, default `~/.local/state/sessionview`), `SESSIONVIEW_PLUGINS`
  (another plugin directory).
- sessionview does not read the kit's settings cascade today, only these.

Every file, variable and tmux option is in
[Configuration](docs/configuration.md),
and every key in
[Settings](docs/settings.md).

## Logs

- `~/.local/state/sessionview/sessionview.log`: what went wrong, one
  entry each, starting with the time (a failed tmux call, an uncaught
  error with its traceback). Follow it with
  `tail -f ~/.local/state/sessionview/sessionview.log` when a click
  seems to do nothing.
- `~/.local/state/sessionview/sidebar-mouse.log`: one line per mouse
  click the sidebar receives.
- Both sit under `$SESSIONVIEW_STATE` when it is set. Neither is rotated.
- **Health:** `sessionview install --check`: exit 0 and `ready` when
  every requirement is present, exit 1 with each MISSING one named
  otherwise. It checks the machine, not a running sidebar.
