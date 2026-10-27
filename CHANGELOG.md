# Changelog

<!-- markdownlint-configure-file {"MD024": {"siblings_only": true}} -->

All notable changes to sessionview are documented here. The format is
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changes since the last release are in `changelog.d/`, one file each, not
in this file; `changelog.d/README.md` says how to write one.
`make changelog` prints them as the next release will write them. The
release moves them in here, under the new version.

## [Unreleased]

## [0.3.2] - 2026-10-28

### Added

- An idle agent's row shows how many minutes it has sat idle, just left of
  its context %, as `34m`. Only an idle agent shows a time: one that is
  busy, waiting or blocked shows nothing, however long it has been so. The
  time is dim grey at first, turns orange and bold at 45 minutes and red
  and bold at 60. Three settings, in minutes, move those points:
  `agent_idle_orange`, `agent_idle_red`, and `agent_idle_blink`, which
  makes the time blink from that minute on. Blinking is off (`0`) by
  default. The time takes the same four columns on every row, so the
  context % stays lined up on the right. The new field is `{idle_m}`, and
  the default `agent_format` now carries it. A settings file made by an
  earlier version keeps its own `agent_format`: to see the time, put
  `{idle_m} ` before `{ctx}` in it, or run
  `sessionview-config unset agent_format` to take the new default.
- The sessionview skill points to the sessionkit skill's card on several
  agents in one seat or on one call, in one line after its opening
  paragraph, and does not repeat the card.

### Changed

- A change now writes its changelog entry to its own file,
  `changelog.d/<slug>.md`, and no longer edits `CHANGELOG.md`. Two changes
  in flight never clash on one file, and an entry can no longer merge
  cleanly under a version that has already been released.
  `changelog.d/README.md` says how to write one.
- `make release` collects the pending entries under the new version, each
  section merged by name in Keep a Changelog order and its entries in
  file-name order, then removes them in the release commit. It refuses a
  malformed entry, or a file under `changelog.d/` it would not read, before
  it bumps the version.
- `make changelog` prints `[Unreleased]` as the next release will write it,
  pending entries included. It writes nothing.
- An earlier entry was reworded to drop a personal name.
- `sessionview install --check` says WARN, not MISSING, when neomutt is
  not installed, and still says ready. neomutt serves only the `messages`
  tab, and sessionview makes that tab only when sessionmail is installed,
  so a missing neomutt no longer reads as a failed install.
  `docs/dependencies.md` now lists neomutt as optional.
- The README and `docs/sessionview.md` quote the question sessionview asks
  the first time it opens, about which agent to start, and how to answer
  it. The README said the dock app asked it; sessionview does.
- An agent whose name is too long for its row keeps its model, idle time
  and context % on the right: the name is cut short with `…` instead.
  Before, a long name pushed the whole right side off the row.
- sessionview keeps its state in `~/.sessionkit/view/state/` and its log in
  `~/.sessionkit/view/log/sessionview.log`, beside its settings, and no
  longer makes files in `~/.local/state/sessionview/`. Both folders are mode
  0700. `SESSIONVIEW_LOG` names another log file, and a `SESSIONVIEW_STATE`
  you set is used as before, with the log in it. On an upgrade, the first
  start hard-links `recent.tsv`, `picker-order`, `sidebar-mail.txt` and the
  `mutt/` files into the new folder. The old names are kept, so a sidebar
  still running from before sees the same files. The old folder stays,
  with the old log, and the old log's last line names the new one. The
  uninstall in the README removes both new folders, and keeps the line for
  the old one.

### Fixed

- The first-run question that asks which agent to start lists each agent
  once, by its name. The launcher's list gives a name and, after a tab, a
  note such as `built in`, and the question split the whole list on spaces,
  so it offered `built` and `in` as agents. It now reads only the name
  before the tab. The sidebar's agent picker reads the list the same way,
  and no longer shows a name with its note attached.
- After you switch the sidebar to another store, a project's ready badge
  counts that store's repo. When two stores each had a project of the same
  name, the sidebar kept the first store's repo for that name, so the other
  store's row showed the first store's count. The sidebar now remembers a
  project's repo per store, and a lookup still running when you switch is
  kept for the store it was asked for.
- Missed from the 0.3.1 notes: a sidebar drag made just after opening
  sessionview is kept. When the sidebar was slow to draw its first screen
  (a busy machine), it showed 14 columns instead of 34 until it did, and a
  drag in that time was put back to 34. The frame's window now starts at
  your terminal's size, so opening it changes no width, and the sidebar
  knows the width it starts at before it first draws.
