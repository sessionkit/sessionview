"""The sessionview skill's references: present, pointed at, small, and in step
with the code they describe (SV-104)."""
import json
import os
import re
import unittest

from tests import support

SKILL = os.path.join(support.REPO, "skills", "sessionview")
REFS = ("tabs.md", "tab-config.md", "sidebar.md")
MAX_LINES = 60      # "keep each very small"
MAX_TAB_LINES = 10  # a tab file is "a few lines"


def read(*rel):
    with open(os.path.join(*rel), encoding="utf-8") as f:
        return f.read()


class References(unittest.TestCase):
    def test_each_exists_and_is_small(self):
        for name in REFS:
            with self.subTest(ref=name):
                text = read(SKILL, "references", name)
                self.assertLessEqual(len(text.splitlines()), MAX_LINES)

    def test_skill_points_at_each(self):
        text = read(SKILL, "SKILL.md")
        for name in REFS:
            with self.subTest(ref=name):
                self.assertIn(f"`{name}`", text)

    def test_a_file_per_template_tab(self):
        """One short tab-NAME.md per template tab, each indexed by tabs.md;
        no file for a tab the template does not ship (there is no super tab)."""
        index = read(SKILL, "references", "tabs.md")
        tpl = json.loads(read(support.REPO, "config", "config.json"))
        names = {w["name"] for w in tpl["windows"]}
        for name in names:
            ref = f"tab-{name}.md"
            with self.subTest(tab=name):
                text = read(SKILL, "references", ref)
                self.assertLessEqual(len(text.splitlines()), MAX_TAB_LINES)
                self.assertIn(f"`{name}`", text.splitlines()[0])
                self.assertIn(f"`{ref}`", index)
        files = {f[4:-3] for f in os.listdir(os.path.join(SKILL, "references"))
                 if f.startswith("tab-") and f.endswith(".md") and f != "tab-config.md"}
        self.assertEqual(files, names)

    def test_glyphs_match_the_sidebar(self):
        src = read(support.BIN, "tmux-sidebar")
        table = src[src.index("TAB_CH = {"):]
        table = table[:table.index("}")]
        doc = read(SKILL, "references", "sidebar.md")
        for ch in set(re.findall(r'"(\\u[0-9a-f]{4})"', table)):
            glyph = ch.encode().decode("unicode_escape")
            with self.subTest(glyph=glyph):
                self.assertIn(f"`{glyph}`", doc)

    def test_session_bullet_lists_no_stale_tab(self):
        """The sessionview-session bullet points at tabs.md; every tab it
        names in backticks is a template tab (`code` became `repo`)."""
        text = read(SKILL, "SKILL.md")
        bullet = text[text.index("- `sessionview-session NAME`"):]
        bullet = bullet[:bullet.index("\n- ")]
        self.assertIn("references/tabs.md", bullet)
        tpl = json.loads(read(support.REPO, "config", "config.json"))
        names = {w["name"] for w in tpl["windows"]}
        for word in re.findall(r"`([a-z]+)`", bullet):
            if word != "windows":
                with self.subTest(word=word):
                    self.assertIn(word, names)

    def test_windows_note_names_the_pin_key(self):
        """A pin is refused when a layer sets `window_pins` (set_home_config
        is called with window_pins' source), and the template note says so."""
        src = read(support.BIN, "tmux-sidebar")
        self.assertIn('set_home_config("window_pins", pins, src)', src)
        note = json.loads(read(support.REPO, "config", "config.json"))["_windows"]
        self.assertIn(".sessionview sets `window_pins`", note)
        self.assertNotIn(".sessionview sets `windows`", note)

    def test_show_and_tell_says_show_me(self):
        text = read(SKILL, "SKILL.md")
        part = text[text.index("## Show-and-tell"):]
        part = part[:part.index("\n## ", 1)]
        self.assertIn("show-me", part)
        self.assertNotRegex(part, r"`tmux-show [A-Z]")   # named only to say it cannot run


if __name__ == "__main__":
    unittest.main()
