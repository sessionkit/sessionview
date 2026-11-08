"""bin/tmux-sidebar: the agents list's three scopes, all / store / project.

`project` is the old `current`: the agents of the selected session. `store`
keeps the agents whose session is one of the current store's projects (or
the store's own session). A pinned agent shows under every scope.

PureScope drives scope_filter() and store_projects() in a subprocess, as
tests/test_pinned_agents.py does: the sidebar is never imported into this
process, and each run has a scratch HOME (support.scratch_env). RenderScope
draws render_base() on a private `sv-test-` server with the fixture stores
(tests/test_store_view.py ViewBase); ClickScope clicks the heading word in a
real sidebar running in a pane there.
"""
import json
import os
import subprocess
import sys
import re
import shlex
import tempfile
import textwrap
import time
import unittest

from tests import support
from tests.test_store_view import ViewBase

SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")

HARNESS = textwrap.dedent('''
    import importlib.machinery, importlib.util, json, sys
    loader = importlib.machinery.SourceFileLoader("sidebar", sys.argv[1])
    spec = importlib.util.spec_from_loader("sidebar", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    OUT = {}
    exec(sys.argv[2])
    print(json.dumps(OUT))
''')

#: The viewed server's panes, pane -> session. `alpha` and `beta` are store
#: projects, `fx-store` is the store's own session, `home` is a plain session
#: in no store.
P2S = {"%1": "alpha", "%2": "fx-store", "%3": "home", "%4": "beta"}
STORE = ["alpha", "beta", "fx-store"]

#: Live rows after the placement loop: a seat on another server has lost its
#: pane and carries `_xsock`; a remote seat keeps its REMOTE pane id (`%1`,
#: colliding with the local alpha pane).
ROWS = [
    {"agent": "proj",   "status": "busy", "idle_s": 1, "tmux_pane": "%1"},
    {"agent": "own",    "status": "idle", "idle_s": 2, "tmux_pane": "%2"},
    {"agent": "plain",  "status": "idle", "idle_s": 3, "tmux_pane": "%3"},
    {"agent": "other",  "status": "busy", "idle_s": 4, "tmux_pane": "%4"},
    {"agent": "xsock",  "status": "idle", "idle_s": 5, "tmux_pane": "",
     "_xsock": "elsewhere", "_xpane": "%9"},
    {"agent": "remote", "status": "busy", "idle_s": 6, "tmux_pane": "%1", "_host": "devbox"},
    {"agent": "nopane", "status": "idle", "idle_s": 7},
    {"agent": "alice",  "status": "idle", "idle_s": 900},
]
ALL = [a["agent"] for a in ROWS]
PINNED = ["alice"]


