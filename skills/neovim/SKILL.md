---
name: neovim
description: >-
  Work beside a user's running Neovim (LazyVim) through its server socket
  without typing into it: find the socket for a tmux pane, look at what is
  open (file, cursor, mode, unsaved changes), check a file for unsaved
  changes before you edit it with your own tools, reload it after, read it
  as the user has it, open a file for them, and show or hide Neo-tree
  (Space-e). Use when a user asks you to open something in their editor, or
  before you edit a file they may have open.
---

# neovim — ask the socket; never type into the editor

Edit files with your normal tools. Use the socket to look, to check, to
show and to reload, and every one of those is a `--remote-expr`: nvim
answers a question, or runs one command inside the answer, and no key is
sent. Keys (`--remote-send`, or typing into the pane) land in nvim's input
between the user's own keystrokes: mid-word in insert mode they end insert
mode, and the rest of the user's word runs as commands in whatever you
opened.

## The user's rules

These are the user's words: "my" and "me" are the user.

- Default to using your normal tools for editing, not nvim socket tools
- Use RPC (nvim --server SOCK --remote-*) to:
  - Check for modified buffer via socket before editing with your tools
  - Look: which file is open; where my cursor is
  - Show: open a file for me; jump to a line
  - Reload after you edit on disk (:checktime), so I don't save over you
- Don't use RPC to:
  - Type into my buffer: it races my typing, tangles my undo
  - Edit when the buffer is modified: leave it, tell me

So: no `--remote-send`, ever. Every move is a `--remote-expr`, and the
tools below are those moves.

## Editing a file the user may have open

1. `nvim-modified SOCK FILE`. Exit 0 (modified): leave the file alone and
   tell the user it has unsaved changes. Exit 1 (clean) or 3 (not open):
   go on.
2. Edit FILE on disk with your normal tools.
3. `nvim-reload SOCK FILE`, so the buffer shows your edit and a later save
   cannot write the old text over it. It refuses (exit 1) if the user
   started changing the buffer in the meantime: tell them.

## Tools (`scripts/`)

- `nvim-sock [-L SOCK] PANE` — the socket of the nvim in that pane
  (sessionview's convention, shared with show-me:
  `$TMPDIR/nvim-show-<server key>-pane-<pane number>`, the key being the
  cksum of the tmux server's socket path; else the `--listen` on its
  command line). Exit 2 when there is none.
- `nvim-look SOCK` — one tab-separated line: mode (`n` normal, `i`
  insert, ...), modified (`1`/`0`, the current buffer), cursor line,
  cursor column (bytes), then the current file's full path.
- `nvim-modified SOCK FILE` — does FILE's buffer hold unsaved changes?
  FILE need not be the current buffer. Exit 0 modified, 1 clean, 3 not
  open, 2 usage or no nvim; the word is printed too. So
  `if nvim-modified "$S" "$F"; then` reads "if the user has unsaved work".
- `nvim-reload SOCK FILE` — `:checktime` on FILE's buffer after you edit
  it on disk. Refused when the buffer has unsaved changes: exit 1, one
  line, nothing reloaded. Exit 3 when FILE is not open. It reloads
  silently with `autoread` set (LazyVim sets it); without it nvim asks the
  user.
- `nvim-read SOCK FILE` — FILE as the user has it now, unsaved changes
  included. Exit 3, with a line, when FILE is not open: read the disk.
- `nvim-open SOCK FILE [+LINE]` — show a file, at a line. It checks and
  opens in one expression: when the user is not in normal mode, or the
  current buffer or FILE's buffer has unsaved changes, it leaves the
  window alone, exits 1 and says why in one line (pass that on). Prints
  `path:line` when it opened. `show-me FILE` does more when it is
  installed - a file, a URL, the right pane.
- `nvim-tree SOCK status|show|hide|toggle` — Neo-tree. `status` prints
  `shown`/`hidden` (exit 0/1) by asking nvim which windows hold a
  `neo-tree` buffer; `show`/`hide` are idempotent and, like `toggle`, are
  refused (exit 1, one line) unless the user is in normal mode.

Exit 2 from any of them: usage, or no nvim listening on SOCK.

Following the user's edits as they type (the whole file, diffs since a
last check, ride-along notices) is not in this skill.

## Rules

1. Find the socket first; no socket = do nothing in the editor. Ask the
   user to start nvim with `--listen`, or open the project through
   sessionview, which does (`code_nvim` in config).
2. No `--remote-send`: every move is a `--remote-expr`. A command runs
   inside one, as `execute(...)`, and only behind a check that the user
   is in normal mode with no unsaved changes in the way.
3. Verify with `--remote-expr` (`nvim-look`, the tree status), not by
   reading the screen.
4. A refusal is an answer: leave the window as it is and tell the user
   what you wanted to do and why it waited.

## LazyVim keys the user uses (so you can say them, not press them)

Space-e Neo-tree · Space-Space find file · Space-/ grep · gd definition ·
Space-b buffers · `+`/`-` in Neo-tree expand/collapse.
