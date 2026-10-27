# Dependencies

The direct dependencies of sessionview and the tools a user meets: what
needs each one, whether you need it, how it gets onto your Mac, and how you
upgrade it. The README's [requirements][readme-requirements] link here.

The full resolved set, every package at the version this repo is tested with, is in [`uv.lock`][uv-lock].

- **Required:** macOS and Python 3.11 to 3.14 (standard library only).
  sessionview has no Python package dependencies.
- **Optional:** sessionmail, neomutt, sessiontools, taskmaster, Claude Code,
  uv, git, lazygit, an editor, and a few tools single features use.
- **Pending a ruling:** Homebrew, tmux, notmuch and ffmpeg. Whether the
  family requires them is not decided yet; their entries say what uses each
  one today ([pending a ruling][pending]).
- **Upgrade:** `uv tool upgrade sessionview` for the package, `claude plugin
  update` for the plugin ([upgrade][upgrade]).
- **Check:** `sessionview install --check` (from a checkout,
  `bin/sessionview-install --check`) checks tmux, Python, `session`, neomutt,
  notmuch's index and `tm`, says PASS, WARN or MISSING with the fix for each, and
  changes nothing.

Required means a default command fails without it. Optional means a feature
you turn on needs it, or a command still works without it but does less.

## sessionview itself

It comes two ways, and you can have both:

- **The package**, from PyPI: `uv tool install sessionview` puts
  `sessionview`, `sessionview-config`, `sessionview-session` and
  `sessionview-messages` on your PATH. The wheel carries the whole tool:
  `bin`, `lib`, `config`, `tmux`, `plugins` and `macos`. Each command runs
  its namesake there, on the Python the install chose.
- **The Claude Code plugin**: its skills (sessionview, tmux, lazygit,
  neovim, claude-code). From a clone: `claude plugin marketplace add
  <path-to-clone>`, then `claude plugin install sessionview@sessionview`.

From a checkout, `bin/sessionview-install` links the tools into
`~/.local/bin` (or `$PREFIX/bin`) and runs the check; it installs nothing
else.

## Required

| Dependency | What needs it | How you get it | How you upgrade it |
|---|---|---|---|
| macOS | Everything. Tested on macOS 27 on Apple silicon. The dock app and the menu's Copy are macOS only; the sidebar and the frame are tmux and Python and should run on Linux, untested. | Your Mac. | Software Update. |
| Python 3.11 to 3.14 | The sidebar and the config tools (`sessionview-config`, the settings screen). Standard library only. Without one, the check says MISSING; macOS ships 3.9. | `uv tool install sessionview` brings its own and every command uses it. From a checkout: `uv python install 3.14`, or `brew install python@3.14`. | With the package: `uv tool upgrade sessionview`. Otherwise the way you installed it. |

## Optional

| Dependency | What needs it | Without it | How you get it | How you upgrade it |
|---|---|---|---|---|
| [sessionmail][pkg-mail] (`message`) | Every mail action: the agent menu's Message, Continue, Settle and Speak, the agent pane menu, and the session, taskmaster and voicemode plugins, which each list `message` in their `requires`. The `messages` tab finds its folder with `message path`. | The mail items are hidden and no `messages` tab is made. Run by hand, `sessionview-messages` exits 2, "no `message` on PATH". | `uv tool install sessionmail`. | `uv tool upgrade sessionmail`. |
| [neomutt][neomutt] | The `messages` tab: `sessionview-messages` runs `neomutt -R`, read-only. sessionview makes that tab only when sessionmail is installed, and then opens it by default when the project has a mailbox. Also the sidebar's `✉ mail` row, which falls back to `mutt`. | The check says WARN and still says ready. The tab opens and its command exits 2, "no neomutt on PATH". Without sessionmail there is no tab to need it. | `brew install neomutt`, which is built with notmuch, as the tab's sidebar needs; or your package manager's, built with notmuch. | `brew upgrade neomutt`, or the way you installed it. |
| [sessiontools][pkg-tools] (`session`) | Agent rows, Start an agent, and the agent menu (`session list`, `session start`). | The check says WARN. The sidebar lists projects (tmux sessions) but no agent rows, so no agent menu (Message, Continue, Settle, ...) and no Start an agent. `message` itself still works from a shell. | `uv tool install sessiontools`. | `uv tool upgrade sessiontools`. |
| taskmaster (`tm`) | The store row and Switch store (`tm store list`), the new-session picker's projects (`tm project list`), the taskmaster menu items, and a store's `tasks` tab. A project's `tasks` tab, offered but not opened by default, runs a `tasks` command of your own. | No store row, the picker offers no projects, and the taskmaster items are hidden. The sidebar still lists your tmux sessions. | Its own install. | Its own upgrade. |
| [Claude Code][claude-code] | The plugin and its skills; the voicemode plugin's Speak item, shown only when that plugin is installed. | No skills. The sidebar runs without it. | Its installer. | Claude Code's own update. |
| [uv][uv] | `uv tool install sessionview`. From a checkout, `make build`, `make release` and `make publish`. | Install from a checkout instead. | The uv installer, or `brew install uv`. | `uv self update`, or `brew upgrade uv` for a Homebrew copy. |
| git | A project row's branch and status; lazygit, in the `git` tab. | The rows show no branch or status. | Apple's Command Line Tools: `xcode-select --install`. | Software Update. |
| [lazygit][lazygit] | The `git` tab, opened by default in a project with a repository. | The tab opens and the command fails; nothing checks first. | `brew install lazygit`, or its own releases. | `brew upgrade lazygit`, or the way you installed it. |
| An editor | The `project` tab (`PROJECT.md`, when there is one), the `editor` tab and the store's `slipbox` tab: `$VISUAL`, else `$EDITOR`, else `nvim`. | The tab opens and the command fails. | Your editor's own install. | Its own upgrade. |
| ssh | Remote hosts: their sessions and agents, over a control master you already hold. None are configured by default. | No remote rows. | macOS ships it. | Software Update. |
| osacompile, codesign | `sessionview install --app`, the dock app. | No `osacompile`: the build stops. No `codesign`: the app is built unsigned, with a warning. | macOS ships both. | Software Update. |
| show-me | The skills, which use it to move your view to a pane or a file. Referenced, not bundled. | The skills cannot move your view. | Its own install. | Its own upgrade. |

