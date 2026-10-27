# Decision: where sessionview keeps its state and its log

Status: decided before the code. Nothing here is built yet; the code that
follows this note implements it, and a change to a rule changes this note in
the same commit. The question a review left open (what a process that still
holds the old dir sees) is decided: the state files are linked into the new
dir, never moved out of the old one (section 3).

sessionview's state and its log get a new home in the kit's dir, beside the
settings it already keeps there. The old dir, `~/.local/state/sessionview/`,
is left in place: it keeps the old log, and the state files keep their old
names there as hard links (section 3).

The new home:

```text
~/.sessionkit/view/settings/   the settings (already here)
~/.sessionkit/view/state/      the state: recent projects, picker order, mail body, neomutt files
~/.sessionkit/view/log/        the log: sessionview.log
```

This note fixes five things: the one resolver for these paths, the new
defaults, the old-path fallback with its one-time link step, why that step is safe
when several entry points start at once, and how the older move from
`~/.local/state/herd` chains into it.

## Names used below

| name | path | what it is |
|---|---|---|
| `N` | `$HOME/.sessionkit/view/state` | the new default state dir |
| `L` | `$HOME/.sessionkit/view/log/sessionview.log` | the new default log file; its dir is `LD` |
| `O` | `$HOME/.local/state/sessionview` | the old default state dir, which also held the log |
| `H` | `$HOME/.local/state/herd` | the pre-release state dir, moved to `O` once by the older rule |

`STATE` and `LOG` are the two answers the resolver gives: the state dir and
the log file this process uses.

## 1. One resolver: one shell rule, one Python rule

Today the default `~/.local/state/sessionview` is written by hand in six
code lines: `bin/sessionview` (twice: the sidebar verb and the frame),
`bin/sessionview-frame`, `bin/sessionview-session`, `bin/sessionview-messages`
and `bin/tmux-sidebar`. `bin/tmux-sidebar` also carries a copy of the move from
`H`. After this change the paths are written in exactly two places.

### The rule (identical in both languages)

1. `STATE` is `$SESSIONVIEW_STATE` when it is set and not empty. Otherwise it
   is `N`.
2. `LOG` is `$SESSIONVIEW_LOG` when it is set and not empty. Otherwise, when
   `STATE` is exactly the string `N`, it is `L`. Otherwise it is
   `$STATE/sessionview.log`.

So `$SESSIONVIEW_LOG` overrides the log on its own, and `$SESSIONVIEW_STATE`
on its own keeps the log in that dir, exactly where it is today. Every test
that points `$SESSIONVIEW_STATE` at a scratch dir sees no change.

Three details make the two languages agree:

- **Empty is unset**, as the shell's `${VAR:-default}` reads it. Python must
  not use `os.environ.get(name, default)`, which keeps an empty string.
