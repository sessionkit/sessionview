"""Shared helpers for the suite: where the checkout is, a scratch HOME, and
running one of its tools inside that HOME.

Isolation is the point. scratch_env() builds the child's environment from a
short allow-list (PATH, LANG) plus a fresh temporary HOME, and drops anything
that could point a tool back at a real install: SESSIONVIEW_ROOT, SESSIONVIEW_STATE,
SESSIONVIEW_CONFIG, SIDEBAR_CONFIG, XDG_*. A test that needs one of those sets
it on the dict it gets back.

The Python is decided by the suite, never by the tool's probe: scratch_env()
sets SESSIONVIEW_PYTHON to the interpreter running the suite, as the wheel's
console scripts do (SV-172). So a bin/ tool a test runs never depends on what
python3.x happens to be on PATH. A test OF the probe removes that named key
itself: env.pop("SESSIONVIEW_PYTHON").

tmux is a documented prerequisite, not a dependency the suite can supply.
Without it, a test that needs it is a LOUD skip that names tmux (TMUX_SKIP),
never a FileNotFoundError: PrivateTmux.tmux() and require_tmux() raise it.
"""
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

#: The checkout under test: the parent of tests/.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(REPO, "bin")
PLUGINS = os.path.join(REPO, "plugins")
CONFIG = os.path.join(REPO, "config")

#: The only variables a child inherits from the caller.
KEEP = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")

#: The skip reason when tmux is not on PATH. Loud on purpose: it names the
#: prerequisite and how to get it, so a skip count is never mistaken for a pass.
TMUX_SKIP = "SKIPPED: needs tmux, which is not on PATH (a prerequisite: brew install tmux)"


@contextlib.contextmanager
def scratch_env(**extra):
    """Yield (env, home): a child environment whose HOME is a new empty
    directory, removed afterwards. **extra is added on top."""
    # ignore_cleanup_errors: a private server's pane shells get SIGHUP from
    # kill-server and may still write (shell history) into HOME while it is
    # removed - "Directory not empty", once in a make test (SV-92 do-002).
    with tempfile.TemporaryDirectory(prefix="sessionview-test-", ignore_cleanup_errors=True) as home:
        env = {k: os.environ[k] for k in KEEP if k in os.environ}
        env["HOME"] = home
        env["SESSIONVIEW_PYTHON"] = sys.executable
        env.update(extra)
        yield env, home


def run(tool, *args, env, timeout=30):
    """Run bin/TOOL with ARGS under ENV, with the interpreter running this
    suite for a python tool (so `make test` decides the Python, not the
    tool's shebang). Returns the CompletedProcess, text mode."""
    path = os.path.join(BIN, tool)
    argv = [path, *args]
    if script_kind(path) == "python":
        argv = [sys.executable, "-B", *argv]
    return subprocess.run(argv, env=env, capture_output=True, text=True,
                          timeout=timeout, cwd=REPO)


def script_kind(path):
    """'python', 'bash' or 'sh' from the shebang, else None."""
    try:
        with open(path, "rb") as f:
            first = f.readline().decode("utf-8", "replace").strip()
            second = f.readline().decode("utf-8", "replace").strip()
    except OSError:
        return None
    # A Python tool behind the sh trampoline that finds a Python 3.11+.
    if first == "#!/bin/sh" and second == "\'\'\':\'":
        return "python"
    if not first.startswith("#!"):
        return None
    words = first[2:].split()
    if not words:
        return None
    prog = os.path.basename(words[1] if os.path.basename(words[0]) == "env" and len(words) > 1 else words[0])
    if prog.startswith("python"):
        return "python"
    if prog in ("bash", "sh"):
        return prog
    return None


def scripts():
    """Every script shipped in bin/ and plugins/*/, as (path, kind)."""
    out = []
    dirs = [BIN] + sorted(os.path.join(PLUGINS, d) for d in os.listdir(PLUGINS)
                          if os.path.isdir(os.path.join(PLUGINS, d)))
    for d in dirs:
        for name in sorted(os.listdir(d)):
            p = os.path.join(d, name)
            kind = script_kind(p) if os.path.isfile(p) else None
            if kind:
                out.append((p, kind))
    return out


