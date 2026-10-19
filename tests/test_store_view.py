"""bin/tmux-sidebar and the store row (SV-92, design.md §1, §3, §4, §5; §6
cases 4, 5a, 5b, 5c, 5d): which session the row opens, what it hides, what
its name and its dots do when clicked, and the Switch store modal.

Every tmux call is on a private socket (support.private_tmux: `-L sv-test-*`
under a scratch TMUX_TMPDIR); the sidebar is pointed at it by SESSIONVIEW_VIEW_SOCK.
The sidebar is never imported into this process (import runs load_config()
and reads TMUX): a subprocess loads it with SourceFileLoader under the
scratch env and prints JSON.
"""
import json
import os
import re
import subprocess
import sys
import textwrap
import unittest

from tests import support

SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")
ANSI = re.compile(r"\x1b\[[0-9;]*m")

# The harness: load the sidebar as a module, run BODY (it may set OUT), print OUT.
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


class ViewBase(unittest.TestCase):
    TAG = "view"

    def setUp(self):
        if not support.have_tmux():
            self.skipTest(support.TMUX_SKIP)
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self._pt = support.private_tmux(self.TAG)
        self.pt = self._pt.__enter__()
        self.fx = support.StoreFixtures(os.path.join(self.home, "fx"), self.pt)
        # `session list` (the agents) answers nothing: the real one reads real seats.
        p = os.path.join(self.fx.bin, "session")
        with open(p, "w") as f:
            f.write("#!/bin/sh\necho '[]'\n")
        os.chmod(p, 0o755)
        self.env = self.fx.env(env)
        self.env["SESSIONVIEW_VIEW_SOCK"] = self.pt.sock
        self.env["SIDEBAR_WIDTH"] = "40"

    def tearDown(self):
        self._pt.__exit__(None, None, None)
        self._scratch.__exit__(None, None, None)

    def place(self, ident, **change):
        """Put ONLY fixture IDENT on the private socket (the others on one
        that never exists), so the viewed store is unambiguous. CHANGE edits
        IDENT's record (e.g. name=)."""
        with open(self.fx.fixtures) as f:
            fix = json.load(f)
        for s in fix["stores"]:
            s["socket"] = self.pt.sock if s["store"] == ident else f"sv-test-off-{os.getpid()}"
            if s["store"] == ident:
                s.update(change)
        with open(self.fx.fixtures, "w") as f:
            json.dump(fix, f)

    def sessions(self, *names):
        """Start the private server holding exactly NAMES (one shell window each)."""
        for n in names:
            r = self.pt.tmux("new-session", "-d", "-s", n)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(self.pt.sessions()), sorted(names))

    def once(self):
        r = subprocess.run([sys.executable, "-B", SIDEBAR, "--once"], env=self.env,
                           capture_output=True, text=True, timeout=60, cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        return [ANSI.sub("", line).rstrip() for line in r.stdout.splitlines()]

    def harness(self, body):
        r = subprocess.run([sys.executable, "-B", "-c", HARNESS, SIDEBAR, textwrap.dedent(body)],
                           env=self.env, capture_output=True, text=True, timeout=120,
                           cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.splitlines()[-1])


def project_rows(lines, store):
    """The project names drawn under the store row: the rows after ` STORE ⋯`
    up to the first blank line, each row's first word that is not a glyph."""
    i = next(k for k, line in enumerate(lines) if line.strip() == f"{store} ⋯")
    out = []
    for line in lines[i + 1:]:
        words = line.split()
        if not words:
            break
        out.append(words[1] if words[0] in "◐●○■" and len(words) > 1 else words[0])
    return out


class Case4ResolveAndHide(ViewBase):
    """§6 case 4: `tmux-sidebar --once` viewing fx-legacy, one row per line of
    §3's table. Exactly the resolved session is hidden; nothing else ever is."""

    TABLE = [
        # sessions on the server             hidden          drawn
        (("fx-legacy", "alpha"),             "fx-legacy",    ["alpha"]),
        (("store", "alpha"),                 "store",        ["alpha"]),
        (("fx-legacy", "store", "alpha"),    "fx-legacy",    ["alpha", "store"]),
        (("alpha",),                         None,           ["alpha"]),
    ]

    def test_the_hide_table(self):
        self.place("fx-legacy")
        for names, hidden, drawn in self.TABLE:
            with self.subTest(sessions=names):
                self.pt.tmux("kill-server")
                self.sessions(*names)
                lines = self.once()
                self.assertTrue(any(line.strip() == "fx-legacy ⋯" for line in lines), lines)
                rows = project_rows(lines, "fx-legacy")
                self.assertEqual(sorted(rows), sorted(drawn), lines)
                if hidden:
                    self.assertNotIn(hidden, rows)
                # never hide an unopened session: every other one has its row
                self.assertEqual(sorted(rows), sorted(n for n in names if n != hidden))

    def test_store_is_drawn_when_the_identity_is_the_store_row(self):
        self.place("fx-corp")
        self.sessions("fx-corp", "store", "alpha")
        rows = project_rows(self.once(), "fx-corp")
        self.assertEqual(sorted(rows), ["alpha", "store"])

    def test_no_store_record_hides_nothing(self):
        self.place("fx-legacy", socket=f"sv-test-off-{os.getpid()}")   # no store on this server
        self.sessions("store", "alpha")
        lines = self.once()
        store_row = next(line for line in lines if line.strip().endswith("⋯"))
        rows = project_rows(lines, store_row.strip()[:-2])
        self.assertEqual(sorted(rows), ["alpha", "store"])


class Case5aFunctions(ViewBase):
    """§6 case 5a: store_session(rec) for the four session sets of case 4,
    session_items() without the store project, and the store row selected
    while the client is on its session."""

    def test_store_session_for_each_set(self):
        self.place("fx-legacy")
        want = {
            ("fx-legacy", "alpha"): ["fx-legacy", True],
            ("store", "alpha"): ["store", True],
            ("fx-legacy", "store", "alpha"): ["fx-legacy", True],
            ("alpha",): ["fx-legacy", False],
        }
        for names, expect in want.items():
            with self.subTest(sessions=names):
                self.pt.tmux("kill-server")
                self.sessions(*names)
                out = self.harness('''
                    rec = m.row_store()
                    OUT["asked"] = list(m.store_session(rec))
                    OUT["given"] = list(m.store_session(rec, {n for n, _, _ in m.sessions()}))
                ''')
                self.assertEqual(out["asked"], expect)
                self.assertEqual(out["given"], expect)

    def test_store_session_without_a_store(self):
        out = self.harness('OUT["r"] = list(m.store_session({}, {"store", "alpha"}))')
        self.assertEqual(out["r"], ["", False])

    def test_session_items_drop_the_store_project(self):
        for ident, gone in (("fx-legacy", "store"), ("fx-named", "fx-named"), ("fx-corp", "store")):
            with self.subTest(store=ident):
                self.place(ident)
                out = self.harness('OUT["items"] = [i["name"] for i in m.session_items()]')
                self.assertIn("alpha", out["items"])
                self.assertNotIn(gone, out["items"])

    def test_store_project_by_name(self):
        out = {}
        for ident in ("fx-corp", "fx-legacy", "fx-named", "fx-bare"):
            self.place(ident)
            out[ident] = self.harness('OUT["p"] = m.store_project(m.row_store())')["p"]
        self.assertEqual(out, {"fx-corp": "store", "fx-legacy": "store",
                               "fx-named": "fx-named", "fx-bare": ""})

    def test_projects_store_wins_over_identity(self):
        os.makedirs(os.path.join(self.fx.path("fx-legacy"), "projects", "fx-legacy"))
        self.place("fx-legacy")
        out = self.harness('''
            OUT["p"] = m.store_project(m.row_store())
            OUT["items"] = [i["name"] for i in m.session_items()]
        ''')
        self.assertEqual(out["p"], "store")
        self.assertNotIn("store", out["items"])

    def test_store_row_selected_when_on_its_session(self):
        self.place("fx-legacy")
        self.sessions("store", "alpha")
        body = '''
            m.current_session = lambda: CUR
            lines, targets = m.render_base(40)
            i = next(k for k, t in targets.items() if t[0] == "store-dots")
            OUT["sel"] = lines[i].startswith(m.BG_SEL)
        '''
        self.assertTrue(self.harness('CUR = "store"\n' + textwrap.dedent(body))["sel"])
        self.assertFalse(self.harness('CUR = "alpha"\n' + textwrap.dedent(body))["sel"])

    def test_store_row_click_splits_at_the_dots(self):
        out = self.harness('''
            OUT["r"] = [m.store_row_click(0, 2, 12), m.store_row_click(0, 10, 12),
                        m.store_row_click(0, 11, 12), m.store_row_click(0, 12, 12),
                        m.store_row_click(0, 13, 12), m.store_row_click(2, 2, 12),
                        m.store_row_click(2, 12, 12)]
        ''')
        self.assertEqual(out["r"], ["open", "open", "switch", "switch", "switch", "kick", "kick"])


class Case5bSwitchStoreMenu(ViewBase):
    """§6 case 5b (design §4, Q1 and Q4): switch_store_menu() is an
    overlay MENU titled "Switch store", one item per store in stores()
    order, no Kick; a pick is open_store; `s` opens it; MODE = "stores" and
    its store / store-pick targets are gone."""

    def test_the_modal(self):
        self.place("fx-legacy", live=True, session_count=2)
        out = self.harness('''
            m.switch_store_menu()
            OUT["title"] = m.MENU["title"]
            OUT["items"] = [[l, k, bool(a)] for l, k, a in m.MENU["items"]]
            OUT["cur"] = m.MENU["cur"]
            OUT["names"] = [m.store_name(s) for s in m.stores()]
            OUT["prompt"] = m.PROMPT
        ''')
        self.assertEqual(out["title"], "Switch store")
        self.assertEqual([i[0] for i in out["items"]], out["names"])
        self.assertEqual(out["names"], ["fx-corp", "fx-legacy", "fx-named", "fx-bare"])
        self.assertNotIn("Kick", [i[0] for i in out["items"]], "the modal switches only (Q1)")
        self.assertTrue(all(i[2] for i in out["items"]), "every store is pickable, down ones too")
        # the badge: x<sessions> when live, blank when down
        self.assertEqual([i[1] for i in out["items"]], ["", "x2", "", ""])
        self.assertEqual(out["cur"], 1, "the viewed store sits under the cursor")
        self.assertIsNone(out["prompt"])

    def test_a_pick_is_open_store(self):
        self.place("fx-legacy")
        out = self.harness('''
            calls = []
            m.open_store = lambda n: calls.append(n)
            m.switch_store_menu()
            m.menu_keys("f")                  # no letter keys: names share initials
            OUT["open_after_letter"] = m.MENU is not None
            m.menu_keys("\\x1b[B\\r")       # down from fx-legacy, enter
            OUT["after_key"] = [list(calls), m.MENU]
            m.switch_store_menu()
            m.menu_pick(0)                    # a click on the first row
            OUT["after_click"] = [list(calls), m.MENU]
        ''')
        self.assertTrue(out["open_after_letter"])
        self.assertEqual(out["after_key"], [["fx-named"], None])
        self.assertEqual(out["after_click"], [["fx-named", "fx-corp"], None])

    def test_a_pick_opens_the_store_as_the_name_does(self):
        """End to end: picking a DOWN store boots it through tm and jumps to
        its store session - open_store's whole path, not a view change."""
        self.place("fx-named")
        self.assertFalse(self.pt.alive())
        out = self.harness('''
            jumps = []
            m.jump = lambda t: jumps.append(list(t))
            m.switch_store_menu()
            m.menu_pick([l for l, _k, _a in m.MENU["items"]].index("fx-named"))
            OUT.update(jumps=jumps, sock=m.SOCK, prompt=m.PROMPT, menu=m.MENU)
        ''')
        self.assertIsNone(out["prompt"], out["prompt"])
        self.assertIsNone(out["menu"])
        self.assertEqual(out["jumps"], [["session", "fx-named"]])
        self.assertEqual(out["sock"], self.pt.sock)
        self.assertEqual([line for line in self.fx.log() if line.startswith("store boot")],
                         ["store boot fx-named"])
        self.assertIn("tasks", [n for _, n, _ in self.pt.windows("fx-named")])

    def test_no_stores_is_one_greyed_line_that_says_why(self):
        wrap = os.path.join(self.home, "nostores")
        os.makedirs(wrap)
        with open(os.path.join(wrap, "tm"), "w") as f:
            f.write('#!/bin/sh\n[ "$1 $2" = "store list" ] && exit 1\n'
                    f'exec {os.path.join(self.fx.bin, "tm")} "$@"\n')
        os.chmod(os.path.join(wrap, "tm"), 0o755)
        self.env["PATH"] = wrap + os.pathsep + self.env["PATH"]
        out = self.harness('''
            m.switch_store_menu()
            OUT["items"] = [[l, k, bool(a)] for l, k, a in m.MENU["items"]]
            m.menu_keys("\\r")                # enter on a greyed line does nothing
            OUT["still"] = m.MENU is not None
        ''')
        self.assertEqual(out["items"], [["tm store list failed (rc 1)", "", False]])
        self.assertTrue(out["still"])

    def test_s_opens_the_modal_over_an_unchanged_sidebar(self):
        self.place("fx-legacy")
        self.sessions("store", "alpha")
        out = self.harness('''
            OUT["s_is_modal"] = m.KEYS["s"] is m.switch_store_menu
            base, btargets = m.render_base(40)
            m.KEYS["s"]()
            lines, targets = m.overlay(base, btargets)
            plain = [m.ANSI_RE.sub("", l).rstrip() for l in lines]
            OUT["title_rows"] = [l for l in plain if "Switch store" in l]
            OUT["items"] = sorted(v for k, (w, v) in targets.items() if w == "menu-item")
            # the store row and the rows above the box are what they were
            i = next(k for k, t in btargets.items() if t[0] == "store-dots")
            OUT["row_kept"] = lines[i] == base[i]
            OUT["store_row"] = plain[i].strip()
            OUT["base_kinds"] = sorted({t[0] for t in btargets.values()})
            OUT["has_mode"] = hasattr(m, "MODE") or hasattr(m, "toggle_stores")
        ''')
        self.assertTrue(out["s_is_modal"])
        self.assertEqual(len(out["title_rows"]), 1, out["title_rows"])
        self.assertEqual(out["items"], [0, 1, 2, 3])
        self.assertTrue(out["row_kept"])
        self.assertEqual(out["store_row"], "fx-legacy ⋯")
        self.assertNotIn("store", out["base_kinds"])
        self.assertNotIn("store-pick", out["base_kinds"])
        self.assertFalse(out["has_mode"], 'MODE = "stores" is retired (Q4)')


class Case5dStoreRowClick(ViewBase):
    """§6 case 5d (design §5): the click dispatcher on the store row, fed the
    row's real target from render_base. Left on the name opens the store;
    left on the dots is Switch store; right anywhere is store_menu (Kick)."""

    def test_dispatch(self):
        self.place("fx-legacy")
        self.sessions("store", "alpha")
        out = self.harness('''
            opened = []
            m.open_store = lambda n: opened.append(n)
            _lines, targets = m.render_base(40)
            val = next(t[1] for t in targets.values() if t[0] == "store-dots")
            name, x0 = val
            OUT["val"] = list(val)
            OUT["name"] = [m.store_row_dispatch(0, 2, val), list(opened), m.MENU]
            OUT["dots"] = [m.store_row_dispatch(0, x0, val), list(opened), m.MENU["title"],
                           [l for l, _k, _a in m.MENU["items"]]]
            m.MENU = None
            OUT["right"] = [m.store_row_dispatch(2, 2, val), list(opened), m.MENU["title"],
                            [[l, bool(a)] for l, _k, a in m.MENU["items"] if l]]
            kick = next(a for l, _k, a in m.MENU["items"] if l == "Kick")
            OUT["kick_cmd"] = kick["a"]["command"]
        ''')
        name, x0 = out["val"]
        self.assertEqual(name, "fx-legacy")
        self.assertEqual(out["name"], ["open", ["fx-legacy"], None])
        self.assertEqual(out["dots"][:3], ["switch", ["fx-legacy"], "Switch store"])
        self.assertNotIn("Kick", out["dots"][3])
        self.assertEqual(out["right"][:3], ["kick", ["fx-legacy"], "fx-legacy"])
        self.assertIn(["Kick", True], out["right"][3])
        self.assertEqual(out["kick_cmd"], ["tm", "kick", "--store", "{store.name}"])


class Case5cOpenStore(ViewBase):
    """§6 case 5c: open_store() with jump() recording its target."""

    RUN = '''
        calls = []
        m.jump = lambda t: calls.append(list(t))
        m.open_store(NAME)
        OUT.update(jumps=calls, sock=m.SOCK, prompt=m.PROMPT)
    '''

    def open(self, name):
        return self.harness(f"NAME = {name!r}\n" + textwrap.dedent(self.RUN))

    def test_a_down_store_is_booted_by_tm_and_lands_on_tasks(self):
        self.place("fx-named")
        self.assertFalse(self.pt.alive())
        out = self.open("fx-named")
        self.assertIsNone(out["prompt"], out["prompt"])
        self.assertEqual(out["jumps"], [["session", "fx-named"]])
        self.assertEqual(out["sock"], self.pt.sock)
        self.assertEqual([line for line in self.fx.log() if line.startswith("store boot")],
                         ["store boot fx-named"])
        names = [n for _, n, _ in self.pt.windows("fx-named")]
        self.assertEqual(names[1:], ["tasks", "slipbox", "scripts", "messages"])
        self.assertEqual(next(n for _, n, a in self.pt.windows("fx-named") if a), "tasks",
                         "a booted store must land on tasks (--fresh)")
        env = self.pt.tmux("show-environment", "-g", "TASKMASTER_STORE")
        self.assertEqual(env.stdout.strip(), "TASKMASTER_STORE=fx-named")
        self.assertEqual(self.pt.sessions(), ["fx-named"], "no store session may be made")

    def test_a_live_store_opens_the_legacy_session_and_is_not_booted(self):
        self.place("fx-legacy", live=True)
        self.sessions("store", "alpha")
        self.pt.tmux("rename-window", "-t", "=store:", "work")
        out = self.open("fx-legacy")
        self.assertIsNone(out["prompt"], out["prompt"])
        self.assertEqual(out["jumps"], [["session", "store"]])
        self.assertFalse(any(line.startswith("store boot") for line in self.fx.log()), self.fx.log())
        self.assertEqual(sorted(self.pt.sessions()), ["alpha", "store"], "fx-legacy was created")
        self.assertEqual([n for _, n, _ in self.pt.windows("store")],
                         ["work", "tasks", "slipbox", "scripts", "messages"])
        self.assertEqual(next(n for _, n, a in self.pt.windows("store") if a), "work",
                         "an existing session keeps its current window (Q8)")

    def test_a_live_server_without_either_session_creates_the_identity(self):
        self.place("fx-corp", live=True)
        self.sessions("alpha")
        out = self.open("fx-corp")
        self.assertIsNone(out["prompt"], out["prompt"])
        self.assertEqual(out["jumps"], [["session", "fx-corp"]])
        self.assertEqual(sorted(self.pt.sessions()), ["alpha", "fx-corp"])
        self.assertFalse(any(line.startswith("store boot") for line in self.fx.log()), self.fx.log())

    def test_an_unknown_store_is_a_note(self):
        self.place("fx-legacy")
        out = self.open("nope")
        self.assertEqual(out["jumps"], [])
        self.assertEqual(out["prompt"]["label"], "no store nope")
        self.assertFalse(self.pt.alive())

    def test_a_failed_boot_is_a_note_and_nothing_opens(self):
        self.place("fx-named")
        # a tm whose boot fails (first on PATH); every other verb is the shim's
        wrap = os.path.join(self.home, "failboot")
        os.makedirs(wrap)
        with open(os.path.join(wrap, "tm"), "w") as f:
            f.write('#!/bin/sh\n[ "$1 $2" = "store boot" ] && { echo "tm: boot refused: $3" >&2; exit 1; }\n'
                    f'exec {os.path.join(self.fx.bin, "tm")} "$@"\n')
        os.chmod(os.path.join(wrap, "tm"), 0o755)
        self.env["PATH"] = wrap + os.pathsep + self.env["PATH"]
        out = self.open("fx-named")
        self.assertEqual(out["jumps"], [])
        self.assertEqual(out["prompt"]["title"], "store")
        self.assertEqual(out["prompt"]["label"], "tm: boot refused: fx-named")
        self.assertFalse(self.pt.alive(), "a server came up without tm")


if __name__ == "__main__":
    unittest.main()
