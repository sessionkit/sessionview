"""sessionview - a sidebar for tmux.

The tools are the scripts shipped under _data/ (bin, lib, config, tmux,
plugins, macos), laid out as in the repo. The one console script,
sessionview, runs _data/bin/sessionview, with SESSIONVIEW_ROOT pointing
there and SESSIONVIEW_PYTHON set to this interpreter (3.11+), so no tool
depends on which python3 comes first on PATH. Every other tool is reached
through it (`sessionview config`, `sessionview session`, ...), never by its
own name: whatever argv[0] says, this runs bin/sessionview.
"""
import os
import sys
from pathlib import Path

__version__ = "0.4.0"

DATA = Path(__file__).resolve().parent / "_data"
PUBLIC = ("sessionview",)


def main() -> None:
    tool = DATA / "bin" / PUBLIC[0]
    os.environ["SESSIONVIEW_ROOT"] = str(DATA)
    os.environ.setdefault("SESSIONVIEW_PYTHON", sys.executable)
    os.execv(str(tool), [str(tool), *sys.argv[1:]])