# -- tmux on a PRIVATE socket only (SV-92) --------------------------------------
# The rule is enforced HERE, not left to each test: a developer's machine runs
# their own screen and agents on the default server, and live windows on a
# second store's server. TMUX_TMPDIR is a scratch dir, so even a stray
# `-L default` resolves to a socket that does not exist there; TMUX is never
# passed on; the socket is `sv-test-<tag>-<pid>`; kill-server only ever runs
# with -L that name and that TMUX_TMPDIR. No test passes -S or names default.

def have_tmux():
    return shutil.which("tmux") is not None


def require_tmux():
    """Skip the running test, loudly naming tmux, when tmux is not on PATH."""
    if not have_tmux():
        raise unittest.SkipTest(TMUX_SKIP)


class PrivateTmux:
    """A private tmux server: `sock` (the -L name), `tmpdir` (its TMUX_TMPDIR),
    `env(base)` (a child env pointed at it), `tmux(*args)` (run one command
    there; returns the CompletedProcess)."""

    def __init__(self, tag, tmpdir):
        self.sock = f"sv-test-{tag}-{os.getpid()}"
        assert self.sock.startswith("sv-test-"), self.sock
        self.tmpdir = tmpdir

    def env(self, base=None):
        e = dict(base if base is not None else {k: os.environ[k] for k in KEEP if k in os.environ})
        e.pop("TMUX", None)
        e.pop("TMUX_PANE", None)
        e["TMUX_TMPDIR"] = self.tmpdir
        return e

    def tmux(self, *args, env=None):
        assert "-S" not in args and "default" not in args, args
        require_tmux()
        return subprocess.run(["tmux", "-L", self.sock, *args], env=self.env(env),
                              capture_output=True, text=True, timeout=30)

    def alive(self):
        return self.tmux("list-sessions").returncode == 0

    def sessions(self):
        r = self.tmux("list-sessions", "-F", "#{session_name}")
        return r.stdout.split() if r.returncode == 0 else []

    def windows(self, session):
        """[(index, name, active)] of SESSION, in index order."""
        r = self.tmux("list-windows", "-t", f"={session}", "-F",
                      "#{window_index}\t#{window_name}\t#{window_active}")
        out = []
        for line in r.stdout.splitlines():
            i, n, a = line.split("\t")
            out.append((int(i), n, a == "1"))
        return out


@contextlib.contextmanager
def private_tmux(tag):
    """Yield a PrivateTmux on a fresh scratch TMUX_TMPDIR; kill its server
    and remove the dir afterwards. The dir is short on purpose: a unix socket
    path is capped at ~104 bytes and macOS's $TMPDIR alone is ~50."""
    d = tempfile.mkdtemp(prefix="svt-", dir="/tmp" if os.path.isdir("/tmp") else None)
    t = PrivateTmux(tag, d)
    try:
        yield t
    finally:
        # No tmux, no server to kill: this cleanup must not turn a skip into
        # an error.
        if have_tmux():
            subprocess.run(["tmux", "-L", t.sock, "kill-server"], env=t.env(),
                           capture_output=True, text=True, timeout=30)
        shutil.rmtree(d, ignore_errors=True)


# -- fixture stores and the shims that answer for them (SV-92) -------------------
# Identity = dir name. The layouts mirror the three real stores (design §0,
# measured read-only) plus one with neither project dir.
STORE_LAYOUTS = {
    #               project dir under projects/   slipbox scripts mailbox
    "fx-corp": ("store",      False, False, True),
    "fx-legacy":   ("store",      True,  True,  True),
    "fx-named":    ("fx-named",   True,  True,  True),
    "fx-bare":     (None,         True,  False, False),
}

