"""`sessionview show FILE`: the frame's client goes where FILE is, and only it.

Every test runs on PRIVATE tmux servers (support.private_tmux: its own
TMUX_TMPDIR, so even tmux's "default" is private), with TMPDIR, HOME and
PATH cut down, so no real tmux server, Neovim or `tm` is reachable. The
frame is built here as sessionview-frame builds it: a session on its own
server whose main pane runs `tmux -L A attach`, named by the
@sessionview_main_pane option, and a pty client on the frame (the
terminal). The Neovims are real, headless-free ones in panes, listening on
sockets under the scratch TMPDIR; without nvim those tests are skipped.

What is proven:
  (a) the read-only verbs (--current, --target, --dry-run) send nothing:
      every client, window and pane on every server is the same after;
  (b) a file open in a Neovim on ANOTHER server: the client moves there
      (detach-client -E), lands on that window and pane, and the Neovim
      shows the file; a second run sends nothing, and --porcelain names
      the place and the Neovim's socket on one line;
  (c) the same server, another session: switch-client, and only the
      frame's client moves (another terminal on the first session stays);
  (d) another pane zoomed in the target window: the zoom is undone;
  (e) no frame, or only a frame no terminal shows: exit 3, nothing moved;
  (f) a file no rule names and no Neovim has: exit 3, nothing moved;
  (g) a dead tmux socket beside the live ones never hangs it;
  (h) two frames: the one whose terminal was used most recently moves;
  (i) a project file whose session and editor window do not exist: both are
      made (by sessionview-session, on the project's server and store), the
      result names them first, and the frame lands on the file; a second run
      makes and sends nothing.
"""
import json
import os
import shutil
import socket
import subprocess
import time
import unittest

from tests import support
from tests.test_frame_hijack import PtyClient, wait_for, fcntl

TOOL = "sessionview-show"
NVIM_WAIT = 30    # the whole wait for a pane's Neovim to answer
NVIM_TRY = 5      # one ask; a slower one is "not yet", never an error


