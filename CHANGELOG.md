# Changelog

<!-- markdownlint-configure-file {"MD024": {"siblings_only": true}} -->

All notable changes to sessionview are documented here. The format is
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Install as a package: `uv tool install sessionview`. The wheel carries
  the whole tool and declares Python 3.11 to 3.14; its commands run on that
  Python, whatever `python3` comes first on PATH.
- One front door: `sessionview config|session|messages|install|autostart|
  terminal|usermail` runs that tool, so a user needs one name.
- `sessionview install --app` builds and installs the macOS Dock app.
- Autostart per project: a project's `.sessionview` can name its own agent,
  or `""` for none. In the start-an-agent picker, `^e` makes an agent the
  home choice; `^e` on the same agent turns autostart off.
- The messages tab has a sidebar beside the mail: your box with every message
  threaded, **Asks** (one line per ask for the project), and **Asks · threads**
  (each ask with its replies under it, so you can see whether it is being
  worked on). Ctrl-n and Ctrl-p move between rows, Ctrl-o opens one, and B
  hides or shows the sidebar. The Asks rows need notmuch with the `Type` and
  `Project` headers indexed; without notmuch the sidebar is hidden and the tab
  opens the one folder, as before.
- `sessionview-install --check` now checks for neomutt (reported as missing
  when absent, a warning when it is built without notmuch) and for notmuch
  indexing `Type` and `Project`.
- The README Requirements section names neomutt as a dependency of the
  messages tab, and notmuch for its sidebar, with the commands that index the
  two headers.
- `sessionview-from` prints the name your mail is sent as. Set it with
  `sessionview-config set mail_from NAME` or `$SESSIONVIEW_FROM`.

### Changed

- Your settings moved to `~/.sessionkit/view/settings/view.json`, with your
  neomutt override `neomuttrc` beside it; the old settings folder is no longer
  read. Move them once by hand, as "Upgrading from 0.1.0" in
  `docs/configuration.md` says: the old `config.json` to `view.json`, any
  `config.json.before-*` backups and a `neomuttrc` beside it, check that
  `sessionview-config get width --where` names the new file, then remove the
  empty old folder. Until then `sessionview-config` refuses (exit 3) and
  prints the move; a leftover beside the new file is warned about.
- Version 0.2.0. Author is Mike Bailey <mike@sessionkit.ai>. Project URLs
  (homepage, repository) point at <https://github.com/sessionkit/sessionview>.
  Development Status is now 3 - Alpha.
- The PyPI summary is now "A sidebar for tmux: your projects (sessions) and
  your agents, here and on remote hosts." It no longer says the name is
  reserved.
- Renamed from herd to sessionview throughout: `HERD_*` environment
  variables are now `SESSIONVIEW_*`, tmux options `@herd_*` are
  `@sessionview_*`, and `tmux/herd.conf` is `tmux/frame.conf`. The state
  dir moves once, on first run, from `~/.local/state/herd` to
  `~/.local/state/sessionview`.
- One settings command: `sessionview-config` opens the settings screen,
  and `sessionview-config list` prints its rows. `sessionview-configure` is
  gone; re-run `sessionview-install` to drop an old link to it.
- The ready badge is the egg by default, on every fresh install.
- The sidebar's `?` key reads its key list from `config/keys.md`.
- The messages tab lists the newest thread first, and the newest reply first
  within a thread, in your box and in both Asks rows. It was oldest first.
- The ready badge counts unmerged ready tags against the remote's default
  branch (`origin/<default>`) first, and falls back to the local one only when
  there is no remote-tracking branch. It also counts `egg/` tags; a branch
  tagged under both prefixes counts once.
- The sidebar asks only the tmux servers your agent sessions name, instead of
  probing every socket file in the tmux directory on each refresh. Picking a
  store and closing its menu is much faster on a machine with many leftover
  sockets. This needs `session` 2.1.273 or newer; with an older `session`, an
  agent on another tmux server is still listed but loses its click-to-follow.
- `pane_menu_from` is now the older name for `mail_from`. It is still honoured
  when `mail_from` is empty.
- Doc links are relative; a link to another kit repository names HEAD.

### Removed

- `config/sidebar.toml`, which nothing read.

### Fixed

- The sidebar no longer crashes at start on a Mac whose first `python3` is
  Apple's 3.9. It finds a Python 3.11+, or says what to install.
- The Dock app finds `sessionview` through the user's own login shell, so
  it works on a stock Mac (zsh), not only under bash.
- A project's code window opens Neovim on a second tmux server too. Its
  socket name now carries the server as well as the pane, as show-me's
  does, so two servers' same-numbered panes no longer collide ("address
  already in use"). The neovim skill's `nvim-sock` finds it by that name.

- Mail sent from the sidebar, the plugin actions, voicemode speak and the agent
  pane menu was sent as a fixed name. It is now sent as you: `$SESSIONVIEW_FROM`,
  then `mail_from` in your config, then `$USER`. If your login name is not your
  mail name, set `mail_from` (or `$SESSIONVIEW_FROM`) before updating, or your
  mail will go out as your login name.
- The macOS launcher no longer falls back to a hard-wired personal checkout
  path; it looks on your PATH and in `~/Code/sessionview` and `~/sessionview`.
  Rebuild the Dock app with `sessionview-app-install` to pick this up.
- `uv run` no longer rewrites `uv.lock` and leaves the working tree dirty; the
  lock file is committed and names the right version.

### Security

- A `.sessionview` file found in a store or in a project directory is now
  untrusted for anything that executes. Its `agent_command`, and the `command`
  of each `windows` and `store_windows` entry, are ignored and named once on
  stderr. A window entry from such a file keeps its other settings; it runs the
  command of the same-named window from your own config, or none, so the tab
  is a plain shell. Only the shipped template and your own
  `~/.sessionview/config.json` can set what runs. A tab name, `when` or `cwd`
  containing tabs or line breaks can no longer shift text into the command
  column.

## [0.1.0] - 2026-10-10

### Added

- First public alpha, released with the Session Kit family.