class PureScope(unittest.TestCase):

    def setUp(self):
        self._scratch = support.scratch_env()
        self.env, _ = self._scratch.__enter__()

    def tearDown(self):
        self._scratch.__exit__(None, None, None)

    def run_body(self, body, env=None):
        r = subprocess.run([sys.executable, "-B", "-c", HARNESS, SIDEBAR, textwrap.dedent(body)],
                           env=env or self.env, capture_output=True, text=True, timeout=60,
                           cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.splitlines()[-1])

    def scope(self, scope, cur_sess="alpha", store=STORE, pinned=PINNED, no_store=None,
              rows=ROWS):
        """The agent names scope_filter() keeps; also checks ROWS is left
        untouched (the filter is pure)."""
        got = self.run_body(f'''
            rows = json.loads({json.dumps(json.dumps(rows))})
            before = json.dumps(rows)
            store = {store!r}
            out = m.scope_filter(rows, {scope!r}, {P2S!r}, {cur_sess!r}, {pinned!r},
                                 set(store) if store is not None else None, {no_store!r})
            OUT["names"] = [a["agent"] for a in out]
            OUT["pure"] = json.dumps(rows) == before
        ''')
        self.assertTrue(got["pure"], "scope_filter changed its input")
        return got["names"]

    # -- 1. all --

    def test_all_keeps_every_row_in_input_order(self):
        self.assertEqual(self.scope("all"), ALL)
        self.assertEqual(self.scope("all", pinned=[]), ALL)

    # -- 2. store --

    def test_store_keeps_the_store_projects_and_its_own_session(self):
        self.assertEqual(self.scope("store"), ["proj", "own", "other", "alice"])

    def test_store_drops_plain_xsock_remote_and_no_pane_seats(self):
        out = self.scope("store", pinned=[])
        self.assertEqual(out, ["proj", "own", "other"])
        for gone in ("plain", "xsock", "remote", "nopane", "alice"):
            self.assertNotIn(gone, out)

    def test_store_from_the_stores_own_session_is_still_in_the_store(self):
        self.assertEqual(self.scope("store", cur_sess="fx-store"),
                         ["proj", "own", "other", "alice"])

    # -- 3. project --

    def test_project_keeps_only_the_selected_session_plus_pins(self):
        self.assertEqual(self.scope("project"), ["proj", "alice"])
        self.assertEqual(self.scope("project", cur_sess="beta"), ["other", "alice"])

    def test_project_never_keeps_a_remote_seat_with_a_colliding_pane_id(self):
        # remote's pane id `%1` is the REMOTE server's; locally %1 is alpha
        self.assertNotIn("remote", self.scope("project", pinned=[]))
        self.assertNotIn("remote", self.scope("store", pinned=[]))

    def test_project_with_nothing_selected_keeps_only_pins(self):
        self.assertEqual(self.scope("project", cur_sess=""), ["alice"])

    # -- 4. the pinned rule --

    def test_every_pinned_row_is_kept_whatever_its_pane_host_or_session(self):
        pinned = ["plain", "xsock", "remote", "nopane", "alice"]
        for scope in ("store", "project"):
            with self.subTest(scope=scope):
                out = self.scope(scope, pinned=pinned)
                for name in pinned:
                    self.assertIn(name, out)

    def test_a_pin_with_no_live_row_adds_nothing(self):
        self.assertEqual(self.scope("project", pinned=["ghost"]), ["proj"])

    def test_pins_are_kept_under_every_no_store_option(self):
        for opt in ("project", "pinned", "nostore", "all"):
            with self.subTest(no_store=opt):
                self.assertIn("alice", self.scope("store", cur_sess="home", no_store=opt))
                self.assertIn("alice", self.scope("store", store=None, no_store=opt))

    # -- 5. the no-store seam: four options, two triggers --

    def test_no_store_options_with_no_store_on_the_viewed_server(self):
        # trigger (a): no store owns the viewed server
        want = {
            "project": ["proj", "alice"],
            "pinned":  ["alice"],
            "nostore": ["proj", "own", "plain", "other", "alice"],
            "all":     ALL,
        }
        for opt, names in want.items():
            with self.subTest(no_store=opt):
                self.assertEqual(self.scope("store", store=None, no_store=opt), names)

    def test_no_store_options_when_the_selected_session_is_not_a_store_project(self):
        # trigger (b): a store owns the server, the selected session `home` is not its
        want = {
            "project": ["plain", "alice"],
            "pinned":  ["alice"],
            "nostore": ["plain", "alice"],
            "all":     ALL,
        }
        for opt, names in want.items():
            with self.subTest(no_store=opt):
                self.assertEqual(self.scope("store", cur_sess="home", no_store=opt), names)

    def test_no_store_options_with_nothing_selected(self):
        want = {
            "project": ["alice"],
            "pinned":  ["alice"],
            "nostore": ["plain", "alice"],
            "all":     ALL,
        }
        for opt, names in want.items():
            with self.subTest(no_store=opt):
                self.assertEqual(self.scope("store", cur_sess="", no_store=opt), names)

    def test_no_store_unset_reads_the_constant(self):
        got = self.run_body('''
            OUT["const"] = m.STORE_SCOPE_NO_STORE
            rows = [{"agent": "a", "tmux_pane": "%3"}, {"agent": "b"}]
            p2s = {"%3": "home"}
            OUT["default"] = [r["agent"] for r in m.scope_filter(rows, "store", p2s, "home")]
            m.STORE_SCOPE_NO_STORE = "pinned"
            OUT["edited"] = [r["agent"] for r in m.scope_filter(rows, "store", p2s, "home")]
        ''')
        self.assertEqual(got["const"], "all")
        self.assertEqual(got["default"], ["a", "b"])
        self.assertEqual(got["edited"], [])

    def test_an_unknown_scope_or_option_hides_nothing(self):
        self.assertEqual(self.scope("bogus", pinned=[]), ALL)
        self.assertEqual(self.scope("store", cur_sess="home", no_store="bogus", pinned=[]), ALL)

    def test_an_empty_session_name_never_counts_as_in_the_store(self):
        # a store set that somehow holds "" must not pull in pane-less rows
        out = self.scope("store", store=STORE + [""], pinned=[])
        self.assertEqual(out, ["proj", "own", "other"])
        self.assertEqual(self.scope("store", cur_sess="", store=STORE + [""], pinned=[],
                                    no_store="pinned"), [])

    # -- the seams themselves --

    def test_the_seams_are_named_constants_at_todays_behaviour(self):
        got = self.run_body('''
            OUT["scopes"] = list(m.SCOPES)
            OUT["default"] = m.FILTER_DEFAULT
            OUT["filter"] = m.FILTER
            OUT["no_store"] = m.STORE_SCOPE_NO_STORE
        ''')
        self.assertEqual(got["scopes"], ["all", "store", "project"])
        self.assertEqual(got["default"], "all")
        self.assertEqual(got["filter"], got["default"])
        self.assertEqual(got["no_store"], "all")

    def test_every_default_scope_option_is_a_scope(self):
        # the default-scope choice is one word from SCOPES; each is a working scope
        for scope in ("all", "store", "project"):
            with self.subTest(scope=scope):
                self.assertIn("alice", self.scope(scope))

    # -- 6. purity --

    def test_rows_and_their_dicts_are_unchanged_and_not_copied(self):
        got = self.run_body(f'''
            rows = json.loads({json.dumps(json.dumps(ROWS))})
            before = json.dumps(rows)
            out = m.scope_filter(rows, "store", {P2S!r}, "alpha", ["alice"], set({STORE!r}))
            OUT["pure"] = json.dumps(rows) == before
            OUT["same"] = all(any(o is r for r in rows) for o in out)
            OUT["new_list"] = out is not rows
        ''')
        self.assertTrue(got["pure"])
        self.assertTrue(got["same"], "scope_filter should keep the row dicts, not copy them")
        self.assertTrue(got["new_list"])

    # -- 7. filter before sort --

    def order_after_scope(self, scope, grouped):
        return self.run_body(f'''
            rows = json.loads({json.dumps(json.dumps(ROWS))})
            p2s = {P2S!r}
            kept = m.scope_filter(rows, {scope!r}, p2s, "alpha", ["alice"], set({STORE!r}))
            grp = (lambda a: p2s.get(a.get("tmux_pane") or "") or "-") if {grouped!r} else None
            out = m.order_agents(kept, ["alice"], ["rank", "idle_s"], grp,
                                 {{"alpha": 0, "beta": 1, "fx-store": 2}} if {grouped!r} else None)
            OUT["names"] = [a["agent"] for a in out]
        ''')["names"]

    def test_filter_then_sort_a_pinned_row_the_scope_would_drop_leads(self):
        # alice is idle 900s with no pane: the scope alone would drop her, the
        # sort alone would put her last; filtered then sorted, she leads
        self.assertEqual(self.order_after_scope("project", grouped=False), ["alice", "proj"])
        out = self.order_after_scope("store", grouped=False)
        self.assertEqual(out[0], "alice")
        self.assertEqual(sorted(out), sorted(["alice", "proj", "own", "other"]))

    def test_filter_then_sort_a_dropped_unpinned_row_is_absent(self):
        out = self.order_after_scope("store", grouped=False)
        for gone in ("plain", "xsock", "remote", "nopane"):
            self.assertNotIn(gone, out)

    def test_grouped_the_pinned_row_sits_above_every_group(self):
        # alice has no group of her own ("-", after every known group); pinned,
        # she is the block above them all
        self.assertEqual(self.order_after_scope("store", grouped=True),
                         ["alice", "proj", "other", "own"])


