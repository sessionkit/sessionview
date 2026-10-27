# lib/landing.sh - sourced by sessionview-frame. Which session a bare
# `sessionview` lands in: run OUTSIDE tmux, with no SESSION named. (Named, it
# is that session; inside tmux, the caller's own. Neither comes here.)
#
# sv_landing SOCK sets SV_LANDING to a session that already exists on tmux
# server SOCK and returns 0, or returns 1 when that server has no session at
# all (no server, or an empty one): only then does the frame make `main`.
# It reads tmux and `session`, and changes nothing.
#
# The rule: the first rung that answers wins.
#   1. The default seat's session: the tmux session on SOCK holding the pane
#      of the live default seat (`session agent default` names its agent,
#      `session list --json` gives that agent's tmux_socket and tmux_pane).
#      The newcomer's case: the one thing worth looking at is the assistant
#      just started, and the sidebar's rows are agents. It is also the same
#      answer every time.
#   2. The most recently attached session (#{session_last_attached}; a
#      switch-client counts, so the sidebar's own jumps do): where you were.
#   3. The newest session (#{session_created}), when none was ever attached:
#      one made by a script or an agent, likeliest the one just made for you.
# Rungs 2 and 3 are one sort: never-attached counts as 0, then newest first.
# The sort is stable, so same-second ties keep tmux's own order (by name)
# and the answer is deterministic.
#
# Every rung fails open to the next: `session` or a Python missing, a seat not
# running, not in tmux or on another server, a parse failing. The worst case
# is the old behaviour, `main`.
sv_landing() {
  SV_LANDING=""
  _sv_l_sock="$1"
  _sv_l_rows="$(tmux -L "$_sv_l_sock" list-sessions \
    -F '#{?session_last_attached,#{session_last_attached},0} #{session_created} #{session_name}' 2>/dev/null)" || return 1
  [ -n "$_sv_l_rows" ] || return 1
  # 1. the default seat's session
  if command -v session >/dev/null 2>&1 && [ -n "${SESSIONVIEW_PYTHON:-}" ]; then
    _sv_l_agent="$(session agent default 2>/dev/null | head -n 1)"
    if [ -n "$_sv_l_agent" ]; then
      # Pane ids are per server, so the seat's socket must be this one.
      _sv_l_panes="$(session list --json 2>/dev/null | "$SESSIONVIEW_PYTHON" -c '
import json, re, sys
try:
    rows = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if not isinstance(rows, list):
    sys.exit(0)
for r in rows:
    if not isinstance(r, dict):
        continue
    pane = r.get("tmux_pane") or ""
    if r.get("agent") == sys.argv[1] and r.get("tmux_socket") == sys.argv[2] and re.fullmatch(r"%[0-9]+", pane):
        print(pane)
' "$_sv_l_agent" "$_sv_l_sock" 2>/dev/null)"
      for _sv_l_pane in $_sv_l_panes; do
        _sv_l_name="$(tmux -L "$_sv_l_sock" display -p -t "$_sv_l_pane" '#{session_name}' 2>/dev/null)"
        if [ -n "$_sv_l_name" ] && tmux -L "$_sv_l_sock" has-session -t "=$_sv_l_name" 2>/dev/null; then
          SV_LANDING="$_sv_l_name"
          return 0
        fi
      done
    fi
  fi
  # 2 and 3. last attached, else newest. The name is everything after the
  # second space: a session name may hold spaces.
  SV_LANDING="$(printf '%s\n' "$_sv_l_rows" | sort -s -k1,1nr -k2,2nr | sed -n '1s/^[^ ]* [^ ]* //p')"
  [ -n "$SV_LANDING" ]
}
