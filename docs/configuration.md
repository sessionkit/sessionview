# Configuration

sessionview is configured by JSON files, a few environment variables and a
few tmux options. Each section below is one part of sessionview, with the
files and variables that set it and where each one lives.

- [Settings][settings]: the JSON keys, in four layers. Most of what you
  change lives here, in `~/.sessionkit/view/settings/view.json`.
- [Mail sender](#mail-sender): the name sessionview's mail is sent as.
- [The messages tab](#the-messages-tab): how neomutt shows a project's mail.
- [Plugins](#plugins): the right-click menu's actions.
- [Project sessions](#project-sessions): the tabs a project session opens.
- [tmux](#tmux): the look, the tab bar and the agent pane menu.
- [Paths](#paths): the checkout, the state directory and Python.
- [The kit's settings](#the-kits-settings): not read by sessionview today.
- [Upgrading from 0.1.0](#upgrading-from-010): moving your settings to
  the new home, once.

`<checkout>` below is your clone, or the package's data directory for an
install from PyPI. `sessionview-config dump --where` prints every key, its
value and the file that set it.

## [Settings][settings]

One cascade of JSON objects. A later layer wins.

1. `<checkout>/config/config.json`: the template, with every key and its
   default.
2. `~/.sessionkit/view/settings/view.json`: yours, made from the template
   the first time anything reads the config.
3. `<store>/.sessionview`: a JSON file, or a directory holding
   `config.json`.
4. `.sessionview`, walked up from a project's directory: the top one
   first, the project's own last, so the nearest wins.

- **Layers 3 and 4 are untrusted**, because a cloned repo can carry one.
  They never set a key that runs something. Each key they drop is named on
  stderr with its file.
- **`sessionview-config set KEY VALUE`** writes layer 2 only.
  `sessionview-config unset KEY` takes a key back to its default.
- **`SESSIONVIEW_CONFIG=<file>`** puts layer 2 somewhere else.
  `SIDEBAR_CONFIG` is the old name and still works.
- **An older install's settings are never read.** While they are still
  there, sessionview refuses or warns: see [Upgrading from
  0.1.0](#upgrading-from-010).
- **`SIDEBAR_WIDTH` and `SIDEBAR_REFRESH`**, when set, win over the
  `width` and `refresh` keys in the sidebar.

Every key, its type, its default and what it does: the [settings
page][settings].

## Mail sender

sessionview's mail (the sidebar's Message, the plugin actions that mail,
the agent pane menu) is sent as the person at the keyboard. The first of
these that is not empty wins:

1. `$SESSIONVIEW_FROM`
2. `$SESSIONVIEW_MENU_FROM`, the older name
3. the `mail_from` key
4. the `pane_menu_from` key, the older name
5. `$USER`
6. the word `sessionview`

`<checkout>/bin/sessionview-from` prints the name in effect. Set yours with
`sessionview-config set mail_from <you>`.

## The messages tab

The `messages` tab shows a project's mail in neomutt, read-only.

- `<checkout>/config/neomuttrc`: the shipped view (threaded, oldest
  first).
- `~/.sessionkit/view/settings/neomuttrc`: yours, read after the shipped
  one, so it wins. Optional.
- `~/.local/state/sessionview/mutt/`: the per-folder files sessionview
  writes for neomutt. Not for editing.
- neomutt runs with `-R -F`, so `~/.muttrc` is never read for this tab.
- The tab's sidebar needs notmuch to index two headers:
  `notmuch config set index.header.Type Type` and
  `notmuch config set index.header.Project Project`, then
  `notmuch reindex '*'`.

Your own mail client, the sidebar's mail row, is set by the
`user_mail_*` keys on the [settings page][settings].

## Plugins

The right-click menu is built from plugin manifests.

- `<checkout>/plugins/<name>/plugin.toml`: one manifest per plugin; the
  shipped ones are session, taskmaster and voicemode.
- `SESSIONVIEW_PLUGINS=<dir>`: read plugins from another directory.
- `SESSIONVIEW_DRY_RUN=1`: Start an agent prints what it would run and
  starts nothing.
- What Start an agent runs is the `agent_command` key.

The manifest format is section 5 of the spec, `SPEC.md` in the
repository.

## Project sessions

`sessionview-session` builds a project's tmux session with its tabs.

- The tabs come from the `windows` key; the store view's from
  `store_windows`. Your pins are `window_pins`.
- `SESSIONVIEW_PROFILE=0`, or `--plain`: one shell window instead of the
  configured tabs.
- `SESSIONVIEW_CODE_NVIM=1`, or `--nvim`: open the `editor` tab when the
  session opens, as the `code_nvim` key does.
- `SESSIONVIEW_SOCK=<name>`: the tmux server to build on, as `--socket`
  does.

## tmux

- `<checkout>/tmux/frame.conf`: the sessionview look, applied by the
  frame to its own sessions only.
- `<checkout>/tmux/tabs-top.conf`: the same look for every tmux session.
  Optional: `source-file` it from `~/.tmux.conf`.
- `<checkout>/tmux/agent-menu.conf`: the agent pane menu. The frame loads
  it when the `pane_menu` key is `true`; without the frame,
  `source-file -q` it from `~/.tmux.conf`.
- `tmux set -g @sessionview_tab_close 0`: no close `×` on the tabs.

## Paths

- `SESSIONVIEW_ROOT`: the checkout. Worked out from where the command
  lives; an install from PyPI sets it to the package's data directory.
- `SESSIONVIEW_STATE`: the state directory, default
  `~/.local/state/sessionview`. It holds recent projects, the picker
  order and the logs (see the README's Logs section).
- `SESSIONVIEW_PYTHON`: the Python 3.11 or newer to use. When unset: the
  venv a package was installed into, if any, then PATH (newest first).

## The kit's settings

sessionview does **not** read the kit's settings cascade today. It reads
only its own layers, above. Its own home file does live in the kit's home,
in sessionview's folder there: `~/.sessionkit/view/settings/`. The kit's
guide is [sessionkit's docs/settings.md][kit-settings].

## Upgrading from 0.1.0

Up to 0.1.0 your settings lived in their own folder in your home
directory: `config.json`, any `config.json.before-*` backups and an
optional `neomuttrc`. Now they live in `~/.sessionkit/view/settings/`, as
`view.json` and `neomuttrc`, and the old folder is never read. Move them
once, by hand. The first line below names both folders:

```sh
old=~/.sessionview new=~/.sessionkit/view/settings
test ! -e "$new/view.json" && mkdir -p "$new" &&
mv "$old/config.json" "$new/view.json" &&
find "$old" -maxdepth 1 \( -name 'config.json.before-*' -o -name neomuttrc \) -exec mv {} "$new/" ';' &&
find "$old" -maxdepth 0 -empty -delete
sessionview-config get width --where
```

The last line checks the move: it must name `view.json`. The `find` lines
move the backups and `neomuttrc` only if they are there, and remove the
old folder only once it is empty, so no step fails on a file left behind.
Anything else you kept in the old folder stays where it is: move it, then
remove the folder.

- **Not moved yet.** While the old `config.json` is there and `view.json`
  is not, sessionview reads nothing and makes nothing.
  `sessionview-config` exits 3, names both paths and prints this move with
  your paths filled in. The sidebar shows the same message as a note and
  runs on the template.
- **Both there.** If `view.json` and the old `config.json` are both there,
  the new one is used, and a warning names the old one once, on stderr and
  in the sidebar's note. Remove the old folder: a walk-up for
  `.sessionview` from a project under your home directory finds it and
  reads its `config.json` as an untrusted project layer. Do not run the
  move then: its first step stops it, so the old file never overwrites
  `view.json`.
- Neither check opens the old file, and neither applies when
  `SESSIONVIEW_CONFIG` (or `SIDEBAR_CONFIG`) names your file.

[settings]: settings.md
[kit-settings]: https://github.com/sessionkit/sessionkit/blob/HEAD/docs/settings.md
