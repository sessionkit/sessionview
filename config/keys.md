---
doctype: reference
name: sessionview-keys
title: sessionview keys (the sidebar alphabet)
aliases:
  - keys
  - keymap
  - keyboard shortcuts
  - the sidebar alphabet
tags: [sessionview, sidebar, keys, keymap, alphabet, reference]
created: 2030-06-09
---

# sessionview keys (the sidebar alphabet)

One letter, one action, anywhere in the sidebar. The list below is the
whole keyboard: a letter not on it does nothing, and a letter is claimed
here before it is bound in `bin/tmux-sidebar`: see what is free, take
one.

## The rule that makes single letters possible

The frame runs its own tmux server with `prefix None` and the sidebar
reads its pane in cbreak mode (`tmux-sidebar`, the `select` loop), so a
bare letter is the sidebar's to keep - nothing upstream wants it.

**Keys are global, not focused.** A letter does the same thing wherever
the pointer sits; there is no "which half am I in". Without a click you
cannot see which half has focus, and every key already knows where it
acts. An overlay - a prompt, a menu, the picker - owns the keyboard
while it is open, so letters are dead inside one; that gate already
exists and is where these land.

Case matters: `q` and `Q` are two keys. A free letter is listed as a
capital so the list reads as an alphabet; **a claimed line writes the
key as you press it** (`a`, not `A`), because `?` reads this file to
draw the help. Uppercase is a letter's loud twin, claimed on its own
line when it exists (`Q` quit beside `q` reload).

## The alphabet

Each entry: letter, the word, then what it does in the rest of the
69-character line. Free letters are listed so the gap is visible.

- a - agent: start one; the picker over the launcher's agent list (the `+` button)
- B
- C
- D
- E
- F
- G
- H
- I
- J
- K
- L
- M
- N
- O
- p - project: open one; the picker of taskmaster projects (the `new`)
- Q - quit: exit 3, the supervisor loop ends (already bound)
- R
- s - store: Switch store, as the ⋯ on the store row does
- T
- U
- V
- w - wide: flip the bar narrow/wide, as the header chevron does; remembered
- X
- Y
- Z
- q - reload: exit 0, `sessionview sidebar` runs us again (already bound)
- ? - keys: this list, drawn in the sidebar; also `Keys` in the ⋯ menu

## Order of arrival

A, P and S came first: start an agent, open a project, switch store.
`?` is help, so `h` stays free for something real; help is ALSO a line
in the ⋯ menu for those who click. The panel draws THIS list, so help
cannot drift from what is bound. The rest arrive as they are needed.

## Candidates

Ideas, not built yet:

- **a REPL under the agents**: a small text input that opens on the
  selected agent and chats with it over mail, or runs slash commands
  across agents
- **kick a role** (super, engineer) at a project: the ⋯ menu is where
  it belongs, and a key may follow
- **hamburger** on the agent row for the menu, in place of right-click,
  which does not work on an iPad
