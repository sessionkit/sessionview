"""Docs and installer: no instruction from the retired `session` repo (SV-100).

The old `session` repo bundled mail (`session mail send`, a bash-4 listener)
and was retired into sessiontools (`session`) and sessionmail
(`message`). The shipped skills, the README and the installer must not send a
reader back to it.
"""
import glob
import os
import re
import unittest

from tests import support


def shipped_docs():
    """The shipped skills and the README: what a user or an agent reads."""
    paths = sorted(glob.glob(os.path.join(support.REPO, "skills", "*", "SKILL.md")))
    paths.append(os.path.join(support.REPO, "README.md"))
    return paths


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


INSTALLER = os.path.join(support.BIN, "sessionview-install")

#: A line may NAME the retired verb only to forbid it.
FORBIDS = re.compile(r"\b(never|not|retired|instead of)\b", re.I)

#: github.com/mbailey/session, but not .../sessionview or .../sessionmail.
OLD_REPO = re.compile(r"github\.com/mbailey/session(?![A-Za-z0-9_-])")


class RetiredSessionRepo(unittest.TestCase):
    def test_found_docs(self):
        names = {os.path.relpath(p, support.REPO) for p in shipped_docs()}
        self.assertIn("README.md", names)
        self.assertIn(os.path.join("skills", "sessionview", "SKILL.md"), names)
        self.assertIn(os.path.join("skills", "claude-code", "SKILL.md"), names)

    def test_no_session_mail_send_instruction(self):
        for path in shipped_docs():
            for n, line in enumerate(read(path).splitlines(), 1):
                if "session mail send" in line:
                    with self.subTest(doc=os.path.relpath(path, support.REPO), line=n):
                        self.assertRegex(line, FORBIDS,
                                         "names `session mail send` as an instruction; "
                                         "mail is sessionmail's `message send`")

    def test_mail_is_message_send(self):
        for rel in (("skills", "sessionview", "SKILL.md"), ("skills", "claude-code", "SKILL.md")):
            with self.subTest(doc=os.path.join(*rel)):
                self.assertIn("message send", read(os.path.join(support.REPO, *rel)))

    def test_no_old_repo_pointer(self):
        for path in shipped_docs() + [INSTALLER]:
            with self.subTest(file=os.path.relpath(path, support.REPO)):
                self.assertIsNone(OLD_REPO.search(read(path)))

    def test_old_repo_pattern(self):
        # The pattern itself: the retired repo, not its successors.
        self.assertTrue(OLD_REPO.search("(github.com/mbailey/session)"))
        self.assertFalse(OLD_REPO.search("github.com/mbailey/sessionview"))
        self.assertFalse(OLD_REPO.search("github.com/mbailey/sessionmail"))

    def test_session_is_optional(self):
        text = read(os.path.join(support.REPO, "skills", "sessionview", "SKILL.md"))
        self.assertNotIn("which sessionview requires", text)
        self.assertIn("sessiontools", text)

    def test_without_session_the_mail_items_go(self):
        # The agent menu's mail items are the session plugin's, and that plugin
        # `requires` session: without session the sidebar has no mail, so the
        # README must not say mail is unaffected.
        import tomllib
        with open(os.path.join(support.REPO, "plugins", "session", "plugin.toml"), "rb") as f:
            m = tomllib.load(f)
        self.assertIn("session", m["requires"])
        self.assertIn("message", [a["id"] for a in m["actions"]])
        # The list lives in docs/dependencies.md: sessiontools' row there.
        page = read(os.path.join(support.REPO, "docs", "dependencies.md"))
        row = next(l for l in page.splitlines() if l.startswith("| [sessiontools]"))
        self.assertNotIn("unaffected", row)
        self.assertIn("Message", row)


class Installer(unittest.TestCase):
    def test_no_bash4_gate(self):
        text = read(INSTALLER)
        self.assertNotIn("BASH_VERSINFO", text)
        self.assertNotIn("listener needs 4", text)

    def test_no_uv_line(self):
        # uv only installs sessiontools; the session WARN names it.
        self.assertNotRegex(read(INSTALLER), r"command -v uv\b")

    def test_session_warn_names_sessiontools(self):
        text = read(INSTALLER)
        self.assertIn("uv tool install sessiontools", text)
        self.assertNotIn("no mail", text)

    def test_check_runs_and_says_no_bash(self):
        # --check changes nothing; run it in a scratch HOME and read its report.
        with support.scratch_env() as (env, _home):
            r = support.run("sessionview-install", "--check", env=env)
        self.assertIn("requirements:", r.stdout)
        self.assertNotRegex(r.stdout, r"(?m)^\s+\S+\s+bash ")
        self.assertNotIn("uv not installed", r.stdout)


if __name__ == "__main__":
    unittest.main()