TM_SHIM = r'''#!{python}
import json, os, sys
with open({log!r}, "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
if os.path.exists({fail!r}):
    print("not json"); sys.exit(1)
if a[:2] == ["project", "list"] and "--store" in a:
    print(json.dumps([{{"name": "alpha"}}, {{"name": "beta"}}, {{"other": 1}}, "junk"])); sys.exit(0)
print("[]")
'''


class StoreProjects(unittest.TestCase):
    """store_projects(): one tm call per store path a minute, a set of names,
    the empty set whenever tm cannot answer."""

    def setUp(self):
        self._scratch = support.scratch_env()
        self.env, _ = self._scratch.__enter__()
        self.tmp = tempfile.mkdtemp(prefix="sv-scope-")
        self.bin = os.path.join(self.tmp, "bin")
        self.store = os.path.realpath(os.path.join(self.tmp, "store"))
        self.log = os.path.join(self.tmp, "tm.log")
        self.fail = os.path.join(self.tmp, "fail")
        os.makedirs(self.bin)
        os.makedirs(self.store)
        shim = os.path.join(self.bin, "tm")
        with open(shim, "w") as f:
            f.write(TM_SHIM.format(python=sys.executable, log=self.log, fail=self.fail))
        os.chmod(shim, 0o755)
        self.env["PATH"] = self.bin + os.pathsep + self.env.get("PATH", "")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        self._scratch.__exit__(None, None, None)

    def calls(self):
        try:
            with open(self.log) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def run_body(self, body):
        r = subprocess.run([sys.executable, "-B", "-c", HARNESS, SIDEBAR, textwrap.dedent(body)],
                           env=self.env, capture_output=True, text=True, timeout=60,
                           cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.splitlines()[-1])

    def test_names_from_tm_project_list_for_that_store(self):
        got = self.run_body(f'''
            OUT["names"] = sorted(m.store_projects({{"path": {self.store!r}}}))
        ''')
        self.assertEqual(got["names"], ["alpha", "beta"])
        project_calls = [c for c in self.calls() if c.startswith("project list")]
        self.assertEqual(project_calls, [f"project list -f json --store {self.store}"])

    def test_cached_per_store_path(self):
        self.run_body(f'''
            rec = {{"path": {self.store!r}}}
            for _ in range(3):
                m.store_projects(rec)
            m.store_projects({{"path": {self.store!r} + "/."}})    # the same store, another spelling
        ''')
        self.assertEqual(len([c for c in self.calls() if c.startswith("project list")]), 1)

    def test_a_caller_mutating_the_result_does_not_touch_the_cache(self):
        got = self.run_body(f'''
            rec = {{"path": {self.store!r}}}
            m.store_projects(rec).add("mutated")
            OUT["again"] = sorted(m.store_projects(rec))
        ''')
        self.assertEqual(got["again"], ["alpha", "beta"])

    def test_no_path_no_call_empty_set(self):
        got = self.run_body('''
            OUT["a"] = sorted(m.store_projects({}))
            OUT["b"] = sorted(m.store_projects(None))
        ''')
        self.assertEqual((got["a"], got["b"]), ([], []))
        self.assertFalse([c for c in self.calls() if c.startswith("project list")])

    def test_tm_failing_is_the_empty_set(self):
        open(self.fail, "w").close()
        got = self.run_body(f'''
            OUT["names"] = sorted(m.store_projects({{"path": {self.store!r}}}))
        ''')
        self.assertEqual(got["names"], [])

    def test_no_tm_at_all_is_the_empty_set(self):
        self.env["PATH"] = os.pathsep.join(p for p in self.env["PATH"].split(os.pathsep)
                                           if p != self.bin and not os.path.exists(os.path.join(p, "tm")))
        got = self.run_body(f'''
            OUT["names"] = sorted(m.store_projects({{"path": {self.store!r}}}))
        ''')
        self.assertEqual(got["names"], [])