- The Dock app builds on a Mac without iTerm. `sessionview install --app`
  failed there with osacompile's `Expected end of line, etc. but found class
  name. (-2741)` and built nothing, because AppleScript reads iTerm's words
  from iTerm itself at compile time. The iTerm branch is now compiled only
  when it runs, and if iTerm is chosen but not installed, the app says so in
  a dialog. Nothing changes where iTerm is installed.
- A bare `sessionview` run outside tmux no longer makes an empty `main`
  session beside the ones you already have. It lands in a session tmux
  already holds: the one with your default assistant in it, else the one
  you attached most recently, else the newest. It makes `main` only when
  tmux has no session at all. `sessionview NAME`, and `sessionview` run
  inside tmux, behave as before.
- The files sessionview makes in its state and log folders are private
  (mode 0600, `mutt/` 0700), not readable by other users. They held
  project names and paths, mail paths and what the sidebar saw from remote
  hosts. On an upgrade, each start also sets the old
  `~/.local/state/sessionview/` folder to 0700, because the files linked
  from it are still reachable through their old names. The mode is set
  for each file, not with a umask, so the panes of a tmux server
  sessionview starts keep your umask.

## [0.3.1] - 2026-10-25

### Added

- `sessionview --version` prints the version and exits 0. It was refused
  with `unknown flag --version`.
- `docs/dependencies.md`: the direct dependencies and the tools a user
  meets, what needs each one, whether you need it, how it gets onto your Mac
  and how you upgrade it. The README's Requirements is now the operating
  systems and a link to it. `.github/dependabot.yml` looks for updates to
  the Python dependencies daily.
- `docs/dependencies.md` says where the full resolved set is: `uv.lock`,
  every package at the version this repo is tested with.
- The README's *What an install changes* lists what an install puts on
  your Mac: the commands on PATH, the program, uv's cache, the folders
  each verb makes, the plugin and its skills, your settings and the
  keys a frame binds on your tmux server. Each line says what puts it
  there and what takes it away, and a new *Uninstall* section says how
  to remove it. sessionview runs no launchd service, and its plugin has
  no hooks.
- `docs/sessionview.md`: what `sessionview` does, each verb with its form,
  and an example. The README links it, and the kit's own docs import it.

### Fixed

- A release no longer re-locks the project, and it pushes only what it
  cut. `scripts/release.py` runs `uv version --frozen`, on a dry run too, and
  writes the new version onto uv.lock's own `sessionview` line as text, so a
  release changes no other line of uv.lock and resolves nothing. A plain
  `uv version` re-locked: cut before a dependency's new release was on PyPI,
  it failed, and with `UV_FIND_LINKS` set it wrote a lock of local paths that
  the release then committed. The script refuses a uv.lock without exactly
  one root `sessionview` block holding one `version` line, and a detached
  HEAD, before it writes anything. `make release` runs the script with
  `python3`, not `uv run`, which re-locked before the script started. The
  push line it prints, and `make push`, send the branch by name and then the
  one release tag, `refs/tags/vX.Y.Z`; they sent every local tag, and
  `make push` now refuses a missing tag before it pushes anything.
- A shell line in the docs no longer ends in a `#` comment. Pasted into
  zsh, the macOS shell, the comment was not a comment: `sessionview
  install   # checks every requirement; links nothing` passed the words to
  the installer, which refused them, and then ran `links nothing` as a
  command. Each explanation is now in the prose around its block.
- The docs no longer say the wheel is an empty package: it carries the
  whole tool and puts four commands on PATH. Nor do they say `message send`
  needs a mail server: sessionmail writes into this host's maildirs by
  default. neomutt is listed as required, as `sessionview install --check`
  has treated it.
- The installed `config/README.md` link to the upgrade notes works. The
  wheel now ships `docs/configuration.md` and `docs/settings.md` next to
  `config/`, so `../docs/configuration.md#upgrading-from-010` opens the page
  in an installed copy too. Before, the link pointed at a file the wheel did
  not have. The sdist carries `docs/`, so a wheel built from it ships them
  as well.
- Asking for help no longer does anything else. `sessionview sidebar
  --help` started the sidebar, `install --help` ran the requirements check
  (and, from a checkout, linked the tools onto PATH), `autostart --help`
  decided whether to start an agent, and `from --help` and `terminal --help`
  ran their lookups. Each now prints its usage and exits 0, and so does `-h`.
  `sessionview --help` and `sessionview-frame --help` no longer make the
  state directory before they print.
- An argument a command does not know is refused: one line naming it, then
  the command's whole usage, both on stderr, exit 2, and nothing done.
  `install --version` linked every tool onto PATH and ran the requirements
  check, `newtab --bogus` opened a tab named `--bogus`, `sidebar --bogus`
  never exited, and `autostart`, `from`, `terminal`, `send`, `app-install`,
  `tmux-send-agent` and `tmux-sidebar` acted too. `sessionview <command>
  --bogus` no longer makes the state directory first. `session`,
  `messages` and `usermail` print their usage on stderr when they refuse,
  `sidebar-toggle` and `sessionview-frame` print it at all, and `usermail`
  exits 2, not 1, on an unknown argument. Each `--help` is read to a marker
  in the header, not a line number, so `sessionview-frame --help` no longer
  stops mid-sentence. `sessionview --help` lists `terminal` and `usermail`.
