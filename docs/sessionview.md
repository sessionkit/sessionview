# sessionview

`sessionview` puts a sidebar beside tmux, in the terminal you run it in:
your projects (tmux sessions) above, your agents below, here and on remote
hosts. A click goes there; a right-click opens that row's menu. Bare
`sessionview` opens the frame: the sidebar on the left and the session
`main` on the right. Every other word is a verb.

- `sessionview --help` lists the verbs.
- `sessionview VERB --help` has each verb's form. Asking never acts: no
  verb does anything on `--help`.
- `sessionview --version` prints the version.
- In any tmux client, `prefix H` opens the same sidebar as a popup.

## The verbs

- `sessionview [SESSION]`: the frame, with SESSION on the right
- `config`: read and write your settings
- `session`: open a project session with its standard tabs
- `messages`: a project's mail, read-only, in NeoMutt
- `install`: check the requirements; `--app` builds the Dock app
- `autostart`: which agent starts when sessionview opens
- `terminal`: the terminal the Dock app opens sessionview in
- `usermail`: your own mail, in one session of its own
- `from`: the name your mail is sent as
- `sidebar-toggle`: hide the sidebar, or show it again
- `sidebar`: the sidebar itself, as the frame's left pane runs it

`sessionview-config`, `sessionview-session` and `sessionview-messages`
are on PATH too: the sidebar runs them. Type the `sessionview VERB` form.

## An example

Make the sidebar 40 columns wide, then open the frame:

```sh
sessionview config set width 40
sessionview
```

## Each verb's form

- `sessionview [SESSION] [--sock SERVER] [--width N]`: SESSION is `main`
  when you name none, and the frame makes `main` if it is not there. A
  SESSION you name must already exist. `--sock` names the tmux server
  SESSION is on. `--width` sets the sidebar's starting columns in place
  of your `width` setting, and writes nothing.
  - To make a new session: `sessionview session NAME`.
- `sessionview config [VERB]`: with no verb, the settings screen (it
  needs a terminal). `list`, `dump [--where]`, `get KEY [--where]
  [--json]`, `set KEY VALUE`, `unset KEY`, `windows`, `init` and `path`.
  `get`, `dump` and `windows` take `--project DIR` and `--store DIR` to
  read those layers too. `get` exits 2 when the key is in no layer.
  Every key is in [Settings][settings], every file in
  [Configuration][configuration].
- `sessionview session NAME [--repo DIR] [--plain] [--print]`: the tabs
  are the `windows` list in your settings. `--list-windows` prints the
  ones that apply to NAME; `--window WNAME` opens one of them in the
  session NAME, which must exist. `--plain` gives one shell instead.
- `sessionview messages PROJECT [--store SLUG] [--print]`: the
  project's mailbox, opened read-only, so reading marks nothing. It needs
  NeoMutt, and `message` to find the mailbox.
- `sessionview install [--check | --relink | --app]`: says PASS, WARN or
  MISSING for each requirement, with the fix. Installed with `uv tool
  install`, it only checks: it links nothing. From a clone, it also
  links the tools into `~/.local/bin`, or `PREFIX/bin` when `PREFIX` is
  set. `--check` only reports, and exits 1 while a requirement is
  MISSING. What each of these puts on your Mac: [what an install
  changes][changes].
- `sessionview autostart --status`: the decision, and nothing done. The
  first open asks which agent to start, once. `--start NAME` starts NAME
  now, which is what the `+` under agents does.
- `sessionview terminal [--why]`: one word, `iterm`, `ghostty` or
  `terminal`. Your `terminal` setting first, then a terminal running
  now, then the one installed. `--why` says which step chose it.
- `sessionview usermail [--socket SOCK] [--session NAME] [--print]`:
  finds the session for your own mail, or makes it.
- `sessionview from`: `SESSIONVIEW_FROM`, else your `mail_from` setting,
  else `$USER`.
  - To set the name: `sessionview config set mail_from NAME`.
- `sessionview sidebar-toggle [--hide | --show]`: from a shell inside the
  frame. With neither, it toggles. The `◧` glyph on the tab bar does the
  same.
- `sessionview sidebar`: the sidebar under its supervisor. In it, `q`
  reloads and `Q` quits; a crash waits on screen for Enter.

What it needs, and why: [dependencies][dependencies].

[settings]: settings.md
[configuration]: configuration.md
[dependencies]: dependencies.md
[changes]: ../README.md#what-an-install-changes
