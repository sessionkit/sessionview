---
name: tmux
description: >-
  Drive tmux without eyes and without breaking the human's terminal: find the
  server/session/window/pane you mean, read only the lines you need, type
  into a pane safely, and move the human's view (show-and-tell). Use when an
  agent must act on a tmux pane it did not create, or show the user a window.
---

# tmux — the belt, not the workshop

Four tools, one rule each. You have no eyes: every action is followed by a
bounded read. Reading a whole window is expensive; read the last N lines.

## Tools (`scripts/`)

- `tmux-where [-L SOCK]` — the map: every server, session, window, pane;
  one line each with the pane's current command. Run this first.
- `tmux-peek PANE [N]` — the last N lines (default 20) of a pane. `PANE`
  is `%id`, `session:window.pane`, or `-t` syntax; `-L SOCK` for a server.
- `tmux-type PANE TEXT` — `send-keys -l` then `Enter`, two calls. REFUSES
  when the pane runs an editor/TUI (nvim, vim, lazygit, less, htop, claude)
  unless `--force` (flags go anywhere); those panes interpret keys. Then
  peek.
- `tmux-show TARGET [--client TTY]` — show the human: `select-window` on
  TARGET's session; with `--client`, `switch-client -c TTY` too. Never
  moves a client you were not given.

## Rules

1. Shells take commands; editors, TUIs and REPLs take KEYS. `tmux-where`
   tells you which is which before you type.
2. `$TMUX_PANE` is you. `display-message` without `-t` is the ACTIVE pane
   of the window, which may not be you.
3. Two calls to submit: literal text, then Enter. One call does not submit
   reliably into Claude Code.
4. Verify after acting: `tmux-peek`. A successful `send-keys` proves
   nothing about what the program did with it.
5. Never `kill-server`, never `kill-session` of a session you did not make,
   never `git switch` in a pane on a shared checkout.

## Power moves

- A window in a session, in its directory, named:
  `tmux new-window -t =SESSION -n NAME -c DIR "CMD"`.
- Which client is watching what:
  `tmux list-clients -F '#{client_tty} #{session_name}'`.
- A pane's directory: `tmux display -p -t PANE '#{pane_current_path}'`.
- Another server: every command takes `-L NAME` (sessionview stores each
  run their own).
