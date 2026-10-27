"""The first-open question is documented word for word where a user meets it.

The first time sessionview opens, bin/sessionview-autostart asks which agent
to start. Its prompts were once nowhere in the docs, so a stranger met an
unexplained question, and the README credited the question to the dock app's
name instead of sessionview. Each prompt the script prints is quoted in the
README's feature list and in docs/sessionview.md, and the script still
prints each one, so neither side can change alone.
"""
import os
import re
import unittest

from tests import support

AUTOSTART = os.path.join(support.BIN, "sessionview-autostart")
DOCS = ("README.md", os.path.join("docs", "sessionview.md"))

#: What ask() prints: the headline, the numbered list's prompt, and the
#: prompt it asks when the agent list cannot be had.
PROMPTS = (
    "sessionview can start an agent for you each time it opens",
    'Which? (number, name, or "n")',
    'Which agent? (a name, or "no" to never ask again)',
)


def read(rel):
    with open(os.path.join(support.REPO, rel), encoding="utf-8") as f:
        return f.read()


def flat(text):
    """TEXT with every run of whitespace as one space: a quote may wrap."""
    return re.sub(r"\s+", " ", text)


class FirstOpenQuestion(unittest.TestCase):
    def test_the_script_prints_each_prompt(self):
        script = read(os.path.relpath(AUTOSTART, support.REPO))
        for prompt in PROMPTS:
            with self.subTest(prompt=prompt):
                self.assertIn(prompt, script)

    def test_each_doc_quotes_each_prompt(self):
        for rel in DOCS:
            text = flat(read(rel))
            for prompt in PROMPTS:
                with self.subTest(doc=rel, prompt=prompt):
                    self.assertIn(prompt, text)

    def test_the_readme_says_sessionview_asks(self):
        m = re.search(r"(?ms)^- \*Consent on first open\* — (.*?)(?=^- |^\s*$)", read("README.md"))
        self.assertIsNotNone(m, "no 'Consent on first open' bullet in the README")
        bullet = flat(m.group(1))
        self.assertTrue(bullet.startswith("the first time it opens, sessionview asks"), bullet)
        self.assertNotIn("Dreamcatcher", bullet)


if __name__ == "__main__":
    unittest.main()
