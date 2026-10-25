# Settings

sessionview's own settings: JSON keys in
`~/.sessionkit/view/settings/view.json`.
Each table below gives a key's type, its default and what it does.

- **Where they live.** The template `<checkout>/config/config.json` holds
  every key and its default. Your copy,
  `~/.sessionkit/view/settings/view.json`, is made from it the first time
  anything reads the config. An older install's file is never read:
  [Upgrading from 0.1.0][upgrading] says how to move it and what
  sessionview does while it is still there. A store's or a
  project's `.sessionview` may set keys too, later layers winning. The
  layers are on the [configuration page][configuration].
- **Change one** with `sessionview-config set <key> <value>`, which writes
  your copy only. `sessionview-config unset <key>` goes back to the
  default. A key not in the template is refused.
- **See them** with `sessionview-config list`, or project menu → Settings
  in the sidebar.
- **Template or home only.** A key marked so is ignored in a store's or a
  project's `.sessionview`, because it runs something.
- **Not the kit's settings.** sessionview does not read the kit's settings
  cascade today, only its own layers. The kit's guide is
  [sessionkit's docs/settings.md][kit-settings].
- **Not the keyboard.** The sidebar's letters are listed in
  [config/keys.md][keys]. The template's own notes on each key are in
  [config/README.md][config-readme].

## Sidebar size and look

| Key | Type | Default | What it does |
| --- | --- | --- | --- |
| `width` | integer | `34` | Sidebar width in columns. A drag on the border writes it. |
| `fit` | string | `"fixed"` | `fixed`: `width` columns. `auto`: the widest row plus one, between `width_min` and `width_max`. `narrow`: the names only. `focus`: narrow until the sidebar has focus. |
| `width_min` | integer | `20` | The narrowest `fit: auto` goes. |
| `width_max` | integer | `60` | The widest `fit: auto` goes. |
| `refresh` | integer | `2` | Seconds between redraws. |
| `log_level` | string | `"error"` | What the one log records: `error`, `timing` (each click and slow command, in ms) or `debug` (every command and mouse event). |
| `brand` | string | `"sessionview.dev"` | The dim word on the top row. `""` hides it. |
| `popup_bg` | string | `"#181924"` | The tab bar and menu background colour. |
| `selected_fg` | string | `"#f0f3ff"` | The selected row's text colour. |
| `selected_bold` | boolean | `true` | The selected row in bold. |
| `tab_glyphs` | boolean | `true` | Write a glyph per tmux window for the tab bar. |
| `collapse` | string | `""` | A glyph drawn at the right of the bottom row. A click on it does nothing today. |

## Project rows

| Key | Type | Default | What it does |
| --- | --- | --- | --- |
| `show_spaces` | boolean | `true` | Show the project rows (tmux sessions). |
| `project_format` | string | `" {glyph} {name}  {branch}\t{ready} "` | A project row. One TAB right-aligns the rest. |
| `project_format2` | string | `"   {repo} · {branch_raw}"` | A project's second line, shown when `project_two_line` or `project_expand_selected` is on. |
| `project_two_line` | boolean | `false` | Every project gets its second line. |
| `project_expand_selected` | boolean | `false` | The selected project gets its second line. |
| `project_gap` | integer | `0` | Blank rows between projects. |
| `ready_glyph` | string | `"🥚"` | The glyph of the `{ready}` field: unmerged `ready/*` tags. |
| `ready_format` | string | `"{n}{glyph}"` | The `{ready}` field. `"{glyph}"` hides the count. |
| `ready_window` | string | `"git"` | The tab a click on the ready badge opens. `""`: no click action. |
| `store_format` | string | `" {store}"` | The store row. |
| `mid_format` | string | `" +"` | The row between projects and agents; a click opens a new session. |
| `picker_order` | string | `"recent"` | The new-session picker's order: `recent` or `alpha`. |
| `project_dirs` | list | `["~/workspace"]` | Directories that hold your checkouts; each repo under them is offered by the new-session picker. |
| `project_dirs_depth` | integer | `2` | How many levels under each `project_dirs` entry to look. |

## Agent rows

| Key | Type | Default | What it does |
| --- | --- | --- | --- |
| `agents_heading` | string | `" agents\tgrouped "` | The agents heading. |
| `agent_format` | string | `" {glyph} {at}{label}\t{model} {ctx} "` | An agent row. |
| `agent_format2` | string | `"   {agent}\t{ctx} {idle} "` | An agent's second line, shown when `agent_two_line` is on. |
| `agent_two_line` | boolean | `false` | Every agent gets its second line. |
| `agent_gap` | integer | `0` | Blank rows between agents. |
| `group_by` | string | `"none"` | Group agents: `none`, `repo`, `project` or `session`. |
| `group_format` | string | `" {group}"` | A group's heading row. |
| `sort` | list | `["rank", "idle_s"]` | The fields agents are sorted by, in order. |
| `hide` | list | `[]` | Agent statuses to leave out. |
| `pinned_agents` | list | `[]` | Agent names held at the top, in this order, here and in the start-an-agent picker. |

## Remote hosts

| Key | Type | Default | What it does |
| --- | --- | --- | --- |
| `remotes` | list | `[]` | ssh hosts whose sessions and agents are shown. |
| `remote_heading` | string | `" remote"` | The divider above them. |
| `remote_refresh` | integer | `5` | Seconds between reads of a remote host. |
| `remote_connect` | string | `"ride"` | `ride`: only over an ssh control master you already hold. `auto`: connect on each read. |

## Your mail row

| Key | Type | Default | What it does |
| --- | --- | --- | --- |
| `user_mail_command` | string | `"neomutt"` | The mail client the `✉ mail` row opens, typed as is. `""`: no row. Template or home only. |
| `user_mail_socket` | string | `"default"` | The tmux server that session lives on. |
| `user_mail_session` | string | `"mail"` | That session's name. |
| `user_mail_format` | string | `" ✉ mail"` | The row's label. |

## Sessions and tabs

| Key | Type | Default | What it does |
| --- | --- | --- | --- |
| `windows` | list | 7 tabs | A project session's tabs and the new-tab picker's suggestions. Any layer, but an entry's `command` comes from the template or home only. |
| `store_windows` | list | 5 tabs | The store view's tabs, the same fields as `windows`. The same rule for `command`. |
| `window_pins` | object | `{}` | Your pins over `windows`: `{"<tab>": true}` opens it with every session. |
| `code_nvim` | boolean | `false` | Open the `editor` tab when a session opens. |

The fields of a `windows` entry are `position`, `name`, `when`, `cwd`,
`command`, `focus`, `auto` and `console`. The template lists the shipped
tabs; [config/README.md][config-readme] describes each field.

## Agents

| Key | Type | Default | What it does |
| --- | --- | --- | --- |
| `agent_command` | list | `["session", "start", "--tmux-target", "{project}", "--no-switch", "{agent}"]` | What Start an agent runs; `{project}`, `{agent}`, `{dir}` and `{socket}` are filled in. Template or home only. |
| `autostart_agent` | string | `"ask"` | When sessionview opens: `"ask"` asks once and remembers, `""` starts none, a name starts that agent. |

## Dock app and mail

| Key | Type | Default | What it does |
| --- | --- | --- | --- |
| `terminal` | string | `""` | The terminal the dock app opens: `iterm`, `ghostty` or `terminal`. `""` works it out. |
| `fullscreen` | boolean | `false` | The dock app opens sessionview full screen. |
| `pane_menu` | boolean | `false` | Right-click on an agent's pane opens the agent pane menu. It replaces your own tmux right-click menu. |
| `mail_from` | string | `""` | The name sessionview's mail is sent as. `""`: the next in line, on the [configuration page][mail-sender]. |
| `pane_menu_from` | string | `""` | The older name for `mail_from`, read when `mail_from` is empty. |

[configuration]: configuration.md
[upgrading]: configuration.md#upgrading-from-010
[mail-sender]: configuration.md#mail-sender
[kit-settings]: https://github.com/sessionkit/sessionkit/blob/HEAD/docs/settings.md
[keys]: ../config/keys.md
[config-readme]: ../config/README.md
