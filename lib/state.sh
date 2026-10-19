# lib/state.sh - sourced by each entry script once SESSIONVIEW_STATE is set.
# Makes the state dir, first moving it from its pre-release name
# (~/.local/state/herd) when only the old one exists. A frame started by the
# old code keeps writing to the old dir until it is restarted.
_sv_old="$HOME/.local/state/herd"
if [ "$SESSIONVIEW_STATE" = "$HOME/.local/state/sessionview" ] && [ ! -e "$SESSIONVIEW_STATE" ] && [ -d "$_sv_old" ]; then
  if mv "$_sv_old" "$SESSIONVIEW_STATE" 2>/dev/null; then
    [ -e "$SESSIONVIEW_STATE/herd-recent.tsv" ] && mv "$SESSIONVIEW_STATE/herd-recent.tsv" "$SESSIONVIEW_STATE/recent.tsv"
    [ -e "$SESSIONVIEW_STATE/herd.tty" ] && mv "$SESSIONVIEW_STATE/herd.tty" "$SESSIONVIEW_STATE/frame.tty"
  fi
fi
unset _sv_old
mkdir -p "$SESSIONVIEW_STATE"
