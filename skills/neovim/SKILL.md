---
name: neovim
description: >-
  Drive a running Neovim (LazyVim) from outside, through its server socket:
  find the socket for a tmux pane, open a file, and know whether Neo-tree
  (the file tree, Space-e) is shown, then show or hide it. Use when a user
  asks you to open something in their editor or tidy its layout - never by
  typing keys into the editor pane.
---

# neovim — talk to the socket, not the keyboard

Keys into an editor pane are interpreted by whatever mode it is in. The
socket is exact: `nvim --server SOCK --remote-send / --remote-expr`.

## Tools (`scripts/`)

- `nvim-sock [-L SOCK] PANE` — the socket of the nvim in that pane
  (sessionview's convention, shared with show-me:
  `$TMPDIR/nvim-show-<server key>-pane-<pane number>`, the key being the
  cksum of the tmux server's socket path; else the `--listen` on its
  command line). Exit 2 when there is none.
- `nvim-open SOCK FILE [+LINE]` — open a file; prints the buffer path
  back. `show-me FILE` does this and more when it is installed - prefer it.
- `nvim-tree SOCK status|show|hide|toggle` — Neo-tree. `status` prints
  `shown`/`hidden` (exit 0/1) by asking nvim which windows hold a
  `neo-tree` buffer; `show`/`hide` are idempotent.

## Rules

1. Find the socket first; no socket = do not type. Ask the human to start
   nvim with `--listen`, or open the project through sessionview, which
   does (`code_nvim` in config).
2. Every `--remote-send` starts with `<C-\><C-n>` (back to normal mode)
   so the command lands whatever mode the human left it in.
3. Verify with `--remote-expr` (`expand("%:p")`, the tree status), not by
   reading the screen.
4. Never send `:q`, `:w`, or anything that changes a buffer the human is
   editing, unless they asked for that act by name.

## LazyVim keys the human uses (so you can say them, not press them)

Space-e Neo-tree · Space-Space find file · Space-/ grep · gd definition ·
Space-b buffers · `+`/`-` in Neo-tree expand/collapse.