- **A value is used verbatim.** No `~` is expanded, nothing is normalised,
  no trailing slash is stripped. The shell expands no `~` inside a variable,
  so Python must not either (today's `os.path.expanduser` on the value goes).
- **The defaults are built by joining strings**: `$HOME` + `/.sessionkit/view/state`,
  in both languages. `os.path.join` and `normpath` would drop a doubled slash
  that the shell keeps (a `HOME` that ends in `/`), and the comparison in rule
  2 would then differ.

### "The default" is a value, not an unset variable

Rule 2, and every rule in sections 3 to 5, asks whether `STATE` is the
default by comparing its value with the string `N`. It never asks whether
`$SESSIONVIEW_STATE` was set. This is on purpose:

- The entry scripts export `SESSIONVIEW_STATE` to everything they start, so a
  sidebar started by the frame always sees it set, to `N`. It must still
  treat it as the default.
- The frame re-runs itself across a tmux `detach-client -E` hop, which runs
  with the client's environment, so it carries `SESSIONVIEW_STATE` by hand.
  It now carries `SESSIONVIEW_LOG` beside it when the user gave one (see
  below), so a user's own log path survives the hop.
- The answer is a fixed point: resolving an environment that already holds
  the resolved `STATE` and `LOG` gives the same two paths again.

**`SESSIONVIEW_STATE` is exported resolved; `SESSIONVIEW_LOG` is exported
only when the user gave it.** The log's default is a pure function of
`STATE` (rule 2), so every process derives it again and gets the same
answer. Exporting the derived `L` would turn the default into an override
for every descendant. The entry scripts' environment reaches far: a tmux
server that a frame starts (`new-session -d` on a server that is not running
yet) keeps it as its global environment, so every pane shell and every
binding on that server inherits it. A process there that sets only
`$SESSIONVIEW_STATE` would then write its log to `L`, the real default log,
and not to `$STATE/sessionview.log` as rule 2 says. So `lib/state.sh` leaves
`SESSIONVIEW_LOG` exactly as it found it: set and non-empty, it stays and is
exported; unset or empty, it stays unset, and only the shell variable
holds `LOG`.

A consequence, also on purpose: a value equal to `O` is not the default. It
is used as given, and nothing is linked or read by fallback for it. Section 3
relies on this. Such a value
reaches new code three ways: a user who typed the old default; a process
started by older code, which exported `O`; and, longest-lived, a tmux server
started by an older frame, which keeps `O` in its global environment until
that server exits. The frame server is one of these: the sidebar pane gets
`SESSIONVIEW_STATE` only from the frame server's global environment (the
frame passes `SESSIONVIEW_PIN` and others with `-e`, but not it). Section 3,
"Processes that hold `O`", says why such a process stays correct.

### Where the rule lives

- **Shell: `lib/state.sh`**, and nowhere else. The six entry lines stop
  writing a default and only source it. It sets and exports
  `SESSIONVIEW_STATE`, sets `LOG` (exporting `SESSIONVIEW_LOG` only when the
  user gave it, above), makes the dirs (section 2) and runs the link
  step and the older move (sections 3 and 5). It is POSIX `sh`: `bin/sessionview` and
  `bin/sessionview-frame` are `sh`, the others `bash`.
- **Python: one function in `bin/tmux-sidebar`**, the only Python that reads
  or writes these paths. It returns `STATE`, `LOG` and whether `STATE` is the
  default, and it makes the dirs by the same rules as the shell (section 2):
  a sidebar started on its own, with no shell entry before it, must still
  find `N` and `LD` there at `0700`, or its first write and the create of
  `L` (section 3) fail. It replaces today's module-level default, its
  `os.makedirs`, and the `_migrate_state` copy. `state(name)` keeps its
  meaning. `log()` writes to `LOG`.

A dispatcher verb that is routed before `lib/state.sh` (help, `config` and the
other routed verbs) inherits neither variable, as today.

### The tests that hold it

- **Agreement.** For each environment below, run the shell rule
  (`lib/state.sh` sourced under `sh`, then print both variables) and the
  Python rule (without starting the sidebar's screen), each in a scratch
  `HOME`, and require the same `STATE` and `LOG`. Then feed each answer back
  in and require the same answer again (the fixed point). The environments:
  neither variable set; `SESSIONVIEW_STATE` only; `SESSIONVIEW_LOG` only;
  both; each set to the empty string; `SESSIONVIEW_STATE` set to `N` as a
  string; set to `O` as a string; a value holding a literal `~`; a value with
  a trailing slash; a `HOME` that ends in `/`. After the shell rule runs
  with `SESSIONVIEW_LOG` unset or empty, `SESSIONVIEW_LOG` is not in the
  environment it exports.
- **No log leak.** A child started from an entry script's environment (the
  default resolved and exported) that sets only `SESSIONVIEW_STATE` to a
  scratch dir writes its log to `$STATE/sessionview.log`, never to `L`.
- **No hand copy.** A guard reads the code lines of `bin/` and `lib/` and
  allows the strings `.sessionkit/view/state`, `.sessionkit/view/log` and
  `.local/state/sessionview` only in `lib/state.sh` and the one resolver
  function in `bin/tmux-sidebar`. Comments that name an old path say "the old
  state dir" instead.

## 2. The new defaults and their modes

- `STATE` defaults to `N`. `LOG` defaults to `L` (rule 2).
- `N` and `LD` are made mode `0700`. Their parents (`~/.sessionkit`,
  `~/.sessionkit/view`) are made as `mkdir -p` makes them; they may exist
  already, holding the settings.
