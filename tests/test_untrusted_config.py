"""SV-145: a store's or project's `.sessionview` never sets a key
that RUNS something.

Trust is by a layer's POSITION in sessionview-config's cascade: the template
and the home file (layers 1-2) are trusted; STORE/.sessionview and every
`.sessionview` walked up from --project are not. From an untrusted layer,
`agent_command` is dropped, and a `windows` / `store_windows` entry keeps its
data but not its `command` (the trusted command of the same name stands in,
else none).

Nothing here executes a planted command: sessionview-config only prints, and
sessionview-session runs with --print on a private socket
(support.private_tmux) that is never started.
"""
import json
import os
import unittest

from tests import support

PLANT = "touch /tmp/SV145-PWNED"
PLANT_AGENT = ["sh", "-c", "touch /tmp/SV145-PWNED-agent"]
HOME_CMD = "echo home-layer-git"
HOME_AGENT = ["echo", "home-layer-agent", "{agent}"]


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def planted(extra_windows=()):
    """A repo layer that tries both executing keys, plus one data key."""
    return {
        "width": 51,
        "windows": [
            {"name": "pwn", "position": 1, "when": "always", "cwd": "root", "command": PLANT},
            {"name": "git", "position": 2, "when": "has_repo", "cwd": "repo", "command": PLANT},
            *extra_windows,
        ],
        "agent_command": PLANT_AGENT,
    }


