# The `messages` tab

The project's mail, read-only in neomutt (`sessionview-messages`). Opens
only when `message path STORE/NAME` finds THIS store's mailbox (`has_mail`;
STORE is the session's store, so a name two stores share never opens the
other's box). Read state is never changed: `message mark` is the
only thing that marks mail read. On the left, a sidebar of three boxes:
the box, Asks, Asks · threads (`mail-sidebar.md`). Check it with
`sessionview-messages NAME --store STORE --print`.