class ShowCase(unittest.TestCase):
    def setUp(self):
        support.require_tmux()
        if fcntl is None:
            self.skipTest("SKIPPED: needs a POSIX pty")
        cm = support.private_tmux("show")
        self.pt = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        envcm = support.scratch_env()
        self.base, self.home = envcm.__enter__()
        self.addCleanup(envcm.__exit__, None, None, None)
        self.addCleanup(self._kill_private_servers)
        pbin = os.path.join(self.home, "pbin")
        os.makedirs(pbin)
        # The Neovims here start at once (a pane's UI and server processes,
        # and the first ask) in this new HOME, and each makes its state and
        # swap directories as it starts. One that loses that race (EEXIST)
        # stops at "Press ENTER" and never answers, so make them first.
        os.makedirs(os.path.join(self.home, ".local", "state", "nvim", "swap"))
        for tool in ("tmux", "nvim", "git"):
            if shutil.which(tool):
                os.symlink(shutil.which(tool), os.path.join(pbin, tool))
        self.base["PATH"] = pbin + ":/usr/bin:/bin:/usr/sbin:/sbin"
        self.base["TMPDIR"] = self.pt.tmpdir
        self.base["SESSIONVIEW_STATE"] = os.path.join(self.home, "state")
        self.A, self.B = self.pt.sock, self.pt.sock + "-b"
        self.F = self.pt.sock + "-frame"
        self.base["SESSIONVIEW_FRAME_SOCK"] = self.F
        self.clients = []
        self.addCleanup(lambda: [c.close() for c in self.clients])
        self.files = os.path.join(self.home, "files")
        os.makedirs(self.files)
        self.tmux(self.A, "-f", "/dev/null", "new-session", "-d", "-s", "a", "-x", "160", "-y", "40", "sleep 3600")
        self.tmux(self.A, "set", "-g", "exit-empty", "off")

    def _kill_private_servers(self):
        root = self.pt.tmpdir
        for d, _dirs, files in os.walk(root):
            for f in files:
                p = os.path.join(d, f)
                assert p.startswith(root), p
                subprocess.run(["tmux", "-S", p, "kill-server"], env=self.pt.env(),
                               capture_output=True, timeout=30)

    # ---- helpers ------------------------------------------------------------
    def env(self, **extra):
        e = self.pt.env(self.base)
        e.update(extra)
        return e

    def tmux(self, sock, *args):
        return subprocess.run(["tmux", "-L", sock, *args], env=self.env(),
                              capture_output=True, text=True, timeout=30)

    def out(self, sock, *args):
        return self.tmux(sock, *args).stdout.strip()

    def session(self, sock, name, *cmd):
        r = self.tmux(sock, "-f", "/dev/null", "new-session", "-d", "-s", name, "-x", "160", "-y", "40",
                      *(cmd or ("sleep 3600",)))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.tmux(sock, "set", "-g", "exit-empty", "off")

    def frame(self, name="frame-1", inner=None, session="a"):
        """A frame as sessionview-frame makes it: side pane, main pane
        attached to INNER:SESSION, the option naming the main pane, and a
        terminal on the frame. Returns (terminal, main pane tty)."""
        inner = inner or self.A
        self.session(self.F, name)
        side = self.out(self.F, "list-panes", "-t", "=" + name + ":", "-F", "#{pane_id}").split()[0]
        main = self.out(self.F, "split-window", "-h", "-P", "-F", "#{pane_id}", "-t", side, "-e", "TMUX=",
                        "exec tmux -L %s attach -t =%s" % (inner, session))
        self.tmux(self.F, "set", "-t", name, "@sessionview_main_pane", main)
        tty = self.out(self.F, "display-message", "-p", "-t", main, "#{pane_tty}")
        term = PtyClient(self.F, name, self.env(TERM="xterm-256color"))
        self.clients.append(term)
        self.assertTrue(wait_for(lambda: tty in self.clients_on(inner)), "the frame's client never attached")
        return term, tty

    def clients_on(self, sock):
        r = self.tmux(sock, "list-clients", "-F", "#{client_tty}\t#{session_name}")
        return dict(l.split("\t", 1) for l in r.stdout.splitlines() if "\t" in l)

    def snapshot(self):
        """Every client, window and pane on every private server."""
        snap = {}
        for sock in (self.A, self.B, self.F):
            snap[sock] = (self.out(sock, "list-clients", "-F", "#{client_tty} #{session_name} #{window_id} #{pane_id}"),
                          self.out(sock, "list-windows", "-a", "-F", "#{window_id} #{window_active} #{window_zoomed_flag}"),
                          self.out(sock, "list-panes", "-a", "-F", "#{pane_id} #{pane_active}"))
        return snap

    def need_nvim(self):
        if not shutil.which("nvim"):
            self.skipTest("SKIPPED: needs nvim")

    def write(self, name, text="hello\n"):
        p = os.path.join(self.files, name)
        with open(p, "w") as f:
            f.write(text)
        return os.path.realpath(p)

    def nvim_window(self, sock, session, wname, path, extra_pane=True):
        """A window WNAME in SESSION running a Neovim on PATH in pane 0 (and a
        second pane beside it). Returns (window id, nvim pane id, other pane id)."""
        sockpath = os.path.join(self.pt.tmpdir, "nvim-show-%s-%s" % (sock[-6:], wname))
        cmd = "nvim --clean --listen %s %s" % (sockpath, path)
        r = self.tmux(sock, "new-window", "-d", "-P", "-F", "#{window_id} #{pane_id}", "-t", "=" + session + ":",
                      "-n", wname, cmd)
        self.assertEqual(r.returncode, 0, r.stderr)
        wid, pid = r.stdout.split()
        other = self.out(sock, "split-window", "-d", "-h", "-P", "-F", "#{pane_id}", "-t", pid, "sleep 3600") \
            if extra_pane else None
        ok = wait_for(lambda: os.path.exists(sockpath) and self.nvim_expr(sockpath, "1") == "1", timeout=NVIM_WAIT)
        self.assertTrue(ok, "the Neovim never answered; its pane:\n" + self.out(sock, "capture-pane", "-p", "-t", pid))
        return wid, pid, other

    def nvim_expr(self, sockpath, expr):
        """`nvim --server SOCKPATH --remote-expr EXPR`: its answer, or None
        when none came in NVIM_TRY s. Callers poll it in a wait_for, so one
        slow ask is a "not yet" and the wait goes on."""
        try:
            return subprocess.run(["nvim", "--server", sockpath, "--remote-expr", expr], env=self.env(),
                                  capture_output=True, text=True, timeout=NVIM_TRY).stdout.strip()
        except subprocess.TimeoutExpired:
            return None

    def nvim_cur(self, sock, wname):
        sockpath = os.path.join(self.pt.tmpdir, "nvim-show-%s-%s" % (sock[-6:], wname))
        cur = self.nvim_expr(sockpath, "expand('%:p')")
        return "(no answer)" if cur is None else cur

    def show(self, *args):
        r = support.run(TOOL, *args, "--json", env=self.env(), timeout=60)
        try:
            return r.returncode, json.loads(r.stdout)
        except json.JSONDecodeError:
            self.fail("not JSON (rc %s): %s %s" % (r.returncode, r.stdout[-800:], r.stderr[-800:]))

    def brief(self, res):
        """A short account of a result, for a failure message."""
        return json.dumps({"result": res.get("result"), "error": res.get("error"),
                           "sent": [(r["step"], r["ok"], r.get("error")) for r in res.get("sent", [])],
                           "after": {k: (res.get("after") or {}).get(k) for k in ("server", "session", "window", "pane")}})

    def writes(self, res):
        return [s["step"] for s in res.get("sent", [])]

    # ---- (a) read-only --------------------------------------------------------
    def test_read_only_verbs_send_nothing(self):
        self.need_nvim()
        self.session(self.B, "b")
        f = self.write("a.txt")
        self.nvim_window(self.B, "b", "editor", f)
        self.frame()
        before = self.snapshot()
        rc, cur = self.show("--current")
        self.assertEqual(rc, 0, self.brief(cur))
        self.assertEqual((cur["server"]["name"], cur["session"]["name"]), (self.A, "a"))
        rc, tgt = self.show("--target", f)
        self.assertEqual(rc, 0, self.brief(tgt))
        self.assertEqual((tgt["server"]["name"], tgt["session"]["name"], tgt["window"]["name"]),
                         (self.B, "b", "editor"))
        rc, dry = self.show(f, "--dry-run")
        self.assertEqual(rc, 0, self.brief(dry))
        self.assertEqual(dry["result"], "would")
        self.assertEqual(dry["sent"], [])
        self.assertIn("server", [p["step"] for p in dry["plan"]])
        self.assertEqual(self.snapshot(), before)

    # ---- (b) another server ----------------------------------------------------
    def test_another_server_moves_the_client_and_shows_the_file(self):
        self.need_nvim()
        self.session(self.B, "b")
        f, g = self.write("a.txt"), self.write("b.txt")
        wid, pid, other = self.nvim_window(self.B, "b", "editor", g)
        subprocess.run(["nvim", "--server", os.path.join(self.pt.tmpdir, "nvim-show-%s-editor" % self.B[-6:]),
                        "--remote-send", ":badd %s<CR>" % f], env=self.env(), timeout=NVIM_WAIT)
        self.tmux(self.B, "select-pane", "-t", other)
        _term, tty = self.frame()
        rc, res = self.show(f, "--by", "amy")
        self.assertEqual(rc, 0, self.brief(res))
        self.assertEqual(res["result"], "shown", self.brief(res))
        self.assertIn("server", self.writes(res))
        self.assertEqual(self.clients_on(self.B).get(tty), "b")
        self.assertNotIn(tty, self.clients_on(self.A))
        self.assertEqual(self.out(self.B, "display-message", "-p", "-t", "=b:", "#{window_id} #{pane_id}"),
                         "%s %s" % (wid, pid))
        self.assertTrue(wait_for(lambda: self.nvim_cur(self.B, "editor") == f), self.nvim_cur(self.B, "editor"))
        rc, again = self.show(f)
        self.assertEqual((rc, again["result"], again["sent"]), (0, "already there", []), self.brief(again))
        r = support.run(TOOL, f, "--porcelain", env=self.env(), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        line = r.stdout.rstrip("\n").split("\t")
        self.assertEqual(line[:5], ["already-there", self.B, "b", wid, pid])
        self.assertTrue(line[5].endswith("nvim-show-%s-editor" % self.B[-6:]), line)

    # ---- (c) same server, another session ---------------------------------------
    def test_same_server_switches_only_the_frames_client(self):
        self.need_nvim()
        self.session(self.A, "c")
        f = self.write("c.txt")
        wid, pid, _other = self.nvim_window(self.A, "c", "editor", f, extra_pane=False)
        bystander = PtyClient(self.A, "a", self.env(TERM="xterm-256color"))
        self.clients.append(bystander)
        self.assertTrue(wait_for(lambda: bystander.tty in self.clients_on(self.A)))
        _term, tty = self.frame()
        rc, res = self.show(f)
        self.assertEqual((rc, res["result"]), (0, "shown"), self.brief(res))
        self.assertIn("session", self.writes(res))
        self.assertNotIn("server", self.writes(res))
        on = self.clients_on(self.A)
        self.assertEqual(on.get(tty), "c")
        self.assertEqual(on.get(bystander.tty), "a", "another terminal moved")

    # ---- (d) zoom ------------------------------------------------------------------
    def test_another_panes_zoom_is_undone(self):
        self.need_nvim()
        self.session(self.B, "b")
        f = self.write("z.txt")
        wid, pid, other = self.nvim_window(self.B, "b", "editor", f)
        self.tmux(self.B, "select-pane", "-t", other)
        self.tmux(self.B, "resize-pane", "-Z", "-t", other)
        self.assertEqual(self.out(self.B, "display-message", "-p", "-t", wid, "#{window_zoomed_flag}"), "1")
        self.frame()
        rc, res = self.show(f)
        self.assertEqual((rc, res["result"]), (0, "shown"), self.brief(res))
        self.assertIn("zoom", self.writes(res))
        self.assertEqual(self.out(self.B, "display-message", "-p", "-t", wid, "#{window_zoomed_flag} #{pane_id}"),
                         "0 " + pid)

    # ---- (e) no frame ---------------------------------------------------------------
    def test_no_frame_is_not_ours(self):
        self.need_nvim()
        self.session(self.B, "b")
        f = self.write("n.txt")
        self.nvim_window(self.B, "b", "editor", f)
        before = self.snapshot()
        rc, res = self.show(f)
        self.assertEqual((rc, res["result"]), (3, "not ours"), self.brief(res))
        self.assertEqual(res["sent"], [])
        self.assertEqual(self.snapshot(), before)

    def test_a_frame_nobody_sees_is_not_ours(self):
        self.need_nvim()
        self.session(self.B, "b")
        f = self.write("d.txt")
        self.nvim_window(self.B, "b", "editor", f)
        term, tty = self.frame()
        term.close()                      # the terminal goes; the frame stays, detached
        self.assertTrue(wait_for(lambda: self.out(self.F, "list-clients") == ""), "the terminal never left")
        before = self.snapshot()
        rc, res = self.show(f)
        self.assertEqual((rc, res["result"]), (3, "not ours"), self.brief(res))
        self.assertIn("on screen", res["error"])
        self.assertEqual(self.snapshot(), before)

    # ---- (f) unruled ------------------------------------------------------------------
    def test_a_file_nothing_names_is_not_ours(self):
        f = self.write("loose.txt")
        self.frame()
        before = self.snapshot()
        rc, res = self.show(f)
        self.assertEqual((rc, res["result"]), (3, "not ours"), self.brief(res))
        self.assertEqual(self.snapshot(), before)

    # ---- (g) a dead socket -------------------------------------------------------------
    def test_a_dead_tmux_socket_never_hangs(self):
        d = os.path.join(self.pt.tmpdir, "tmux-%d" % os.getuid())
        os.makedirs(d, exist_ok=True)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(os.path.join(d, "sv-test-dead"))
        s.close()                         # the file stays; nothing listens
        self.frame()
        t = time.time()
        rc, cur = self.show("--current")
        self.assertEqual(rc, 0, self.brief(cur))
        self.assertLess(time.time() - t, 15)
        self.assertTrue(any("sv-test-dead" in d[1] for d in cur["asks"]["dead"]), cur["asks"])

    # ---- (h) two frames ------------------------------------------------------------------
    def test_two_frames_move_the_one_used_last(self):
        self.need_nvim()
        self.session(self.A, "c")
        f = self.write("t.txt")
        self.nvim_window(self.A, "c", "editor", f, extra_pane=False)
        t1, tty1 = self.frame("frame-1")
        t2, tty2 = self.frame("frame-2")
        time.sleep(1.1)                   # tmux keeps activity in whole seconds
        t1.type(b"x")
        rc, res = self.show(f)
        self.assertEqual((rc, res["result"]), (0, "shown"), self.brief(res))
        on = self.clients_on(self.A)
        self.assertEqual((on.get(tty1), on.get(tty2)), ("c", "a"), on)


    # ---- (i) make what is missing ---------------------------------------------------------
    def project_fixture(self):
        """A repo whose remote is a project's git url in a fixture store on
        server B, a stub `tm` that lists that store, and a stand-in
        sessionview-session (under a scratch SESSIONVIEW_ROOT) that logs its
        argv and makes the session, or the editor window running a Neovim."""
        repo = os.path.join(self.home, "Code", "demo")
        os.makedirs(repo)
        for args in (["init", "-q"], ["remote", "add", "origin", "forge:pat/demo.git"]):
            subprocess.run(["git", "-C", repo, *args], env=self.env(), check=True, capture_output=True)
        with open(os.path.join(repo, "README.md"), "w") as f:
            f.write("# demo\n")
        store = os.path.join(self.home, "store")
        os.makedirs(os.path.join(store, "projects", "demo"))
        with open(os.path.join(store, "projects", "demo", "PROJECT.md"), "w") as f:
            f.write("---\nname: demo\ngit_url: forge:pat/demo.git\n---\n")
        tm = os.path.join(self.home, "pbin", "tm")
        with open(tm, "w") as f:
            f.write("#!/bin/sh\necho '%s'\n" % json.dumps([{"name": "fx", "path": store, "socket": self.B}]))
        os.chmod(tm, 0o755)
        root = os.path.join(self.home, "root")
        os.makedirs(os.path.join(root, "bin"))
        os.makedirs(os.path.join(root, "tmux"))
        open(os.path.join(root, "tmux", "frame.conf"), "w").close()
        self.made_log = os.path.join(self.home, "made.log")
        nv = os.path.join(self.pt.tmpdir, "nvim-show-made")
        fake = os.path.join(root, "bin", "sessionview-session")
        with open(fake, "w") as f:
            f.write("""#!/bin/sh
echo "$*" >> %(log)s
NAME=$1; shift; SOCK=""; WIN=""; LIST=0
while [ $# -gt 0 ]; do case "$1" in
  --socket) SOCK=$2; shift;; --store) shift;; --window) WIN=$2; shift;; --list-windows) LIST=1;;
esac; shift; done
if [ $LIST = 1 ]; then printf 'repo\\t%(repo)s\\neditor\\tnvim README.md\\n'; exit 0; fi
if [ -n "$WIN" ]; then
  exec tmux -L "$SOCK" new-window -d -t "=$NAME:" -c %(repo)s -n "$WIN" "nvim --clean --listen %(nv)s README.md"
fi
exec tmux -L "$SOCK" -f /dev/null new-session -d -s "$NAME" -c %(repo)s "sleep 3600"
""" % {"log": self.made_log, "repo": repo, "nv": nv})
        os.chmod(fake, 0o755)
        self.base["SESSIONVIEW_ROOT"] = root
        return repo

    def test_a_missing_session_and_window_are_made_then_shown(self):
        self.need_nvim()
        repo = self.project_fixture()
        self.session(self.B, "other")
        f = self.write("../Code/demo/x.txt")
        _term, tty = self.frame()
        before = self.snapshot()
        rc, dry = self.show(f, "--dry-run")
        self.assertEqual((rc, dry["result"], dry.get("would_make"), dry["sent"]),
                         (0, "would", ["session", "window"], []), self.brief(dry))
        self.assertEqual(self.snapshot(), before)
        rc, res = self.show(f, "--by", "bob")
        self.assertEqual((rc, res["result"]), (0, "shown"), self.brief(res))
        self.assertEqual(list(res)[0], "made")
        self.assertEqual(res["made"], ["session demo", "window editor in demo"])
        with open(self.made_log) as fh:
            log = fh.read()
        self.assertIn("demo --socket %s --store" % self.B, log)
        self.assertIn("--window editor", log)
        self.assertEqual(self.clients_on(self.B).get(tty), "demo")
        self.assertEqual(self.out(self.B, "display-message", "-p", "-t", "=demo:", "#{window_name}"), "editor")
        nv = os.path.join(self.pt.tmpdir, "nvim-show-made")
        self.assertTrue(wait_for(lambda: self.nvim_expr(nv, "expand('%:p')") == f, timeout=NVIM_WAIT),
                        self.nvim_expr(nv, "expand('%:p')"))
        rc, again = self.show(f)
        self.assertEqual((rc, again["result"], again["made"], again["sent"]), (0, "already there", [], []),
                         self.brief(again))


if __name__ == "__main__":
    unittest.main()