- The shell rule and the Python rule each make `N` always when `STATE` is
  `N`, and make `LD` when `LOG` is `L`. A fresh home therefore has both dirs after its first start,
  and nothing is written under `O` or `H`.
- An existing `N` or `LD` is set to `0700` on each start. They are
  sessionview's own dirs at its own paths.
- A dir the user named (`$SESSIONVIEW_STATE`, or the dir of
  `$SESSIONVIEW_LOG`) is made `0700` when sessionview has to make it, and an
  existing one is never re-moded.
- Each file sessionview creates in its state dir and its log dir is made
  `0600`, and each dir it makes there (`mutt/`) `0700`, whichever dir that
  is: `N`, `LD`, or a dir the user named. The mode is given at the create,
  in each writer: `os.open(..., 0o600)` in Python, a `umask 077` scoped to a
  subshell around the one write in shell. Never a process umask: a umask is
  inherited by every child, the user's tmux server among them, and a tmux
  server started under `077` gives it to every pane it ever opens.
- A file that already exists keeps its mode and its inode. Every writer
  writes in place (section 3), and a create mode applies only to a create.
  The `0700` dirs are the guard.
- At the default only (`STATE` is `N`), `O` is set to `0700` on each start,
  by `lib/state.sh` only, never through a symlink. A linked file's old name
  sits in `O` on the same inode as its name in `N`, so `O` must guard it as
  `N` does. Only the dir: no file in `O` is re-moded. When `STATE` is a dir
  the user named, `O` is not touched.

## 3. The old-path fallback and the one-time link step

### When it applies

Only when `STATE` is `N`. A state dir the user named is never linked from
and never read through a fallback, and neither is a process that inherited
`O`. Older code still running (a sidebar, or its supervisor reloading the
new sidebar with `O` still exported), and new code that inherited `O`
(section 1), keep using `O` until started fresh. Nothing signals or restarts
them, and the link step keeps them correct: "Processes that hold `O`", below.

### Link, never move

The state files are not moved out of `O`. Each one is hard-linked into `N`
with `link(2)`, and its name in `O` is never unlinked. `O/<name>` and
`N/<name>` are then two names for one file (one inode). A write through
either name is seen through the other.

This is the rule because a running sidebar keeps its old paths until its
next start and must stay correct until then, and it may not be restarted or
signalled. If the files left `O`, a process at `O` would list no recents and
show the configured picker order, not the one last flipped. With the files
linked, it sees every change a process at `N` makes, and the other way
round.

Two other ways were weighed and turned down. Accepting that loss and
naming it at each host's update leaves a running older sidebar wrong. Reading
a value equal to `O` as the default heals new code that inherited `O`, but
not older code still running. Only the link keeps the older code correct.

### What is linked, and what never is

The link set is exactly these names, from `O` into `N`:

- `recent.tsv`
- `picker-order`
- `sidebar-mail.txt`
- every regular file in `mutt/`, into a new `N/mutt/` (section 4)

Everything else in `O` stays only in `O`, and nothing of it is linked:
`sessionview.log`, `sidebar-mouse.log` and any other log, the frame pins
`frame-<pid>.tty` and `frame.tty`, and the per-run evidence files
`sidebar-remote-<host>.json` and `plugin-<id>-<action>.txt`. A running frame
removes its own pin, by its old path, when it exits. Nothing in the code
writes an `ssh-cm-*` socket any more; one left from an older version also
stays.

`O` itself is never removed. It keeps the logs, the pins, the pointer line
below, and the old names of the linked files. It is set to `0700` on each
start (section 2): a linked file's old name opens the same inode as its name
in `N`, and a file in `O` can be reached only through `O`. A same-user chmod
of the dir moves, links and truncates nothing, and a process still running
at `O` keeps every access it had. An uninstall removes it with
its own line, as today. That removes only the old names: the files live on
through their names in `N`, which the uninstall removes with its own line.

### Every writer of a linked file writes in place