_TM_SHIM = r'''#!{python}
# tm, for the suite: answers from the fixture file, logs every call, and
# boots ONLY an sv-test- socket under the scratch TMUX_TMPDIR.
import json, os, subprocess, sys
FIX = json.load(open({fixtures!r}))
with open({log!r}, "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
if a[:2] == ["store", "list"]:
    print(json.dumps(FIX["stores"])); sys.exit(0)
if a[:2] == ["project", "list"]:
    store = a[a.index("--store") + 1] if "--store" in a else ""
    for s in FIX["stores"]:
        if os.path.realpath(s["path"]) == os.path.realpath(store):
            print(json.dumps([{{"name": n}} for n in FIX["projects"][s["store"]]])); sys.exit(0)
    print("[]"); sys.exit(0)
if a[:2] == ["store", "boot"] and len(a) > 2:
    rec = next((s for s in FIX["stores"] if s["name"] == a[2]), None)
    if rec is None:
        print(f"tm: no store {{a[2]}}", file=sys.stderr); sys.exit(2)
    sock = rec["socket"]
    assert sock.startswith("sv-test-"), sock
    env = dict(os.environ, TMUX_TMPDIR={tmpdir!r}); env.pop("TMUX", None)
    ident = rec["store"]
    T = ["tmux", "-L", sock]
    if subprocess.run(T + ["has-session", "-t", "=" + ident], env=env, capture_output=True).returncode != 0:
        subprocess.run(T + ["new-session", "-d", "-s", ident, "-e", "TASKMASTER_STORE=" + ident], env=env, check=True)
    subprocess.run(T + ["set-environment", "-g", "TASKMASTER_STORE", ident], env=env, check=True)
    sys.exit(0)
sys.exit(0)    # anything else (`tm task list` typed into a tab): quietly nothing
'''

_MESSAGE_SHIM = r'''#!{python}
# message, for the suite: `path NAME` answers for the fixture boxes only.
import json, sys
BOXES = json.load(open({fixtures!r}))["boxes"]
a = sys.argv[1:]
if a[:1] == ["path"]:
    if len(a) > 1 and a[1] in BOXES:
        print(BOXES[a[1]]); sys.exit(0)
    print(f"message: no box {{a[1] if len(a) > 1 else ''}}", file=sys.stderr); sys.exit(2)
sys.exit(0)
'''


class StoreFixtures:
    """Fixture stores under BASE, shims in BASE/bin, all for one private
    socket. `path(id)`, `env(base_env)` (shims first on PATH, the scratch
    config and state), `log()` (the tm shim's calls)."""

    def __init__(self, base, ptmux, live=()):
        self.base, self.pt = base, ptmux
        self.bin = os.path.join(base, "bin")
        self.state = os.path.join(base, "state")
        self.logfile = os.path.join(base, "tm-shim.log")
        for d in (self.bin, self.state):
            os.makedirs(d, exist_ok=True)
        stores, projects, boxes = [], {}, {}
        for ident, (proj, slip, scr, mail) in STORE_LAYOUTS.items():
            root = os.path.realpath(os.path.join(base, "stores")) + "/" + ident
            os.makedirs(os.path.join(root, "projects", "alpha"), exist_ok=True)
            if proj:
                os.makedirs(os.path.join(root, "projects", proj), exist_ok=True)
                with open(os.path.join(root, "projects", proj, "PROJECT.md"), "w") as f:
                    f.write(f"---\nname: {proj}\n---\n")
            for flag, sub in ((slip, "slipbox"), (scr, "scripts")):
                if flag:
                    os.makedirs(os.path.join(root, sub), exist_ok=True)
            if mail:
                box = os.path.join(base, "mail", ident)
                for sub in ("new", "cur", "tmp"):
                    os.makedirs(os.path.join(box, sub), exist_ok=True)
                boxes[ident] = box
            projects[ident] = ["alpha"] + ([proj] if proj else [])
            stores.append({"name": ident, "store": ident, "path": root, "socket": ptmux.sock,
                           "live": ident in live, "session_count": 0})
        self.fixtures = os.path.join(base, "fixtures.json")
        with open(self.fixtures, "w") as f:
            json.dump({"stores": stores, "projects": projects, "boxes": boxes}, f)
        fill = dict(python=sys.executable, fixtures=self.fixtures, log=self.logfile, tmpdir=ptmux.tmpdir)
        for name, text in (("tm", _TM_SHIM), ("message", _MESSAGE_SHIM),
                           ("neomutt", "#!/bin/sh\nexit 0\n")):
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write(text.format(**fill) if "{python}" in text else text)
            os.chmod(p, 0o755)

    def path(self, ident):
        return os.path.realpath(os.path.join(self.base, "stores", ident))

    def env(self, base_env):
        e = self.pt.env(base_env)
        e["PATH"] = self.bin + os.pathsep + e.get("PATH", "")
        e["SESSIONVIEW_STATE"] = self.state
        e["SESSIONVIEW_CONFIG"] = os.path.join(self.base, "sessionview-config.json")
        e["VISUAL"] = "true"          # {editor} types a no-op, never a real nvim
        return e

    def log(self):
        try:
            with open(self.logfile) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []
