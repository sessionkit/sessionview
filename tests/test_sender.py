"""Who session view's mail is FROM: bin/sessionview-from (the one resolver)
and bin/sessionview-send (message send AS that name), and that the sidebar,
a plugin action and the voicemode speak script all go through them.

Order, first non-empty wins: $SESSIONVIEW_FROM, $SESSIONVIEW_MENU_FROM,
config mail_from, config pane_menu_from, $USER, "sessionview".

`message` is a stub first on PATH that records the environment it ran with,
so nothing is ever sent. HOME, SESSIONVIEW_CONFIG and SESSIONVIEW_STATE are scratch;
the real home settings are never read or written.
"""
import codecs
import json
import os
import subprocess
import sys
import textwrap
import unittest

from tests import support

#: A `message` that records CLAUDE_CODE_AGENT, EMAIL, TM_AGENT_ADDRESS and its
#: argv, one JSON object, into $STUB_OUT. Python, so the record is exact.
STUB = textwrap.dedent("""\
    #!/bin/sh
    exec "{python}" -c '
    import json, os, sys
    rec = {{k: os.environ.get(k) for k in ("CLAUDE_CODE_AGENT", "EMAIL", "TM_AGENT_ADDRESS")}}
    rec["argv"] = sys.argv[1:]
    open(os.environ["STUB_OUT"], "w").write(json.dumps(rec))
    ' "$@"
    """)