The link holds only while every writer changes the file through the name it
opens. A grep of `bin/`, `lib/`, `src/`, `plugins/` and `tmux/` for the
linked names (and for `mutt`) finds exactly four writers, and all four
write in place. The same grep for `rename`, `os.replace`, `mv`, `mktemp`
and `tempfile` finds no write to state by replacement. The one `os.replace`
writes the settings file (`bin/sessionview-config`), not state. The
`rename`s and `mv`s are the move from `H` (section 5), which runs before
anything is linked. The four writers:

| file | writer | how it writes |
|---|---|---|
| `recent.tsv` | `bin/sessionview-session` (the session verb) | appends (`>>`) |
| `picker-order` | `bin/tmux-sidebar` (the picker flip) | opens for write (`open(..., "w")`) |
| `sidebar-mail.txt` | `bin/tmux-sidebar` (`mail()`) | opens with `O_TRUNC` |
| `mutt/<box>.rc` | `bin/sessionview-messages` | truncates (`>`) |

A writer that wrote a temp file and renamed it over the name (the usual
"atomic replace") would give that name a new inode. The other name would
keep the old one, and the two would split without a word. So:

- Each of these writers carries a code comment that says it must write in
  place, and why: the file may have a second name in the other dir.
- Two tests pin it (below). One runs each named writer against a linked
  pair. The other greps the code, so a new writer, or a writer that starts
  replacing its file, cannot slip past the first one.
- Nothing deletes a linked file today. A future writer that does would
  remove one name only. The grep test refuses that too.

### Who links

**`lib/state.sh` only.** It runs the link step on every start where `STATE`
is `N` and `O` is a dir. When `O` is absent the whole check is one `test -d`.
There is no marker file: the step is idempotent (section 4), so running it
again costs a few `test`s and finishes a step that was cut short.

**The Python sidebar never links.** It resolves the paths and reads through
the fallback. Every way the sidebar starts in normal use runs `lib/state.sh`
first: the frame, the `sessionview sidebar` supervisor, and the tmux popup
and new-tab picker, which are bound inside a frame that already ran it.
Keeping the step in one language keeps one copy of it, and only one
implementation to race. The cost: a sidebar started on its own, with no
shell entry ever run in a home that has only `H`, sees no recents until a
shell entry runs. That home predates every release.

### The fallback (Python, the only reader of the linked files)

The link step can leave a name unlinked: it has not run yet (a sidebar
started on its own), it failed (section 4), or `N/<name>` already held a
different file. The reader covers all three.

- **`recent.tsv`** is read from both files when `STATE` is `N`: `O/recent.tsv`
  if it exists, then `N/recent.tsv`, keeping the latest time for each name,
  as the reader already does within one file. When the two names are one
  file (`os.path.samefile`), it is read once. Recents are never lost,
  however the files were split.
- **`picker-order`** is read from `N` when it exists, else from `O`.
- **`sidebar-mail.txt`** and **`mutt/`** need no fallback. Each is written
  before it is read, in the same run.
- **Every write goes to `N`.** The session verb appends `recent.tsv` there,
  and the sidebar writes `picker-order` and `sidebar-mail.txt` there. When
  the name is linked, the write reaches `O` too.

### Processes that hold `O`

A process that holds `O` (older code, or new code that inherited `O`) reads
and writes `O/recent.tsv` and `O/picker-order`. Once those are linked, they
are the same files a process at `N` reads and writes, so:

- it lists every recent, including the ones recorded at `N` after the link
  step;
- it shows the picker order last flipped by either process;
- a line it appends, or an order it flips, is seen at once by a process at
  `N`.

Where a name could not be linked, a process at `O` sees only `O`'s copy,
exactly as before this change, and a process at `N` reads `O`'s copy
through the fallback. Nothing is lost in either case.

### The log lines

The log file itself is never moved, linked, copied or truncated. The lines
below are written once per home, by the sidebar (the only writer of the
log):

- When `STATE` is `N` and `LOG` is `L`, the sidebar creates `L` at its start
  with `O_CREAT|O_EXCL`. It creates it at start, not at the first error, so a
  person watching the old file is told even when nothing goes wrong.