- The `messages` tab refuses a project or store name that is not letters,
  digits and `. _ + -`, and a mail folder holding `"`, a backtick, `\`, `$`
  or a control character. Each was written into the rc NeoMutt runs, where
  a backtick runs a command.
- A store's or project's `.sessionview` can no longer set
  `user_mail_command`, the mail client the `✉ mail` row types in. Like
  `agent_command`, it comes from the template and your home settings only.
- The agent menu shows a pane's title as it is. A title holding `#{...}`
  was expanded as a tmux format in the status line.
- A `.sessionview` window whose `name` is not a string is skipped and
  named. It stopped every tab from opening.
- `sessionview session --print` names each key a store's or project's
  `.sessionview` set and was ignored, and each window entry it skipped.
- The [+] popup's shell command no longer carries the pane's directory; the
  popup starts in it instead.
- The installer never moves links that run a different checkout (a second
  clone, a git worktree, a uv tool): it lists them, changes nothing and
  exits 3. `--relink` moves them here on purpose. `make` with no target
  prints the help; it used to install.
- Resizing your terminal no longer undoes a sidebar drag. A resize that
  changed only the height, or attaching a terminal, put back the width the
  frame started with and remembered it as if you had dragged to it: drag
  the sidebar to 50, change the height, and it went back to 34 for good.
  The width you dragged to now stays.
- A terminal width resize, with no drag, no longer now and then remembers a
  wrong sidebar width. A redraw caught in the middle of the resize could
  take the narrowed sidebar (14 columns, say) for a drag and save it, and
  every later open came up at 14. The sidebar now goes back to your width
  after the resize and saves nothing. If yours opens at a width you never
  chose, drag it back once, or run `sessionview config unset width`.
- `sessionview install --check` WARNs on each tool link that runs a
  different checkout, dangling ones and files that are not links included,
  so they show without an install. It still changes nothing, and a WARN
  never changes its exit status.
- The install replaces a tool's link that points at a directory. It used
  to follow the link and write the new one inside that directory.
- A verb given a flag with no value, a missing or surplus word, or a config word it does not know now refuses before it acts: a reason line, the usage, and exit 2. `usermail --socket` and `send` with no ADDRESS exit 2, not 1. `sidebar-toggle --frame` no longer dies. `config` no longer writes view.json before refusing an unknown word or the wrong number of words. `config --project`/`--store`/`--key` with no value are refused, not silently dropped. A dangling `--store` in `sessionview-messages` no longer swallows the next flag. autostart refuses a surplus positional.
- The messages tab refuses a project or `--store` name that is `.`, `..`
  or begins with `.` or `-`, exit 2, before it asks `message path`: a
  `..` opened a maildir outside the agents tree. A window name from a
  store's or project's `.sessionview` no longer carries a control
  character to the terminal: ESC, DEL and the rest are dropped from the
  notice that its command was ignored, from `sessionview-config windows`,
  and so from the `sessionview-session --print` plan and the new-tab
  picker. A name of control characters only is skipped as no name.

## [0.3.0] - 2026-10-24

### Added

- Release mechanics: `make release` (`BUMP=patch|minor|major` or
  `VERSION=X.Y.Z`) runs `scripts/release.py`. It sets the version in
  `pyproject.toml` with uv, copies it into the plugin manifest and
  `__version__`, stamps this changelog, commits and makes an annotated tag.
  It never pushes. It refuses a dirty tree, a missing `[Unreleased]` or an
  existing tag. `make build`, `make push` and `make publish` (the PyPI token
  never goes on a command line) complete the set. A test fails when any
  copy of the version differs from `pyproject.toml`.
- Log levels: `log_level` (`error`, `timing`, `debug`), or `$SESSIONVIEW_LOG_LEVEL` for one run. `timing` writes a line per click or key with its milliseconds, and each command of 50 ms or more, so a slow click names its slow part. `debug` adds every command and mouse event; `sidebar-mouse.log` is no longer written.

### Fixed

- A project's code window opens Neovim on a second tmux server too. Its
  socket name now carries the server as well as the pane, as show-me's
  does, so two servers' same-numbered panes no longer collide ("address
  already in use"). The neovim skill's `nvim-sock` finds it by that name.
- `sessionview from` and `sessionview sidebar-toggle` work from a package
  install; the docs named `sessionview-from`, which only a checkout puts on PATH.
- Inside tmux, `sessionview` takes over only your own terminal or refuses (exit 2),
  an unknown word prints usage instead of opening a frame, and a sidebar click
  outside a frame or popup, with no pinned client, no longer moves another
  client (SV-192).
- A first open no longer remembers a sidebar width you never chose. The
  frame's own layout steps, before your terminal attached, could be taken
  for a drag of the border and saved, so a new user's sidebar opened at 100
  columns from then on. Only a drag made while a terminal is attached is
  remembered now. If your sidebar opens too wide, drag it back once, or run
  `sessionview config unset width`.

## [0.2.0] - 2026-10-20

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
- Version 0.2.0. The author is the maintainer, <mike@sessionkit.ai>. Project
  URLs (homepage, repository) point at
  <https://github.com/sessionkit/sessionview>.
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