macOS also ships what the rest uses: `pbcopy` for Copy, and bash 3.2 for
sessionview's bash tools, which use no bash 4 construct.

**Mail across machines** is sessionmail's, not sessionview's: sessionview
never talks to a mail server. sessionmail's `message send` writes each copy
straight into this host's maildirs by default, and mail to another host goes
through postfix, which sessionmail sets up as an opt-in
([sessionmail][pkg-mail]).

## Pending a ruling

Whether the family requires these four is not decided yet, so this page
gives them no class and no install step. Each entry says what uses it today,
what happens without it, and where it comes from today.

### [Homebrew][brew]

Status: pending a ruling. It hangs on the rulings for tmux, notmuch and
ffmpeg below.

- **What uses it:** no sessionview command runs `brew`. The fix lines
  `sessionview install --check` prints name it, for tmux, Python, neomutt
  and notmuch.
- **Without it:** sessionview runs the same; tmux, neomutt and notmuch come
  from somewhere else.
- **Where it comes from today:** its installer, from its own site.

### [tmux][tmux]

Status: pending a ruling.

- **What uses it:** everything. `sessionview` is an outer tmux holding the
  sidebar's pane and your session's; every project is a tmux session and
  every tab a tmux window. It needs 3.7 or newer.
- **Without it:** sessionview does not run, and `sessionview install
  --check` says MISSING and not ready. Below 3.7 it says MISSING too: an
  older tmux can arrive without a word from its installer.
- **Where it comes from today:** Homebrew.

### [notmuch][notmuch]

Status: pending a ruling. Whether the family needs notmuch, and a
replacement for its search built on SQLite's full-text search, are being
researched.

- **What uses it:** the `messages` tab's sidebar: the box, Asks, and Asks ·
  threads. The Asks rows need notmuch to index the `Type` and `Project`
  headers; `sessionview install --check` prints the three lines that do it.
- **Without it:** the tab opens the one folder with no sidebar, and the
  check says WARN. With notmuch but without the two headers indexed, the
  Asks rows show every mail to the project's `+ask` address, replies too.
- **Where it comes from today:** Homebrew.

### [ffmpeg][ffmpeg]

Status: pending a ruling. What the family needs ffmpeg for is being
researched.

- **What uses it:** no sessionview command uses ffmpeg.
- **Without it:** sessionview works the same.
- **Where it comes from today:** sessionview does not need it.

## Upgrade

```bash
uv tool upgrade sessionview
claude plugin marketplace update sessionview
claude plugin update sessionview@sessionview
```

- **The first line** upgrades the package and keeps the Python the install
  chose. sessionview has no Python dependencies to bring.
- **The plugin lines** fetch the marketplace again, then the plugin's
  skills. Installed through Session Kit, the plugin is
  `sessionview@sessionkit`: `claude plugin marketplace update sessionkit`,
  then `claude plugin update sessionview@sessionkit`. Restart Claude Code
  after.
- **From a checkout:** `git pull` in it. The links in `~/.local/bin` point
  into the checkout, so they run the new code at once; run
  `bin/sessionview-install --check` to see that nothing new is missing.

[readme-requirements]: ../README.md#requirements
[uv-lock]: ../uv.lock
[upgrade]: #upgrade
[pending]: #pending-a-ruling
[brew]: https://brew.sh
[claude-code]: https://claude.ai/code
[uv]: https://docs.astral.sh/uv/
[tmux]: https://github.com/tmux/tmux
[notmuch]: https://notmuchmail.org
[ffmpeg]: https://ffmpeg.org
[neomutt]: https://neomutt.org
[lazygit]: https://github.com/jesseduffield/lazygit
[pkg-mail]: https://github.com/sessionkit/sessionmail
[pkg-tools]: https://github.com/sessionkit/sessiontools