- Only the process whose create succeeded writes these lines:
  - **The pointer lines**, only if `O/sessionview.log` exists: one line into
    `L` that names `O/sessionview.log`, and one line appended to
    `O/sessionview.log` that names `L`. It never creates the old file to
    write the pointer.
  - **The link-failure line**, only if a name was left unlinked: one line
    into `L` naming each of `recent.tsv` and `picker-order` that is a
    regular file in `O` with no file of that name in `N`, and saying they
    are read from `O` through the fallback. "A regular file in `O` and
    nothing in `N`" is exactly what a failed `link(2)` leaves; an `EEXIST`
    leaves a file in `N` and is not a failure. The sidebar measures this
    itself, from the two dirs, so the shell needs no channel to the log.
- All of these lines have the shape every log line has (`<date> <time>
  sock=<sock> ...`) and are written at every `log_level`.
- Any other process finds `L` there (`EEXIST`) and writes nothing extra. A
  second start writes nothing.

Older code still running keeps writing the old log file until it is started
fresh. The pointer line is above those lines.

Two limits, named and accepted. The link-failure line is written once, at
the first start, so a link that fails only at a later start (a file that
older code makes in `O` after that start) is not logged; the fallback still
reads it. And a home with the default `STATE` and the user's own
`$SESSIONVIEW_LOG` gets none of these lines: the user chose that log path.

## 4. Race safety

The frame, a sidebar and a session verb can all start at the same moment,
and all of them can see that `N` does not exist yet. The design survives
that because no step depends on `N` being absent.

### Why not one rename of the whole dir, or of each file

The older move from `H` renames the whole dir when the new one is absent.
Reusing that shape here is wrong three times over. A whole-dir rename
carries the logs and the pins along, and those must stay. "The new dir is
absent" is exactly the check that two starters can both pass. And a rename
takes the files out of `O`, which section 3 rules out.

A per-file `rename(2)` is ruled out for the last reason, and for one more:
it silently replaces an existing target. A line the session verb appended to
a new `N/recent.tsv` in the instant between a check and a rename would be
lost. `link(2)` never replaces anything: of several starters, exactly one
link succeeds, and every other starter gets `EEXIST`.

### The step, for each name

For each name in the link set, `lib/state.sh` does:

1. If `O/<name>` is not a regular file, or is a symlink, leave it. A symlink
   is never followed or linked; the fallback reads through it.
2. If `N/<name>` exists in any form (`-e` or `-L`), it is done. An existing
   file in `N` is never overwritten, whether it is `O/<name>`'s inode (an
   earlier start, or another starter, linked it) or a different file.
3. `link(2)` `O/<name>` to `N/<name>` (`ln`, without `-f`).
4. If the link fails with `EEXIST` (another starter won between steps 2 and
   3), it is done, as in step 2.
5. If it fails any other way (`EXDEV` across filesystems, `EPERM`, a
   filesystem without hard links), leave `O/<name>` alone. The fallback
   reads it, and the sidebar logs it once (section 3).

Nothing is ever unlinked, so no step can lose a file, and a step cut short
at any point is finished by the next start.

`ln` gets a target that is checked not to exist first (step 2). If the
target were a dir, `ln` would link into it instead of failing. No writer
makes a dir at any of these names, and `N/mutt` is made before its files are
linked (below).

### `mutt/` is linked file by file

`mv O/mutt N/mutt` would put the dir inside `N/mutt` when `N/mutt` already
exists, which a concurrent `messages` verb can make at any moment, and it
would take the dir out of `O`. So `lib/state.sh` makes `N/mutt` (`0700`;
`EEXIST` is success) and links each regular file in `O/mutt` into it by the
step above. `O/mutt` stays, with its files. The files in `mutt/` are written
again each time the messages tab opens, so one left unlinked costs nothing.

### Failure is never fatal

Each step ends with `|| :` (`|| true`). A sourcing script may run under
`set -e`, and a step that fails there must not end it. An `EEXIST` is the
normal case for the starters that lose the race, not an error. A failed
step leaves the file in `O`, where the fallback finds it.

### Two starters, both seeing no `N`

Both run `mkdir -p` on `N`, and an `EEXIST` there is success. For each name,
one `ln` wins. The other finds `N/<name>` at step 2, or gets `EEXIST` at
step 4, and is done. With three starters it is the same. The end state is
the same in every order: every name in the link set is in both `N` and `O`
as one file, and the logs and pins are only in `O`, untouched.