class SenderCase(unittest.TestCase):
    """A scratch HOME, a scratch config file, a stub `message` on PATH."""

    def setUp(self):
        self._ctx = support.scratch_env()
        self.env, self.home = self._ctx.__enter__()
        self.cfg = os.path.join(self.home, "scratch", "config.json")
        self.env["SESSIONVIEW_CONFIG"] = self.cfg
        self.env["SESSIONVIEW_STATE"] = os.path.join(self.home, "state")
        stub_dir = self.stub_dir = os.path.join(self.home, "stub-bin")
        os.makedirs(stub_dir)
        stub = os.path.join(stub_dir, "message")
        with open(stub, "w") as f:
            f.write(STUB.format(python=sys.executable))
        os.chmod(stub, 0o755)
        self.out = os.path.join(self.home, "stub-out.json")
        self.env["STUB_OUT"] = self.out
        self.env["PATH"] = stub_dir + os.pathsep + self.env.get("PATH", "")
        # an agent's identity leaking in from the tmux server must lose
        self.env["EMAIL"] = "agent@example.invalid"
        self.env["TM_AGENT_ADDRESS"] = "worker.example"

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def config(self, **keys):
        os.makedirs(os.path.dirname(self.cfg), exist_ok=True)
        with open(self.cfg, "w", encoding="utf-8") as f:
            json.dump(keys, f)

    def resolved(self):
        r = support.run("sessionview-from", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.rstrip("\n")

    def recorded(self):
        with open(self.out, encoding="utf-8") as f:
            return json.load(f)


class ResolverOrder(SenderCase):
    """Each source set in turn, everything above it unset; then none set."""

    def setUp(self):
        super().setUp()
        self.env["USER"] = "login-name"
        self.config(mail_from="cfg-mail", pane_menu_from="cfg-pane")
        self.env["SESSIONVIEW_MENU_FROM"] = "env-menu"
        self.env["SESSIONVIEW_FROM"] = "env-from"

    def test_1_sessionview_from_wins(self):
        self.assertEqual(self.resolved(), "env-from")

    def test_2_sessionview_menu_from_is_honoured(self):
        del self.env["SESSIONVIEW_FROM"]
        self.assertEqual(self.resolved(), "env-menu")

    def test_3_config_mail_from(self):
        del self.env["SESSIONVIEW_FROM"], self.env["SESSIONVIEW_MENU_FROM"]
        self.assertEqual(self.resolved(), "cfg-mail")

    def test_4_old_pane_menu_from_is_honoured(self):
        del self.env["SESSIONVIEW_FROM"], self.env["SESSIONVIEW_MENU_FROM"]
        self.config(pane_menu_from="cfg-pane")
        self.assertEqual(self.resolved(), "cfg-pane")

    def test_5_user(self):
        del self.env["SESSIONVIEW_FROM"], self.env["SESSIONVIEW_MENU_FROM"]
        self.config()
        self.assertEqual(self.resolved(), "login-name")

    def test_6_none_set_is_the_neutral_word(self):
        del self.env["SESSIONVIEW_FROM"], self.env["SESSIONVIEW_MENU_FROM"], self.env["USER"]
        self.config()
        self.assertEqual(self.resolved(), "sessionview")

    def test_empty_and_blank_values_fall_through(self):
        self.env["SESSIONVIEW_FROM"] = "  "
        self.env["SESSIONVIEW_MENU_FROM"] = ""
        self.config(mail_from=" ", pane_menu_from="")
        self.assertEqual(self.resolved(), "login-name")

    def test_template_defaults_name_nobody(self):
        """A fresh install (no home file: it is made from the template) with
        no USER says the neutral word: the template sets no sender."""
        del self.env["SESSIONVIEW_FROM"], self.env["SESSIONVIEW_MENU_FROM"], self.env["USER"]
        os.remove(self.cfg)
        self.assertEqual(self.resolved(), "sessionview")
        with open(os.path.join(support.CONFIG, "config.json"), encoding="utf-8") as f:
            tpl = json.load(f)
        self.assertEqual(tpl["mail_from"], "")
        self.assertEqual(tpl["pane_menu_from"], "")


class SendsAsResolvedName(SenderCase):
    """Every mailing path runs `message send` with CLAUDE_CODE_AGENT = the
    resolved name and EMAIL / TM_AGENT_ADDRESS unset."""

    def setUp(self):
        super().setUp()
        self.env["SESSIONVIEW_FROM"] = "the-human"

    def assertSentAsHuman(self, want_argv):
        rec = self.recorded()
        self.assertEqual(rec["CLAUDE_CODE_AGENT"], "the-human")
        self.assertIsNone(rec["EMAIL"])
        self.assertIsNone(rec["TM_AGENT_ADDRESS"])
        self.assertEqual(rec["argv"], want_argv)

    def test_sessionview_send(self):
        r = support.run("sessionview-send", "abc12345", "-s", "hi", "--no-body", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertSentAsHuman(["send", "abc12345", "-s", "hi", "--no-body"])

    def test_sessionview_send_fallback_is_user(self):
        del self.env["SESSIONVIEW_FROM"]
        self.env["USER"] = "login-name"
        r = support.run("sessionview-send", "abc12345", "--no-body", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.recorded()["CLAUDE_CODE_AGENT"], "login-name")

    def test_sessionview_send_without_message_says_so(self):
        self.env["PATH"] = "/usr/bin:/bin"
        r = support.run("sessionview-send", "abc12345", "--no-body", env=self.env)
        self.assertEqual(r.returncode, 127)
        self.assertIn("install sessionmail", r.stderr)

    def sidebar(self, code):
        """Load bin/tmux-sidebar as a module in a child and run CODE in it."""
        prog = textwrap.dedent("""\
            import importlib.machinery, importlib.util, sys
            path = sys.argv[1]
            loader = importlib.machinery.SourceFileLoader("sidebar", path)
            spec = importlib.util.spec_from_loader("sidebar", loader)
            sb = importlib.util.module_from_spec(spec)
            loader.exec_module(sb)
            """) + textwrap.dedent(code)
        r = subprocess.run([sys.executable, "-B", "-c", prog, os.path.join(support.BIN, "tmux-sidebar")],
                           env=self.env, capture_output=True, text=True, timeout=60, cwd=support.REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_sidebar_mail(self):
        self.sidebar("""\
            r = sb.mail("abc12345", "hello `there`")
            assert r.returncode == 0, r.stderr
            """)
        rec = self.recorded()
        self.assertEqual(rec["argv"][:4], ["send", "abc12345", "-s", "hello there"])
        self.assertEqual(rec["argv"][4], "-f")
        self.assertSentAsHuman(rec["argv"])

    def test_plugin_action(self):
        """The session plugin's Continue item, run the way a menu pick runs it.
        The plugin `requires` a `session` command, and plugins() drops it when
        there is none, so a do-nothing stub stands in: the suite must not
        depend on what the host has installed."""
        session = os.path.join(self.stub_dir, "session")
        with open(session, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(session, 0o755)
        self.sidebar("""\
            plug = next(p for p in sb.plugins() if p["id"] == "session")
            a = next(a for a in plug["actions"] if a["id"] == "continue")
            r = sb.run_action({"a": a, "plug": plug, "ctx": {"agent.address": "abc12345"}})
            assert r.returncode == 0, (r.stdout, r.stderr)
            """)
        rec = self.recorded()
        self.assertEqual(rec["argv"][:4], ["send", "abc12345", "-s", "continue"])
        self.assertSentAsHuman(rec["argv"])

    def test_voicemode_speak(self):
        speak = os.path.join(support.PLUGINS, "voicemode", "speak")
        r = subprocess.run([speak, "some-agent", "abc12345"], env=self.env,
                           capture_output=True, text=True, timeout=30,
                           cwd=os.path.dirname(speak))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertSentAsHuman(["send", "abc12345", "-s", "speak EOM", "--no-body"])


class NoLiteralSender(unittest.TestCase):
    """Guard: no shipped file names a person as the sender."""

    def test_no_claude_code_agent_set_to_the_operator(self):
        r = subprocess.run(["git", "ls-files", "-z"], cwd=support.REPO,
                           capture_output=True, timeout=30)
        if r.returncode != 0:
            self.skipTest("not a git checkout")
        # the operator's name is rot13 here, so this file names nobody and is
        # not a hit for `git grep` either
        needle = b"CLAUDE_CODE_AGENT=" + codecs.encode("zvxr", "rot13").encode()
        hits = []
        for rel in r.stdout.decode().split("\0"):
            p = os.path.join(support.REPO, rel)
            if not rel or not os.path.isfile(p):
                continue
            with open(p, "rb") as f:
                for n, line in enumerate(f, 1):
                    if needle in line:
                        hits.append(f"{rel}:{n}")
        self.assertEqual(hits, [])

    def test_every_mailing_plugin_action_uses_sessionview_send(self):
        import tomllib
        for d in sorted(os.listdir(support.PLUGINS)):
            f = os.path.join(support.PLUGINS, d, "plugin.toml")
            if not os.path.isfile(f):
                continue
            with open(f, "rb") as fh:
                m = tomllib.load(fh)
            for a in m.get("actions", []):
                cmd = a.get("command", [])
                if "message" in cmd or "CLAUDE_CODE_AGENT" in " ".join(cmd):
                    self.fail(f"{d}/{a.get('id')}: mails without bin/sessionview-send: {cmd}")
                if cmd and cmd[0].endswith("sessionview-send"):
                    exe = os.path.normpath(os.path.join(support.PLUGINS, d, cmd[0]))
                    self.assertTrue(os.access(exe, os.X_OK), f"{d}/{a.get('id')}: {exe}")


if __name__ == "__main__":
    unittest.main()
