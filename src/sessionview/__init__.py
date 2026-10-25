"""sessionview - a sidebar for tmux.

The tools are the scripts shipped under _data/ (bin, lib, config, tmux,
plugins, macos), laid out as in the repo. Each console script runs its
namesake from _data/bin, with SESSIONVIEW_ROOT pointing there and
SESSIONVIEW_PYTHON set to this interpreter (3.11+), so no tool depends on
which python3 comes first on PATH.
"""
import os
import sys
from pathlib import Path

__version__ = "0.3.1"

DATA = Path(__file__).resolve().parent / "_data"
PUBLIC = ("sessionview", "sessionview-config", "sessionview-session", "sessionview-messages")


def main() -> None:
    name = os.path.basename(sys.argv[0])
    if name not in PUBLIC:
        name = "sessionview"
    tool = DATA / "bin" / name
    os.environ["SESSIONVIEW_ROOT"] = str(DATA)
    os.environ.setdefault("SESSIONVIEW_PYTHON", sys.executable)
    os.execv(str(tool), [str(tool), *sys.argv[1:]])
