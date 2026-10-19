# lib/python.sh - sourced by the entry scripts (sessionview, -frame, -session,
# -install, -newtab, -autostart). Finds a Python 3.11+ ONCE and exports it as
# SESSIONVIEW_PYTHON, so every Python tool below runs on it without probing
# again. macOS puts Apple's 3.9 first on PATH, and the sidebar needs 3.11
# (tomllib). Order: SESSIONVIEW_PYTHON if set; the venv that installed a wheel
# copy; then PATH, newest first.
#
# The venv step locates the copy from "$0", which in a sourced file is the
# SOURCING script (sh has no BASH_SOURCE), resolved through symlinks. Not from
# SESSIONVIEW_ROOT: that may be inherited from another copy's environment.
# >>> venv probe: the venv that installed this copy, before PATH.
# Only for a wheel copy (site-packages/sessionview/_data); a checkout never
# matches, so it keeps the PATH order below. Same text in all four probe
# copies (lib/python.sh and the three trampolines); tests/test_venv_probe.py
# holds them equal.
if [ -z "${SESSIONVIEW_PYTHON:-}" ]; then
  _sv_v="$(readlink -f "$0" 2>/dev/null || echo "$0")"
  case "$_sv_v" in
    */site-packages/sessionview/_data/*)
      _sv_v="$(cd "$(dirname "$_sv_v")" 2>/dev/null && pwd -P)"
      while [ -n "$_sv_v" ] && [ "$_sv_v" != / ] && [ ! -f "$_sv_v/pyvenv.cfg" ]; do
        _sv_v="$(dirname "$_sv_v")"
      done
      if [ -n "$_sv_v" ] && [ -f "$_sv_v/pyvenv.cfg" ] && [ -x "$_sv_v/bin/python3" ] &&
          "$_sv_v/bin/python3" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
        SESSIONVIEW_PYTHON="$_sv_v/bin/python3"; export SESSIONVIEW_PYTHON
      fi ;;
  esac
  unset _sv_v
fi
# <<< venv probe
if [ -z "${SESSIONVIEW_PYTHON:-}" ]; then
  for _sv_p in python3.14 python3.13 python3.12 python3.11 python3; do
    command -v "$_sv_p" >/dev/null 2>&1 || continue
    if "$_sv_p" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
      SESSIONVIEW_PYTHON="$(command -v "$_sv_p")"; break
    fi
  done
  unset _sv_p
fi
[ -n "${SESSIONVIEW_PYTHON:-}" ] && export SESSIONVIEW_PYTHON