#: The agents the render tests draw: one per session on the private server,
#: plus a pinned seat with no pane and a pinned seat whose status is hidden.
#: fx-legacy's tm projects are alpha and store; `fx-legacy` is its own session.
RENDER_ROWS = [
    ("ann", "alpha"), ("ben", "home"), ("cal", "fx-legacy"),
    ("pip", None), ("hal", None),
]
NAMES = {n for n, _ in RENDER_ROWS}
ESC_SGR = re.compile(r"\x1b\[[0-9;]*m")


class RenderScope(ViewBase):
    """render_base() under each scope: the rows kept, the heading word, its
    light and its click span, hide over a pin, and what each scope costs."""

    TAG = "scope"

    def setUp(self):
        super().setUp()
        self.place("fx-legacy")
        self.sessions("fx-legacy", "alpha", "home")
        panes = dict(line.split() for line in self.pt.tmux(
            "list-panes", "-a", "-F", "#{session_name} #{pane_id}").stdout.splitlines())
        rows = []
        for name, sess in RENDER_ROWS:
            row = {"agent": name, "name": name, "status": "idle", "idle_s": 5}
            if sess:
                row["tmux_pane"] = panes[sess]
            if name == "hal":
                row["status"] = "shell"
            rows.append(row)
        agents = os.path.join(self.home, "agents.json")
        with open(agents, "w") as f:
            json.dump(rows, f)
        shim = os.path.join(self.fx.bin, "session")
        with open(shim, "w") as f:
            f.write(f"#!/bin/sh\ncat {shlex.quote(agents)}\n")
        os.chmod(shim, 0o755)
        with open(self.env["SESSIONVIEW_CONFIG"], "w") as f:
            json.dump({"pinned_agents": ["pip", "hal"], "hide": ["shell"],
                       "agent_format": " {glyph} {agent}"}, f)

    def no_store_here(self):
        """No fixture store owns the private server: trigger (a)."""
        with open(self.fx.fixtures) as f:
            fix = json.load(f)
        for s in fix["stores"]:
            s["socket"] = f"sv-test-off-{os.getpid()}"
        with open(self.fx.fixtures, "w") as f:
            json.dump(fix, f)

    def draw(self, scope, cur="alpha", no_store=None):
        """Render under SCOPE with CUR selected: (agent names drawn, the
        heading's plain text, its raw text, the agents-head span, tm calls)."""
        before = len(self.fx.log())
        out = self.harness(f'''
            m.current_session = lambda: {cur!r}
            m.FILTER = {scope!r}
            if {no_store!r} is not None:
                m.STORE_SCOPE_NO_STORE = {no_store!r}
            lines, targets = m.render_base(40)
            i = next(k for k, t in targets.items() if t[0] == "agents-head")
            OUT["head"] = lines[i]
            OUT["span"] = list(targets[i][1])
            OUT["below"] = [m.ANSI_RE.sub("", l) for l in lines[i + 1:]]
        ''')
        # the agent names drawn under the heading, top to bottom
        out["agents"] = [w for l in out["below"] for w in l.split() if w in NAMES]
        plain = ESC_SGR.sub("", out["head"])
        calls = [c for c in self.fx.log()[before:] if c.startswith("project list")]
        return out["agents"], plain, out["head"], out["span"], calls

    # -- the rows each scope draws --

    def test_all_draws_every_unhidden_row(self):
        agents = self.draw("all")[0]
        self.assertEqual(sorted(agents), ["ann", "ben", "cal", "pip"])

    def test_store_draws_the_store_sessions_and_the_pins(self):
        agents = self.draw("store")[0]
        self.assertEqual(sorted(agents), ["ann", "cal", "pip"])
        self.assertEqual(agents[0], "pip", "a pinned row leads")

    def test_project_draws_the_selected_session_and_the_pins(self):
        self.assertEqual(sorted(self.draw("project")[0]), ["ann", "pip"])
        self.assertEqual(sorted(self.draw("project", cur="home")[0]), ["ben", "pip"])

    def test_store_outside_the_store_follows_the_seam(self):
        # trigger (b): `home` is not a store project; the provisional option is all
        agents, plain, _raw, _span, _calls = self.draw("store", cur="home")
        self.assertEqual(sorted(agents), ["ann", "ben", "cal", "pip"])
        self.assertIn("store \u00b7 grouped", plain)
        agents, plain, *_ = self.draw("store", cur="home", no_store="pinned")
        self.assertEqual(agents, ["pip"])
        self.assertIn("no store \u00b7 grouped", plain)

    def test_store_with_no_store_on_the_server_follows_the_seam(self):
        # trigger (a)
        self.no_store_here()
        agents, plain, _raw, _span, calls = self.draw("store")
        self.assertEqual(sorted(agents), ["ann", "ben", "cal", "pip"])
        self.assertEqual(calls, [], "no store, nothing to ask tm")
        agents, plain, *_ = self.draw("store", no_store="pinned")
        self.assertEqual(agents, ["pip"])
        self.assertIn("no store \u00b7 grouped", plain)

    # -- 8. hide wins over the pin --

    def test_a_pinned_row_with_a_hidden_status_is_absent_under_every_scope(self):
        for scope in ("all", "store", "project"):
            with self.subTest(scope=scope):
                agents = self.draw(scope)[0]
                self.assertNotIn("hal", agents)
                self.assertIn("pip", agents)

    # -- 9. the heading --

    def test_the_heading_names_the_scope_lit_unless_all_and_spans_the_word(self):
        for scope in ("all", "store", "project"):
            with self.subTest(scope=scope):
                _a, plain, raw, (x0, x1), _c = self.draw(scope)
                self.assertIn(f"{scope} \u00b7 grouped", plain)
                self.assertEqual(x1 - x0, len(scope) + 2)
                self.assertEqual(plain[x0:x0 + len(scope)], scope,
                                 f"the click span starts on the word: {plain!r}")
                lit = self.harness('OUT["sel"] = m.C_SEL')["sel"] + scope in raw
                self.assertEqual(lit, scope != "all", f"lit only when not all: {raw!r}")

    def test_the_no_store_word_spans_its_own_width(self):
        _a, plain, _raw, (x0, x1), _c = self.draw("store", cur="home", no_store="pinned")
        self.assertEqual(x1 - x0, len("no store") + 2)
        self.assertEqual(plain[x0:x0 + len("no store")], "no store")

    # -- 11. cost --

    def test_only_the_store_scope_asks_tm_for_projects(self):
        self.assertEqual(self.draw("all")[4], [])
        self.assertEqual(self.draw("project")[4], [])
        calls = self.draw("store")[4]
        self.assertEqual(len(calls), 1, calls)
        self.assertIn(f"--store {self.fx.path('fx-legacy')}", calls[0])


