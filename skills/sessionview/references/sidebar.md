# The sidebar: what the rows mean

## Agent glyphs

Agent rows, project rows and the tab bar carry one glyph. A project or tab
shows the most urgent of its agents.

- `■` red: blocked or waiting
- `◐` yellow: busy
- `●` green: idle
- `○` dim: shell

In the pickers, `●` marks a tab or session already open (an agent already
running) and `○` one that is not.

## Ready badge (the eggs)

`3🥚` on the right of a project row counts its `ready/*` tags that are not
yet merged into the default branch. `?🥚` means no default branch was found.
A reviewer makes one with `git ready mint` on a branch. `git ready merge`
merges it and the egg goes. A click on the badge opens the project's `git`
tab (lazygit). Change the look with `ready_glyph`, `ready_format` and
`ready_window`.

## Using it

- `q` reloads the sidebar (new code, new config). `Q` quits it.
- `+` under the projects (or `p`) opens the project picker: type to
  filter, Enter opens. `a` starts an agent. `?` lists the keys.
- Right-click the agent's ROW for its menu. A right-click inside a pane
  goes to tmux (or to the opt-in agent pane menu, `pane_menu`).
- In a menu, bright items are live and dim items do not apply here.
- Message, Continue, Settle, Stand down and Succeed send MAIL, not
  keystrokes. The agent answers on its next turn.
- A failed action shows its error's first line, unclipped, in a `failed`
  box. Failed tmux calls and crashes go to
  `~/.local/state/sessionview/sessionview.log`.

## Store view

The top row is the store: its name, then `⋯`.

- Click the NAME: opens that store's own session, on its own server, and
  moves you there. The session is the one named after the store, else an
  old `store` session. A down server is started by `tm store boot`.
- Its tabs are `store_windows` (`tab-config.md`): `tasks` (a one-shot
  `tm task list` of `projects/store`, else `projects/<store>`, else no
  tab), `slipbox`, `scripts` (when the store root has them), `messages`
  (the store's box, read-only). Missing tabs are added; none is closed.
- `⋯` (or `s`): the Switch store modal. A pick opens that store the same way.
- Right-click the row: the store menu (Kick the GC).
- The store's session and its store project never show as project rows.
