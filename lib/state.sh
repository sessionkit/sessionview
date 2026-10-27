# lib/state.sh - sourced by every entry script that uses the state dir, after
# its own flags. THE rule for where sessionview keeps its state and its log,
# in shell; resolve_paths() in bin/tmux-sidebar holds the same rule in Python,
# and tests/test_log_home.py proves the two agree. The rule and its reasons:
# docs/decisions/state-and-log-home.md. POSIX sh: bin/sessionview and
# bin/sessionview-frame are sh. Every step that can fail ends in `|| :`, so a
# sourcing script under set -e never dies here.
#
# SESSIONVIEW_STATE, the state dir: $SESSIONVIEW_STATE when set and not empty,
# else the default, ~/.sessionkit/view/state. Exported, resolved. A value is
# used as given: no ~ is expanded, nothing is normalised. "The default" is a
# value, not an unset variable: a sidebar the frame starts sees it set.
#
# LOG, the log file (a shell variable):
#   - $SESSIONVIEW_LOG when it is set and not empty;
#   - else, when the state dir IS the default, ~/.sessionkit/view/log/sessionview.log;
#   - else $SESSIONVIEW_STATE/sessionview.log.
# SESSIONVIEW_LOG is exported only when the user gave it. The default is
# derived again by every process; exported, it would reach every pane of a
# tmux server a frame starts, and a child there that names only its own
# SESSIONVIEW_STATE would write the default log. Only bin/tmux-sidebar writes
# the log; this makes its dir.
#
# At the default only, and in this order:
#   1. the older move: the pre-release dir ~/.local/state/herd becomes the
#      old state dir, ~/.local/state/sessionview, when that is absent;
#   2. the old dir is set to 0700 (never through a symlink; no file in it is
#      re-moded), since a linked file's old name sits in it;
#   3. the link step: each state file in the old dir is hard-linked into the
#      new one, and its old name is never unlinked, so a sidebar still
#      running at the old dir (never restarted or signalled) sees every change
#      made at the new one, and the other way round. The logs and the frame
#      pins stay only in the old dir. Idempotent, and safe when several
#      entry points start at once: link(2) never replaces a file, so of
#      several starters exactly one link succeeds. A link that fails leaves
#      the old file where the sidebar's fallback read finds it.
_sv_n="$HOME/.sessionkit/view/state"
_sv_o="$HOME/.local/state/sessionview"
_sv_h="$HOME/.local/state/herd"
SESSIONVIEW_STATE="${SESSIONVIEW_STATE:-$_sv_n}"; export SESSIONVIEW_STATE

# One name of the link set, from the old dir into the new one (decision §4).
_sv_link() {
  # 1. only a regular file; a symlink is never followed or linked
  if [ ! -f "$_sv_o/$1" ] || [ -L "$_sv_o/$1" ]; then return 0; fi
  # 2. a name already in the new dir, in any form, is done: never overwritten
  if [ -e "$_sv_n/$1" ] || [ -L "$_sv_n/$1" ]; then return 0; fi
  # 3-5. link; EEXIST (another starter won) is done, any other failure
  # leaves the old file to the fallback
  ln "$_sv_o/$1" "$_sv_n/$1" 2>/dev/null || :
}

if [ "$SESSIONVIEW_STATE" = "$_sv_n" ]; then
  { mkdir -p -m 700 "$_sv_n" && chmod 700 "$_sv_n"; } 2>/dev/null || :
  if [ ! -e "$_sv_o" ] && [ -d "$_sv_h" ]; then
    if mv "$_sv_h" "$_sv_o" 2>/dev/null; then
      if [ -e "$_sv_o/herd-recent.tsv" ]; then mv "$_sv_o/herd-recent.tsv" "$_sv_o/recent.tsv" 2>/dev/null || :; fi
      if [ -e "$_sv_o/herd.tty" ]; then mv "$_sv_o/herd.tty" "$_sv_o/frame.tty" 2>/dev/null || :; fi
    fi
  fi
  if [ -d "$_sv_o" ]; then
    # The old dir is set to 0700 on every start, never through a symlink: a
    # linked file's old name sits in it, on the same inode as the new one.
    # Only the dir; no file in it is re-moded (decision section 2).
    [ -L "$_sv_o" ] || chmod 700 "$_sv_o" 2>/dev/null || :
    _sv_link recent.tsv
    _sv_link picker-order
    _sv_link sidebar-mail.txt
    # mutt/ is a dir: a fresh one in the new dir, each regular file linked
    # into it one by one. The old mutt/ is never moved or renamed.
    if [ -d "$_sv_o/mutt" ] && [ ! -L "$_sv_o/mutt" ]; then
      { [ -d "$_sv_n/mutt" ] || mkdir -m 700 "$_sv_n/mutt"; } 2>/dev/null || :
      if [ -d "$_sv_n/mutt" ] && [ ! -L "$_sv_n/mutt" ]; then
        for _sv_f in "$_sv_o/mutt"/* "$_sv_o/mutt"/.[!.]* "$_sv_o/mutt"/..?*; do
          _sv_link "mutt/${_sv_f##*/}"
        done
      fi
    fi
  fi
elif [ ! -d "$SESSIONVIEW_STATE" ]; then
  { mkdir -p -m 700 "$SESSIONVIEW_STATE" && chmod 700 "$SESSIONVIEW_STATE"; } 2>/dev/null || :
fi

if [ -n "${SESSIONVIEW_LOG:-}" ]; then
  LOG="$SESSIONVIEW_LOG"; export SESSIONVIEW_LOG
  _sv_ld="$(dirname "$LOG")"
  [ -d "$_sv_ld" ] || { mkdir -p -m 700 "$_sv_ld" && chmod 700 "$_sv_ld"; } 2>/dev/null || :
else
  unset SESSIONVIEW_LOG
  if [ "$SESSIONVIEW_STATE" = "$_sv_n" ]; then
    LOG="$HOME/.sessionkit/view/log/sessionview.log"
    _sv_ld="$HOME/.sessionkit/view/log"
    { mkdir -p -m 700 "$_sv_ld" && chmod 700 "$_sv_ld"; } 2>/dev/null || :
  else
    LOG="$SESSIONVIEW_STATE/sessionview.log"
  fi
fi
unset _sv_n _sv_o _sv_h _sv_ld _sv_f
unset -f _sv_link