class ClickScope(ViewBase):
    """10. The mouse loop end to end: a real sidebar in a pane on the private
    server; a left click on the heading word cycles all, store, project, all."""

    TAG = "scopeclick"
    H = 30

    def setUp(self):
        super().setUp()
        self.place("fx-legacy")
        self.sessions("fx-legacy", "alpha")
        launcher = os.path.join(self.home, "run-sidebar")
        keep = {k: v for k, v in self.env.items() if k not in ("TMUX", "TMUX_PANE")}
        with open(launcher, "w") as f:
            f.write("#!/bin/sh\n")
            for k, v in sorted(keep.items()):
                f.write(f"export {k}={shlex.quote(v)}\n")
            f.write(f"exec {shlex.quote(sys.executable)} -B {shlex.quote(SIDEBAR)}\n")
        os.chmod(launcher, 0o755)
        r = self.pt.tmux("new-session", "-d", "-s", "sb", "-x", "40", "-y", str(self.H), launcher)
        self.assertEqual(r.returncode, 0, r.stderr)

    def screen(self):
        r = self.pt.tmux("capture-pane", "-p", "-t", "=sb:")
        return [ESC_SGR.sub("", l).rstrip() for l in r.stdout.splitlines()]

    def heading(self, word, secs=20):
        """(row, col) of WORD on the agents heading, once it is drawn."""
        want = f"{word} \u00b7 grouped"
        end = time.time() + secs
        while time.time() < end:
            for i, line in enumerate(self.screen()):
                if line.endswith(want):
                    return i, len(line) - len(want)
            time.sleep(0.2)
        self.fail(f"no {want!r}; the pane shows:\n" + "\n".join(self.screen()))

    def click(self, row, col):
        # SGR mouse, 1-based: ESC [ < 0 ; x ; y M is a left press
        r = self.pt.tmux("send-keys", "-t", "=sb:", "-l", f"\x1b[<0;{col + 1};{row + 1}M")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_three_clicks_cycle_all_store_project_all(self):
        row, col = self.heading("all")
        for word in ("store", "project", "all"):
            self.click(row, col)
            row, col = self.heading(word)


if __name__ == "__main__":
    unittest.main()
