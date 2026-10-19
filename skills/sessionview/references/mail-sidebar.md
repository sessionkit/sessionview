# The `messages` tab's sidebar: the boxes on the left

Three rows, written per project into the tab's rc:

- **NAME**: the box, every message, threaded. Where the tab opens.
- **Asks**: one line per ask of this project:
  `Type:ask and (to:"NAME+ask" or Project:"NAME")`. notmuch's `to:` matches
  Cc, and every ask carries its project's `+ask` box in To or Cc.
- **Asks · threads**: the same asks with every reply under them. An answer,
  or a reply carrying a task id, shows as a child: read "is it being worked
  on" here.

Keys: `Ctrl-n` / `Ctrl-p` move between rows, `Ctrl-o` opens the row, `B`
hides and shows the sidebar, `+` on an ask pulls its whole thread in. The
count on a row is the total, never unread (nothing in this tab marks read).

Needs: `notmuch` on PATH, the folder under its `database.path`, and the
`Type` and `Project` headers indexed. Without the index the Asks rows are
every mail to `NAME+ask` (replies too) and the rc says so; without notmuch
the tab is the one folder and the sidebar is hidden.
`sessionview-messages NAME --store STORE --print` names which, and shows
the rc. The look (width, format, keys) is `config/neomuttrc`;
`~/.sessionkit/view/settings/neomuttrc` is sourced last and wins.