A writer that starts in the middle does no harm. The session verb sources
`lib/state.sh` before it appends, so its own step has linked `recent.tsv`
(or found it linked) before its first write. A sidebar started on its own
can write `N/picker-order` before any shell links it; the later step then
finds `N/picker-order` (step 2), leaves both, and the reader takes `N`'s.

### Same filesystem

`N` and `O` are both under `$HOME`, so the link works and is atomic. A home
that spans filesystems (`O` symlinked onto another disk) gets `EXDEV` at step
3. Nothing is linked there, the fallback carries the old files, and the log
says so once.

### The tests that hold it

- **An upgrade home**, with `O` holding the link set, the logs, two pins and
  the evidence files: one start links every name. Each `N/<name>` is the
  same file as its `O/<name>` (`-ef`, link count 2). `O` keeps every name it
  had. The logs and pins are only in `O`. The pointer lines are written, one
  in each log, and no link-failure line.
- **A second start is a no-op.** Both listings, every inode and every mtime
  are unchanged, and no second pointer line appears.
- **The race**: several entry points started at once against one seeded home
  (a frame refused for want of a tty, the session verb with `--print`, and
  the shell rule sourced on its own), repeated. The end state is always the
  one above, and `recent.tsv` holds every line exactly once.
- **A step cut short**: `N/recent.tsv` already linked to `O/recent.tsv`, the
  other names not. The start links the rest and leaves `recent.tsv` as it
  was.
- **An existing different file**: `N/recent.tsv` already holds other lines.
  Both files stay, unchanged, the picker lists the names from both, and no
  link-failure line is written.
- **A failed link**: an `ln` on `PATH` that always fails, before the first
  start. `O` is unchanged, `N` holds none of the link set, the picker lists
  `O`'s recents and order through the fallback, and `L` holds one
  link-failure line naming `recent.tsv` and `picker-order`. A second start
  adds no line.
- **Processes that hold `O` stay correct.** After the link step, the session
  verb run with `SESSIONVIEW_STATE` set to `O` appends a name, and the
  sidebar at `N` lists it. A picker flip at `N` is read by the sidebar's
  reader at `O`, and a flip at `O` by the reader at `N`.
- **Every writer writes in place.** For each of the four writers above, with
  `N/<name>` seeded as a hard link of `O/<name>`, run the writer at `N` and
  then at `O`. After each, the two names are still one file (same inode,
  link count 2) and both read the new content. A writer that replaced its
  file by rename fails this test. The test names its four writers
  (`bin/sessionview-session` for `recent.tsv`, `bin/tmux-sidebar`'s picker
  flip for `picker-order` and its `mail()` for `sidebar-mail.txt`,
  `bin/sessionview-messages` for `mutt/<box>.rc`) in one list, which the
  grep test below reads.
