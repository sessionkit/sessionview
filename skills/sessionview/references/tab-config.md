# Tab config: the `windows` list

One list builds a new session's tabs and fills the new-tab picker
(project menu > New tab, or the tab bar's `+`). Print it, pins applied:
`sessionview-config windows`.

## An entry

- `position`: a number that orders the tabs. Keep gaps (10, 20, 30).
- `name`: the tab label.
- `when`: `always`, `has_repo`, `has_projdir`, `has_mail` or `fallback`.
  Named tests, never expressions.
- `cwd`: `root`, `repo` or `projdir`. Named dirs, never evaluated.
- `command` (optional): typed into the tab. `{editor}` (VISUAL, else
  EDITOR, else nvim), `{readme}`, `{pmd}` (PROJECT.md), `{project}`.
- `focus` (optional): the tab you land on.
- `auto` (optional, default true): false = offered by the picker only.
  On a `fallback` entry, true = opens with every session.

## The store view: `store_windows`

The same fields, its own list, for the store row's session
(`sessionview-session NAME --store-view STORE`). Print it with
`sessionview-config windows --key store_windows`. Its own names:
`when` `has_store_project`, `has_slipbox`, `has_scripts`,
`has_store_mail`; `cwd` `store`, `slipbox`, `scripts` (and `projdir`, the
store project); `{store}` and `{store_project}`. `config/README.md` has
the detail.

## Pinning

In the new-tab picker, `^p` or a right-click on a row flips a tab between
opening with the session and picker only. The pin is written to
`window_pins` in `~/.sessionkit/view/settings/view.json`, laid over the list, so
later changes to the list still reach you. If a store or project layer
sets `window_pins`, the pin is refused with that file's path.

## Layers, later wins

1. `config/config.json` in the repo: the template, every default.
2. `~/.sessionkit/view/settings/view.json`: yours, made from the template
   (an older install's file is never read: see Upgrading in
   docs/configuration.md).
3. `STORE/.sessionview`: a JSON file, or a dir holding `config.json`.
4. `.sessionview` walked up from the project's root, nearest wins.

A layer replaces a key whole, so a project that sets `windows` replaces
the entire list. `sessionview-config get windows --where` names the file.
Layers 3 and 4 never say what a tab runs: their `command` is ignored and
the same name's command from layers 1-2 is used, else a plain shell.
