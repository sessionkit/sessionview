# lib/client.sh - sourced by an entry script that acts on "the tmux client
# this was run from": sessionview-frame's hand-over (detach-client -E) and
# sessionview-sidebar-toggle without --tty. One rule, in one place.
#
# sv_own_client sets SV_CLIENT (that client's tty) and SV_SESSION (the
# session that client shows: the caller's) and returns 0, or sets SV_REFUSAL (one neutral
# line saying why) and returns 1. It reads tmux and changes nothing.
#
# An untargeted `tmux display -p '#{client_tty}'` is NOT the caller's client.
# tmux answers with the most recently active client of the caller's session,
# and when that session has no client attached, of the WHOLE server: some
# other terminal. Even `display -t "$TMUX_PANE"` falls back that way. So:
#   1. stdin and stdout are terminals, and `tty` names one. A script or an
#      agent's shell that inherited TMUX and TMUX_PANE has neither.
#   2. that tty IS the pane's: `#{pane_tty}` of $TMUX_PANE. A process in a
#      pane has the pane's pty as its terminal (never the client's), so this
#      proves the caller is the process in that pane.
#   3. exactly one client is on a session that holds the pane's window. Not
#      only the session `display -t "$TMUX_PANE"` names: a window can be in
#      several sessions (a session group, `link-window`), and tmux names the
#      most recently active of them, so a count over that one session alone
#      handed over another terminal's client. None: no terminal shows the
#      pane. More than one: no way to tell which terminal is the caller's,
#      so refuse rather than guess.
sv_own_client() {
  SV_CLIENT=""; SV_SESSION=""; SV_REFUSAL=""
  if [ ! -t 0 ] || [ ! -t 1 ]; then
    SV_REFUSAL="not a terminal: run it from a terminal (stdin and stdout must be a tty)"; return 1
  fi
  _sv_own="$(tty 2>/dev/null)" || { SV_REFUSAL="not a terminal: run it from a terminal (no controlling tty)"; return 1; }
  if [ -z "${TMUX:-}" ] || [ -z "${TMUX_PANE:-}" ]; then
    SV_REFUSAL="not inside a tmux pane (TMUX or TMUX_PANE is empty)"; return 1
  fi
  _sv_sock="${TMUX%%,*}"
  _sv_tab="$(printf '\t')"
  _sv_info="$(tmux -S "$_sv_sock" display-message -p -t "$TMUX_PANE" "#{pane_tty}$_sv_tab#{window_id}$_sv_tab#{session_name}" 2>/dev/null)" || _sv_info=""
  _sv_ptty="${_sv_info%%"$_sv_tab"*}"; _sv_rest="${_sv_info#*"$_sv_tab"}"
  _sv_wid="${_sv_rest%%"$_sv_tab"*}"; _sv_name="${_sv_rest#*"$_sv_tab"}"
  if [ -z "$_sv_info" ] || [ "$_sv_ptty" != "$_sv_own" ]; then
    SV_REFUSAL="not this pane's terminal: $_sv_own is not the tty of pane $TMUX_PANE"; return 1
  fi
  # every session that holds this pane's window, then the clients on those
  _sv_sids="$(tmux -S "$_sv_sock" list-windows -a -F "#{window_id}$_sv_tab#{session_id}" 2>/dev/null \
    | awk -F "$_sv_tab" -v w="$_sv_wid" '$1 == w {printf "%s ", $2}')" || _sv_sids=""
  _sv_clients="$(tmux -S "$_sv_sock" list-clients -F "#{session_id}$_sv_tab#{client_tty}$_sv_tab#{session_name}" 2>/dev/null \
    | awk -F "$_sv_tab" -v s="$_sv_sids" 'BEGIN {n = split(s, a, " "); for (i = 1; i <= n; i++) ok[a[i]] = 1}
                                          ($1 in ok) {print $2 "\t" $3}')" || _sv_clients=""
  _sv_n="$(printf '%s\n' "$_sv_clients" | grep -c . || true)"
  if [ "$_sv_n" -eq 0 ]; then
    SV_REFUSAL="no terminal is attached to this session ($_sv_name)"; return 1
  fi
  if [ "$_sv_n" -gt 1 ]; then
    SV_REFUSAL="this session ($_sv_name) is open in more than one terminal (detach the others, or run it outside tmux)"; return 1
  fi
  SV_CLIENT="${_sv_clients%%"$_sv_tab"*}"; SV_SESSION="${_sv_clients#*"$_sv_tab"}"
  return 0
}
