# lib/pane-menu.sh - sourced by sessionview-frame, only when pane_menu is on.
#
# sv_frame_option_forward SOCK, on the frame's own tmux server SOCK: an Option
# + right-click (M-MouseDown3Pane) on a pane running a tmux client goes through
# to that client's server, where tmux/agent-menu.conf has the agent menu. Every
# other pane (the sidebar) keeps the binding SOCK already had.
#
# Without it the frame's server takes the Option-click itself: it shows its own
# stock menu for the pane that holds your tmux client, and your tmux never sees
# the click. The plain right-click needs nothing here: the frame's stock binding
# already forwards it, because a tmux client's pane has mouse mode on whenever
# your tmux has `mouse on`.
#
# How. The key's current binding is read back with list-keys and becomes the
# else-branch of one if-shell, so no copy of tmux's menu is kept here (a copy
# names flags a given tmux may not know, and one unknown flag rejects the whole
# bind). That binding is tmux's stock menu unless the user's ~/.tmux.conf
# changed it, and then theirs is kept. A key with no binding sends the click to
# the pane under the mouse, so its else-branch is `send-keys -M`, which does
# the same. A second call finds its own wrapper and changes nothing (a second
# frame on the same server).
#
# The separator step. list-keys prints a command SEQUENCE with ` \; ` between
# its commands. Inside braces that is a literal `;` argument, and the bind
# fails. So each ` \; ` becomes ` ; ` (and ` \;\; ` becomes ` ;; `). A `\;`
# inside a quoted string is printed as `\\;` and is left alone.
#
# Known limit: an argument that is exactly `;` (`send-keys ';'`) is printed as
# `\;` too, the same text as a separator. Nothing in the printed line tells the
# two apart: tmux's own round trip of that line, sourced back as a config line,
# loses the argument the same way. Then the bind fails (unknown command), the
# key keeps the user's binding, and the pass-through is not installed. A lone
# `;` as the binding's LAST word is fine.
#
# It runs "${TMUX_BIN:-tmux}" (the frame sets TMUX_BIN) and returns tmux's
# status; the frame fails open on it.

#: the pass-through, as bound: a pane running tmux gets the click
SV_FRAME_FORWARD="if-shell -F -t = '#{==:#{pane_current_command},tmux}' { select-pane -t = ; send-keys -M }"
#: how list-keys prints the start of the wrapper (double quotes)
SV_FRAME_FORWARD_SHOWN='if-shell -F -t = "#{==:#{pane_current_command},tmux}" { select-pane -t = ; send-keys -M }'

sv_frame_option_forward() {
  _sv_pm_cur="$("${TMUX_BIN:-tmux}" -L "$1" list-keys -T root M-MouseDown3Pane 2>/dev/null)" || _sv_pm_cur=""
  # bind-key [-r] -T root M-MouseDown3Pane COMMAND: keep -r, and COMMAND
  _sv_pm_r="$(printf '%s\n' "$_sv_pm_cur" | sed -n 's/^bind-key  *\(-r\)  *-T root  *M-MouseDown3Pane .*/\1 /p')"
  _sv_pm_body="$(printf '%s\n' "$_sv_pm_cur" \
    | sed -n 's/^bind-key  *\(-r  *\)\{0,1\}-T root  *M-MouseDown3Pane  *//p' \
    | sed 's/ [\\];[\\]; / ;; /g; s/ [\\]; / ; /g')"
  case "$_sv_pm_body" in
    "$SV_FRAME_FORWARD_SHOWN"*) return 0;;
    '') _sv_pm_body="send-keys -M";;
  esac
  # $_sv_pm_r is "-r " or empty, unquoted on purpose
  "${TMUX_BIN:-tmux}" -L "$1" bind-key $_sv_pm_r-T root M-MouseDown3Pane "$SV_FRAME_FORWARD { $_sv_pm_body }"
}