class UntrustedBase(unittest.TestCase):
    TAG = "untrust"

    def setUp(self):
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self._pt = support.private_tmux(self.TAG)
        self.pt = self._pt.__enter__()
        self.fx = support.StoreFixtures(os.path.join(self.home, "fx"), self.pt)
        self.env = self.fx.env(env)
        self.cfg = self.env["SESSIONVIEW_CONFIG"]
        with open(os.path.join(support.CONFIG, "config.json"), encoding="utf-8") as f:
            self.template = json.load(f)
        # a planted checkout: a .git dir (has_repo holds) and a .sessionview
        self.repo = os.path.realpath(os.path.join(self.home, "work", "evil"))
        os.makedirs(os.path.join(self.repo, ".git"))
        self.dot = os.path.join(self.repo, ".sessionview")
        write_json(self.dot, planted())

    def tearDown(self):
        self._pt.__exit__(None, None, None)
        self._scratch.__exit__(None, None, None)

    def cli(self, *args):
        return support.run("sessionview-config", *args, env=self.env)

    def rows(self, *args):
        """{name: the TSV row's fields} from `sessionview-config windows ARGS`."""
        r = self.cli("windows", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return {f[1]: f for f in (line.split("\t") for line in r.stdout.splitlines())}, r.stderr

    def project_plan(self, name="evil"):
        r = support.run("sessionview-session", name, "--socket", self.pt.sock,
                        "--store", self.fx.path("fx-legacy"), "--repo", self.repo,
                        "--print", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.pt.alive(), "--print started a server")
        return r.stderr

    def send_keys(self, plan):
        return [line for line in plan.splitlines() if "send-keys" in line]


class ProjectLayer(UntrustedBase):
    """Spec tests 1, 2 and 6: the planted repo's own .sessionview."""

    def test_windows_carry_no_planted_command(self):
        rows, err = self.rows("--project", self.repo)
        self.assertNotIn(PLANT, "\t".join("\t".join(f) for f in rows.values()))
        self.assertEqual(rows["pwn"][4], "-", "a new name from a repo layer is a plain shell")
        git = next(w for w in self.template["windows"] if w["name"] == "git")
        self.assertEqual(rows["git"][4], git["command"], "a known name keeps the trusted command")
        # each drop is named once, with the file
        self.assertEqual(err.count(f"{self.dot}: windows[pwn].command ignored"), 1, err)
        self.assertEqual(err.count(f"{self.dot}: windows[git].command ignored"), 1, err)

    def test_agent_command_is_the_trusted_value(self):
        r = self.cli("get", "agent_command", "--project", self.repo, "--json", "--where")
        self.assertEqual(r.returncode, 0, r.stderr)
        val, src = r.stdout.rstrip("\n").split("\t")
        self.assertEqual(json.loads(val), self.template["agent_command"])
        self.assertEqual(src, self.cfg, "--where must name the home file, not the repo's")
        self.assertIn(f"{self.dot}: agent_command ignored", r.stderr)

    def test_dump_where_never_names_the_repo_for_agent_command(self):
        r = self.cli("dump", "--project", self.repo, "--where")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(PLANT, r.stdout)
        line = next(l for l in r.stdout.splitlines() if l.startswith("agent_command\t"))
        self.assertFalse(line.endswith(self.dot), line)
        r = self.cli("get", "windows", "--project", self.repo, "--json")
        self.assertNotIn(PLANT, r.stdout)

    def test_print_types_no_planted_command(self):
        keys = self.send_keys(self.project_plan())
        self.assertTrue(keys, "the plan typed nothing at all: the test is not looking")
        for line in keys:
            self.assertNotIn("SV145-PWNED", line)
        self.assertFalse(any("=evil:pwn" in l for l in keys), keys)
        self.assertIn("lazygit", "\n".join(keys))

    def test_data_keys_still_apply(self):
        r = self.cli("get", "width", "--project", self.repo, "--where")
        self.assertEqual(r.stdout.rstrip("\n").split("\t"), ["51", self.dot])
        rows, _ = self.rows("--project", self.repo)
        # the repo's list replaced the template's: its order, its names, its dirs
        self.assertEqual(list(rows), ["pwn", "git"])
        self.assertEqual(rows["pwn"][:4], ["1", "pwn", "always", "root"])
        plan = self.project_plan()
        self.assertIn("new-window -t =evil -c", plan)
        self.assertIn("-n git", plan)

    def test_a_copy_of_the_trusted_list_is_quiet(self):
        """A project that only reorders the shipped tabs is told nothing."""
        lst = [dict(w, position=100 - w["position"]) for w in self.template["windows"]]
        write_json(self.dot, {"windows": lst})
        rows, err = self.rows("--project", self.repo)
        self.assertNotIn("ignored", err)
        for w in self.template["windows"]:
            self.assertEqual(rows[w["name"]][4], w.get("command") or "-")

    def test_an_empty_command_stays_empty(self):
        """A repo that turns a shipped tab's command OFF is honoured: nothing runs."""
        write_json(self.dot, {"windows": [{"name": "git", "position": 1, "when": "has_repo",
                                           "cwd": "repo", "command": ""}]})
        rows, err = self.rows("--project", self.repo)
        self.assertEqual(rows["git"][4], "-")
        self.assertNotIn("ignored", err)


class StoreLayer(UntrustedBase):
    """Spec test 3: STORE/.sessionview, for `windows` and `store_windows`."""

    def setUp(self):
        super().setUp()
        self.store = self.fx.path("fx-legacy")
        self.sdot = os.path.join(self.store, ".sessionview")
        data = planted()
        data["store_windows"] = [
            {"name": "pwn", "position": 1, "when": "always", "cwd": "store", "command": PLANT},
            {"name": "slipbox", "position": 2, "when": "has_slipbox", "cwd": "slipbox", "command": PLANT},
        ]
        write_json(self.sdot, data)
        os.remove(self.dot)

    def test_store_windows_carry_no_planted_command(self):
        rows, err = self.rows("--key", "store_windows", "--store", self.store)
        self.assertNotIn(PLANT, "\t".join("\t".join(f) for f in rows.values()))
        self.assertEqual(rows["pwn"][4], "-")
        slip = next(w for w in self.template["store_windows"] if w["name"] == "slipbox")
        self.assertEqual(rows["slipbox"][4], slip["command"])
        self.assertIn(f"{self.sdot}: store_windows[pwn].command ignored", err)

    def test_windows_and_agent_command_from_the_store(self):
        rows, _ = self.rows("--store", self.store)
        self.assertNotIn(PLANT, "\t".join("\t".join(f) for f in rows.values()))
        r = self.cli("get", "agent_command", "--store", self.store, "--json", "--where")
        val, src = r.stdout.rstrip("\n").split("\t")
        self.assertEqual(json.loads(val), self.template["agent_command"])
        self.assertEqual(src, self.cfg)

    def test_store_view_print_types_no_planted_command(self):
        r = support.run("sessionview-session", "fx-legacy", "--store-view", "fx-legacy",
                        "--socket", self.pt.sock, "--store", self.store, "--print", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.pt.alive(), "--print started a server")
        keys = self.send_keys(r.stderr)
        self.assertTrue(keys, r.stderr)
        for line in keys:
            self.assertNotIn("SV145-PWNED", line)

    def test_project_print_with_a_planted_store(self):
        for line in self.send_keys(self.project_plan()):
            self.assertNotIn("SV145-PWNED", line)


class HomeLayer(UntrustedBase):
    """Spec test 4: the home layer (SESSIONVIEW_CONFIG) still sets both."""

    def setUp(self):
        super().setUp()
        home = dict(self.template)
        home["windows"] = [dict(w, command=HOME_CMD) if w["name"] == "git" else w
                           for w in self.template["windows"]]
        home["agent_command"] = HOME_AGENT
        write_json(self.cfg, home)

    def test_home_agent_command_wins_over_the_repo(self):
        r = self.cli("get", "agent_command", "--project", self.repo, "--json", "--where")
        val, src = r.stdout.rstrip("\n").split("\t")
        self.assertEqual(json.loads(val), HOME_AGENT)
        self.assertEqual(src, self.cfg)

    def test_home_command_is_typed(self):
        rows, _ = self.rows()
        self.assertEqual(rows["git"][4], HOME_CMD)
        # and through a repo layer's list, by name
        rows, _ = self.rows("--project", self.repo)
        self.assertEqual(rows["git"][4], HOME_CMD)
        self.assertIn(f"send-keys -t =evil:git {HOME_CMD} C-m", self.project_plan())


class TrustByPosition(UntrustedBase):
    """Spec test 5, by POSITION: the default home file is
    ~/.sessionkit/view/settings/view.json, which no walk-up can reach (a walk
    looks only for `.sessionview`). What a walk up from --project CAN reach is
    a leftover OLD home file, ~/.sessionview/config.json, left behind beside a
    moved one: it is a PROJECT-chain layer, untrusted though it was once the
    home file. The default home is used here (no SESSIONVIEW_CONFIG), and it
    exists, so the unmoved-file refusal does not fire."""

    def setUp(self):
        super().setUp()
        os.remove(self.dot)
        del self.env["SESSIONVIEW_CONFIG"]
        r = self.cli("init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.cfg = os.path.join(self.home, ".sessionkit", "view", "settings", "view.json")
        self.assertEqual(r.stdout.strip(), self.cfg)
        self.leftover = os.path.join(self.home, ".sessionview", "config.json")
        write_json(self.leftover, planted())

    def test_a_leftover_old_home_file_is_untrusted_when_walked_to(self):
        rows, err = self.rows("--project", self.repo)
        self.assertNotIn(PLANT, "\t".join("\t".join(f) for f in rows.values()))
        self.assertIn("windows[pwn].command ignored", err)
        r = self.cli("get", "agent_command", "--project", self.repo, "--json", "--where")
        val, src = r.stdout.rstrip("\n").split("\t")
        self.assertEqual(json.loads(val), self.template["agent_command"])
        self.assertEqual(src, self.cfg)
        # its data keys still apply, as any project layer's do
        r = self.cli("get", "width", "--project", self.repo, "--where")
        self.assertEqual(r.stdout.rstrip("\n").split("\t")[0], "51")

    def test_print_types_no_planted_command(self):
        for line in self.send_keys(self.project_plan()):
            self.assertNotIn("SV145-PWNED", line)


class FieldInjection(UntrustedBase):
    """Peer review of fix-001: the `windows` TSV is read by the shell with
    IFS=TAB, a row per line. A TAB or a line break in a DATA field (name,
    when, cwd) from an untrusted layer shifted the planted text into the
    command column, or began a row of its own, and it was typed with Enter,
    though untrusted() had dropped every `command`. Each field is one cell."""

    INJECT = [
        {"name": "a\talways\troot\t" + PLANT + "-name", "position": 1},
        {"name": "b", "position": 2, "when": "always\troot\t" + PLANT + "-when"},
        {"name": "c", "position": 3, "when": "always", "cwd": "root\t" + PLANT + "-cwd"},
        {"name": "d\n4\tnl\talways\troot\t" + PLANT + "-newline\tfalse\t-\tfalse", "position": 4},
        {"name": "e", "position": 5, "when": "\t", "cwd": "\r\n"},
    ]

    def setUp(self):
        super().setUp()
        write_json(self.dot, {"windows": self.INJECT})

    def test_every_row_has_eight_cells_and_no_command(self):
        r = self.cli("windows", "--project", self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), len(self.INJECT), "a line break began a row of its own")
        for line in lines:
            f = line.split("\t")
            self.assertEqual(len(f), 8, repr(line))
            self.assertTrue(all(f), f"an empty cell shifts the columns: {line!r}")
            self.assertEqual(f[4], "-", f"a command from a data field: {line!r}")
        # an emptied field falls back to its default
        e = next(l.split("\t") for l in lines if l.split("\t")[1] == "e")
        self.assertEqual(e[2:4], ["always", "root"])

    def test_print_types_no_injected_command(self):
        plan = self.project_plan()
        for line in self.send_keys(plan):
            self.assertNotIn("SV145-PWNED", line)



# A harmless marker wrapped in control characters: ESC [ 31 m (red), DEL, the
# C1 CSI (0x9b) and BEL. Printed raw, a terminal would take them as commands.
CONTROLS = ("\x1b", "\x7f", "\x9b", "\x07")
CTRL_NAME = "tab\x1b[31mMARK\x7f\x9b0m\x07"
CTRL_SHOWN = "tab[31mMARK0m"


class ControlCharacters(UntrustedBase):
    """An untrusted window name reaches the terminal with no control character
    in it: in the notice that its command was ignored, in the `windows` rows,
    and in sessionview-session's --print plan, which prints both."""

    def setUp(self):
        super().setUp()
        write_json(self.dot, planted(extra_windows=(
            {"name": CTRL_NAME, "position": 3, "when": "always", "cwd": "root", "command": PLANT},
            {"name": "\x1b\x07", "position": 4, "when": "always", "cwd": "root"},
        )))

    def assertClean(self, text, where):
        for c in CONTROLS:
            self.assertNotIn(c, text, f"{where} holds {c!r}: {text!r}")

    def test_the_notice_and_the_rows_carry_no_control_character(self):
        rows, err = self.rows("--project", self.repo)
        r = self.cli("windows", "--project", self.repo)
        self.assertClean(r.stdout, "windows rows")
        self.assertClean(err, "the notice")
        self.assertIn(f"{self.dot}: windows[{CTRL_SHOWN}].command ignored", err)
        self.assertEqual(rows[CTRL_SHOWN][:5], ["3", CTRL_SHOWN, "always", "root", "-"])

    def test_a_name_of_control_characters_only_is_no_name(self):
        rows, err = self.rows("--project", self.repo)
        self.assertIn("windows[3]: needs a name (skipped)", err)
        self.assertEqual(list(rows), ["pwn", "git", CTRL_SHOWN])

    def test_the_print_plan_carries_no_control_character(self):
        plan = self.project_plan()
        self.assertClean(plan, "the --print plan")
        self.assertIn(f"-n {CTRL_SHOWN}", plan)
        self.assertIn(f"windows[{CTRL_SHOWN}].command ignored", plan)

    def test_list_windows_carries_no_control_character(self):
        r = support.run("sessionview-session", "evil", "--socket", self.pt.sock,
                        "--store", self.fx.path("fx-legacy"), "--repo", self.repo,
                        "--list-windows", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertClean(r.stdout, "--list-windows")
        self.assertIn(CTRL_SHOWN + "\t", r.stdout)


if __name__ == "__main__":
    unittest.main()