- **No writer is missed (the grep).** A test reads the code lines of
  `bin/`, `lib/`, `src/`, `plugins/` and `tmux/` and finds every line that
  names a linked file (`recent.tsv`, `picker-order`, `sidebar-mail.txt`, or
  the state dir's `mutt`, as in `$SESSIONVIEW_STATE/mutt`; `neomutt` is not
  a match). Each line must be on the test's own list, which says what the
  line is: a writer on the named list, a reader, the link step in
  `lib/state.sh`, or a line that names the file and touches nothing (the
  picker's `picker-order` action key in `bin/tmux-sidebar`). A line that is
  not on the list fails the test, with its file and line. The same test fails on any
  `rename`, `os.replace`, `os.rename`, `mv`, `unlink`, `os.remove`, `rm`,
  `mktemp` or `tempfile` whose target is under `STATE`, except the move
  from `H` in `lib/state.sh` (section 5). A new writer therefore lands only
  by adding it to the list, which puts it under the in-place test above.
- **The uninstall keeps the state.** After the link step, the uninstall's
  old-dir line (`rm -rf` of `O`) leaves every file in `N` with its content.
- **The fallback**, through a shell entry point and through Python. Before
  any link step, with `STATE` at `N`, the sidebar lists the recents and the
  picker order from `O`. That holds when the sidebar is started by the
  `sessionview sidebar` supervisor (shell) and when it is started on its own
  (Python). No shell script reads a linked file. The shell's own part of the
  test is that the session verb appends to `N` only, and leaves
  `O/recent.tsv` readable when the link failed.
- **An explicit `$SESSIONVIEW_STATE`**, and one set to the string `O`:
  nothing is linked, nothing is read from `O` by fallback, no pointer line
  is written, and the log is `$STATE/sessionview.log`.
- **A fresh home**: after one start, `N` and `LD` exist at `0700`, and
  neither `O` nor `H` exists.
- **Private modes**, every child started at umask `022`: on a fresh home
  each writer (the picker flip, `mail()`, the remote evidence, the pin, the
  log, a plugin body, the session verb, `sessionview-messages`, and the
  frame's own pin) makes a `0600` file, and every dir under `N` and `LD` is
  `0700`. An upgrade home with `O` at `0755` has `O` at `0700` after one
  start, and every file in `O` keeps its mode; a second start leaves it
  `0700`. A symlinked `O` is never followed: its target keeps its mode. A
  named state dir at `0755`, with a `0644` file in it, keeps both modes and
  the file's inode, a new file there is `0600`, and `O` is not touched. The
  process umask is still `022` after `lib/state.sh` and after the sidebar's
  start. A log file is created `0600`, at `L`, at `$SESSIONVIEW_LOG` and in
  a named state dir; an existing `0644` log keeps its mode and inode.

## 5. How the older move from `H` chains in

Today, `lib/state.sh` and a Python copy in `bin/tmux-sidebar` move `H` once.
When `STATE` is `O`, `O` does not exist and `H` is a dir, they rename `H` to `O`.
Inside it they rename `herd-recent.tsv` to `recent.tsv` and `herd.tty` to
`frame.tty`.

After this change:

- The `H` step stays in `lib/state.sh` only. The Python copy is deleted.
- It runs when `STATE` is `N` (the default, as everywhere in this note), and
  still targets `O`. It runs **before** the link step. A home from that era
  therefore goes `H` to `O`, then has its state linked from `O` into `N`, in
  one start. `H` is renamed to `O` whole, which is safe there: `H` holds only
  files from that era and `O` does not exist yet. Then the link set is
  linked from `O` into `N` by section 4. `frame.tty` is a pin, so it stays
  only in `O`. The sidebar reads `state("frame.tty")` only when
  `SESSIONVIEW_PIN` is unset, and after this change it looks in `N`, so it
  never finds that old file. Nothing in the code writes `frame.tty` (each
  frame writes its own `frame-<pid>.tty` and passes it as
  `SESSIONVIEW_PIN`), so nothing is lost. The state change leaves this as
  it is: it neither links `frame.tty` nor reads it through the fallback.
- Its whole-dir rename keeps its check that `O` is absent. Two starters can
  both pass that check. The second `mv` then finds `H` gone and fails, which
  the `|| :` absorbs. New code creates `O` only in a process that holds `O`
  (it makes its own `STATE`), and a home where that happens already ran
  older code, which moved `H` itself. So in practice `mv` cannot find an `O`
  that exists and move `H` inside it.
- The two inner renames get the same `|| :`. Today, under `set -e`, a lost
  race on one of them would end the sourcing script. They stay renames: they
  run inside the dir just renamed from `H`, before anything links from it.

Test: a home with only `H` (`herd-recent.tsv`, `herd.tty`, `mutt/`) ends
with `recent.tsv` and the `mutt/` files in both `O` and `N` as one file each,
`frame.tty` only in `O`, and no `H`.

## Out of scope here

- The docs and the CHANGELOG follow these paths in their own change.
- Linking a host's live files is a deploy, with its own go per host. The link
  step runs on the first start of the new code, so updating a host's checkout
  is that host's step. A merge links and moves nothing.
- A popup started by a tmux binding gets the tmux server's environment. An
  explicit `$SESSIONVIEW_STATE` given only to the frame does not reach it
  today, either. This change leaves that as it is.
