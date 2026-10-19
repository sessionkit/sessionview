---
name: lazygit
description: >-
  Drive lazygit in a tmux pane safely: know which panel is focused and which
  row is selected without reading the whole screen, move to a row by its
  text, and only then act. Use when a user asks you to select a branch, file
  or commit in their lazygit, or to show them something in it.
---

# lazygit — read the cursor before every key

lazygit interprets every key. `j`/`k` only move; Enter, Space and letters
ACT (checkout, stage, commit, delete). An agent has no eyes, so: state,
move, state, then act — and only act when the human asked for that act.

## The git tab has TWO panes: target lazygit by its pane

sessionview's `git` tab is lazygit (pane 0) with a shell CONSOLE under it
(pane 1, in the repo; one row until it is selected, then 20% of the
window). A bare window target such as `-t SESSION:git` means the
ACTIVE pane, which is the console whenever the human is typing in it. So
give these tools, and any `send-keys`, the lazygit PANE: `SESSION:git.0`
or its `%id`, from
`tmux list-panes -t SESSION:git -F '#{pane_index} #{pane_id} #{pane_current_command}'`.
Never type lazygit keys into the console: they are shell input there. Selecting a pane resizes the console; that is the
tab's own hook, not something to undo.

## Tools (`scripts/`)

- `lazygit-state [-L SOCK] PANE` — two lines: `panel: N Title` (the
  focused panel: bold green border; bold cyan = `(searching)`, a filter
  confirmed; `(typing)` = the prompt is open) and `row: text` (the
  selected row: blue background). Exit 2 when the pane is not running
  lazygit, or a custom theme paints it differently. Cheap.
- `lazygit-goto [-L SOCK] [--keep] PANE PANEL TEXT` — refuses (exit 2)
  unless the pane shows lazygit and PANEL is a list (2-5); then lazygit's
  own filter: PANEL `/` TEXT Enter, read the row, Esc. Four keys, ~1.2 s.
  Branches and commits keep the cursor after Esc; the FILES tree does
  not (the filter lands on the directory node first, goto walks `j` to
  the file, and Esc rebuilds the tree) — pass `--keep` to act while the
  filter is up. Exit 3 when nothing matches. (Read from the lazygit 0.64.1
  source.)

Measured on lazygit 0.64.1: `lazygit-goto PANE 3 master` -> `at: *
master ✓`; `lazygit-goto PANE 2 README.md` -> `at: M README.md`.

## The keys that matter

- Panels: `1` status · `2` files · `3` branches · `4` commits · `5` stash.
  `j`/`k` move, `<`/`>` top/bottom, `h`/`l` switch panel, `[`/`]` the
  tabs inside a panel (Files-Worktrees-Submodules; Branches-Remotes-Tags),
  `/` filter or search the list, `Esc` back.
  NOT `g`: in this lazygit (0.64.1) `g` is the RESET
  menu in commits (4) and POP STASH in stash (5) — Enter after it resets.
- Enter opens the row (a branch's commits, a file's diff). `+` cycles the
  focused panel's size (bigger, full screen, back). `q` quits.
- ACTS - never blind, never without the human's word: Space (checkout /
  stage), `c` commit, `d` delete, `M` merge, `r` rebase, `P` push, `p` pull.
- On a SHARED checkout a checkout is a `git switch` under someone else's
  feet: never Space on a branch there.

## Show a branch to the human

`lazygit-goto PANE 3 NAME`, then `tmux send-keys -t PANE Enter` to open
its commits, then `lazygit-state` to confirm. `+` if they want it big.
