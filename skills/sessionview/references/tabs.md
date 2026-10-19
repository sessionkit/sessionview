# Tabs: an index

A project session's tabs come from the `windows` list in config
(`tab-config.md`). Every tab is a shell with its tool typed in, so quitting
the tool leaves a prompt in the right directory. One file per tab type:

- `tab-project.md`: the store's project dir, the editor on `PROJECT.md`.
- `tab-tasks.md`: the same dir, running `tasks`. Picker only.
- `tab-messages.md`: the project's mail, read-only in neomutt.
- `tab-repo.md`: the project's git checkout, a plain shell.
- `tab-git.md`: the repo, running `lazygit`.
- `tab-editor.md`: the repo, the editor on its README. Picker only.
- `tab-shell.md`: a shell at the root, when no other tab opened.

A store's session (the sidebar's store row) takes its tabs from
`store_windows` instead: `tasks`, `slipbox`, `scripts`, `messages`. See
`sidebar.md` (Store view) and `tab-config.md`.

There is no super tab. The project's super is an agent row: project menu
> Kick starts it, > Message super mails it (the taskmaster plugin).
