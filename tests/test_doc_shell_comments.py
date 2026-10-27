"""Guard: a shell line in the docs carries no `#` comment.

zsh is the macOS shell, and at its prompt `interactivecomments` is off, so a
`#` typed or pasted there is an ordinary word, not the start of a comment.
`sessionview install   # checks every requirement; links nothing` hands the
installer `#`, `checks`, `every` and `requirement` as arguments (it refuses
them), and then the `;` runs `links nothing` as a command. In a comment, an
apostrophe opens a quote that swallows the next lines, `(...)` is read as a
glob, and a `|` pipes into the words after it. A comment on its own line is
no better: zsh runs `#` as a command. So the explanation goes in the prose
around the block, never in the block.

Checked: every Markdown file in the checkout except CHANGELOG.md (it records
what was, and is not pasted) and the fragments in changelog.d/ (CHANGELOG
text not collated yet; changelog.d/README.md is checked). Its shell lines are the lines of each indented
code block, and of each fenced block with no info string or a shell one
(bash, sh, zsh, shell, console). A `text` or other fenced block is not
pasted, so it is not checked. A hit is a `#` that stands as its own word: a
`#` inside a word, such as a link's `page.md#anchor` or `#12`, is not one.
"""
import os
import re
import unittest

from tests import _changelog, support

#: Not checked: the changelog keeps the record as it was written.
SKIP_FILES = {"CHANGELOG.md"}

#: Fenced blocks whose info string says shell. An empty one counts: a reader
#: pastes an untagged block too.
SHELL_LANGS = {"", "bash", "sh", "zsh", "shell", "console", "shell-session"}

#: A `#` standing as its own word: the start of a comment in a script, an
#: ordinary argument at a zsh prompt.
COMMENT = re.compile(r"(?:^|\s)#(?:\s|$)")

#: The sweep the ask was measured with: a command word, then text, then a
#: trailing ` # `. Over every line, not only code blocks.
SWEEP = re.compile(r"^\s*[a-z][\w.-]*(\s|=).*\S\s+#\s")

FENCE = re.compile(r"^\s{0,3}(```+|~~~+)\s*([^\s`]*)")


def doc_files():
    """Every .md under the checkout, CHANGELOG.md and its fragments excepted; a
    directory whose name starts with a dot (.git, a virtualenv) is not walked."""
    out = []
    for root, dirs, files in os.walk(support.REPO):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        out += [os.path.join(root, n) for n in sorted(files)
                if n.endswith(".md") and n not in SKIP_FILES
                and not _changelog.is_fragment(os.path.relpath(os.path.join(root, n), support.REPO))]
    return out


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def shell_lines(text):
    """[(line number, line)] for each line a reader would paste into a shell:
    the lines of an indented code block (four spaces or a tab, after a blank
    line), and of a fenced block with no info string or a shell one."""
    out = []
    fence = None            # (marker, is_shell) while inside a fenced block
    indented = False        # inside an indented code block
    blank_before = True
    for n, line in enumerate(text.splitlines(), 1):
        if fence is not None:
            if line.strip().startswith(fence[0]):
                fence = None
            elif fence[1]:
                out.append((n, line))
            continue
        m = FENCE.match(line)
        if m:
            fence = (m.group(1), m.group(2).lower() in SHELL_LANGS)
            indented = False
        elif not line.strip():
            pass            # a blank line neither opens nor closes an indented block
        elif line.startswith(("    ", "\t")) and (blank_before or indented):
            indented = True
            out.append((n, line))
        else:
            indented = False
        blank_before = not line.strip()
    return out


def commented(text):
    """[(line number, line)] for each shell line with a `#` word in it."""
    return [(n, line.strip()) for n, line in shell_lines(text) if COMMENT.search(line)]


def rel(path):
    return os.path.relpath(path, support.REPO)


class DocShellComments(unittest.TestCase):
    maxDiff = None

    def test_finds_the_docs_and_their_shell_lines(self):
        # Not vacuous: the walk sees the docs, and the parser sees their blocks.
        names = {rel(p) for p in doc_files()}
        for name in ("README.md", "AGENTS.md", "SPEC.md", os.path.join("docs", "settings.md"),
                     os.path.join("skills", "sessionview", "SKILL.md")):
            self.assertIn(name, names)
        self.assertNotIn("CHANGELOG.md", names)
        # The fragments are CHANGELOG text, exempt the same way; their README is a doc.
        self.assertIn(os.path.join("changelog.d", "README.md"), names)
        self.assertFalse([n for n in names if _changelog.is_fragment(n)], names)
        readme = [line.strip() for _, line in shell_lines(read(os.path.join(support.REPO, "README.md")))]
        for start in ("uv tool install sessionview", "sessionview install"):
            self.assertTrue(any(line.startswith(start) for line in readme), start)
        self.assertGreater(sum(len(shell_lines(read(p))) for p in doc_files()), 20)

    def test_no_shell_line_carries_a_comment(self):
        hits = ["%s:%d: %s" % (rel(p), n, line) for p in doc_files() for n, line in commented(read(p))]
        self.assertEqual(hits, [], "a shell line in the docs carries a `#` comment; zsh at its "
                                   "prompt reads it as arguments. Move it into the prose.")

    def test_the_sweep_finds_nothing(self):
        hits = ["%s:%d: %s" % (rel(p), n, line.strip())
                for p in doc_files() for n, line in enumerate(read(p).splitlines(), 1)
                if SWEEP.search(line)]
        self.assertEqual(hits, [])


class Canary(unittest.TestCase):
    """The guard bites: each shape the docs once had is a hit, and what is
    not a pasted comment is not."""

    DOC = "\n".join([
        "Intro.",
        "",
        "    make help      # the default goal: lists the targets",   # 3: trailing
        "                   # and a continuation",                     # 4: own line
        "    make test",
        "",
        "```bash",
        "sessionview install   # checks every requirement; links nothing",  # 8
        "# set up first",                                                    # 9
        "echo 'a#b' page.md#anchor",
        "```",
        "",
        "```text",
        "a diagram   # not pasted",
        "```",
        "",
        "```",
        "rm -rf \"$x\"   # the cache",                                       # 18
        "```",
        "",
        "Prose may say # freely; it is not a block.",
        "- a list item",
        "",
    ])

    def test_hits_each_comment_in_a_shell_block(self):
        self.assertEqual([n for n, _ in commented(self.DOC)], [3, 4, 8, 9, 18])

    def test_the_sweep_hits_a_trailing_comment(self):
        self.assertTrue(SWEEP.search("    sessionview install   # checks every requirement"))
        self.assertFalse(SWEEP.search("    sessionview install"))


if __name__ == "__main__":
    unittest.main()
