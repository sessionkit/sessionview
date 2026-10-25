"""The links in the markdown a wheel ships work in the installed tree.

A package user reads the docs where pip put them, under
site-packages/sessionview/_data. A relative link in one of them is relative to
that file, so its target has to ship too, at the same place relative to it:
config/README.md links ../docs/configuration.md#upgrading-from-010, so the wheel
ships docs/configuration.md as sessionview/_data/docs/configuration.md
(pyproject.toml force-include). The checkout's own links are
tests/test_readme_links.py's; this file reads the BUILT wheel, unzipped into a
scratch directory, never the checkout.

Two builds, each into its own scratch directory:
- `uv build`: an sdist, then a wheel built from that sdist, the path a
  default build takes. A file the wheel force-includes has to be in the sdist
  too (pyproject.toml's sdist include), or this build fails;
- `uv build --wheel`: a wheel straight from the checkout.

For EVERY *.md in each wheel, each relative link resolves inside the unzipped
tree, inline [t](target), image and reference definition [id]: target alike:
the file or directory exists relative to the linking file, and a #anchor
matches a heading of the target, by the repository host's slug rule
(test_readme_links.unresolved). No shipped markdown has a full URL to this
repository either. The shipped set is named too: _data/docs/configuration.md
and _data/docs/settings.md. docs/dependencies.md does not ship: it links
../README.md and ../uv.lock, which a wheel has no place for. Needs uv on PATH; without it this is a LOUD skip naming uv.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from tests import support
from tests import test_readme_links as links

UV_SKIP = "SKIPPED: needs uv, which is not on PATH (to build the wheel)"

#: Where the wheel puts the checkout's force-included directories.
DATA = os.path.join("sessionview", "_data")

#: The two builds: a name for the report, and uv's arguments before --out-dir.
BUILDS = (("sdist-then-wheel", ["uv", "build"]),
          ("wheel", ["uv", "build", "--wheel"]))


def build_env():
    """The build tool's own environment (its cache, its index), minus anything
    that could point at a sessionview install."""
    return {k: v for k, v in os.environ.items() if not k.startswith(("SESSIONVIEW_", "VIRTUAL_ENV"))}


def build_and_unzip(argv, base):
    """Run ARGV --out-dir BASE/dist on the checkout, unzip the one wheel into
    BASE/tree and return that path."""
    dist, tree = os.path.join(base, "dist"), os.path.join(base, "tree")
    r = subprocess.run([*argv, "--out-dir", dist, support.REPO], env=build_env(),
                       capture_output=True, text=True, timeout=300, cwd=base)
    if r.returncode != 0:
        raise AssertionError(f"{' '.join(argv)} failed:\n{r.stderr}")
    wheels = [n for n in os.listdir(dist) if n.endswith(".whl")]
    if len(wheels) != 1:
        raise AssertionError(f"{' '.join(argv)}: expected one wheel in {dist}, found {wheels}")
    with zipfile.ZipFile(os.path.join(dist, wheels[0])) as z:
        z.extractall(tree)
    return tree


def markdown(tree):
    """Every *.md under TREE, as paths relative to it, sorted."""
    found = []
    for d, _subdirs, files in os.walk(tree):
        found += [os.path.relpath(os.path.join(d, n), tree) for n in files if n.endswith(".md")]
    return sorted(found)


def dead_links(tree):
    """[(path, line, target)] for each relative link in a *.md under TREE that
    does not resolve inside TREE."""
    return [(rel, n, t) for rel in markdown(tree)
            for n, t in links.unresolved(os.path.join(tree, rel))]


@unittest.skipUnless(shutil.which("uv"), UV_SKIP)
class WheelLinks(unittest.TestCase):
    """Both builds, built once for the class."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="sessionview-wheel-links-")
        cls.trees = {}
        try:
            for name, argv in BUILDS:
                base = os.path.join(cls._tmp.name, name)
                os.mkdir(base)
                cls.trees[name] = build_and_unzip(argv, base)
        except BaseException:
            cls._tmp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_ships_the_config_readme_and_its_link(self):
        # Not vacuous: the file the bug was found in ships, and the link is seen.
        for name, tree in self.trees.items():
            with self.subTest(build=name):
                readme = os.path.join(tree, DATA, "config", "README.md")
                self.assertTrue(os.path.isfile(readme))
                self.assertIn("../docs/configuration.md#upgrading-from-010",
                              [t for _n, t in links.relative(links.read(readme))])

    def test_ships_the_docs_the_config_readme_needs(self):
        # The shipped set by name: config/README.md -> docs/configuration.md ->
        # docs/settings.md, and the anchor the README names is a heading there.
        for name, tree in self.trees.items():
            with self.subTest(build=name):
                docs = os.path.join(tree, DATA, "docs")
                for page in ("configuration.md", "settings.md"):
                    self.assertTrue(os.path.isfile(os.path.join(docs, page)), page)
                self.assertIn("upgrading-from-010",
                              links.anchors(links.read(os.path.join(docs, "configuration.md"))))

    def test_every_relative_link_resolves_in_the_wheel(self):
        for name, tree in self.trees.items():
            with self.subTest(build=name):
                self.assertTrue(markdown(tree))
                hits = dead_links(tree)
                self.assertEqual(hits, [], "a relative link in shipped markdown with no such "
                                 "file or heading in the wheel (ship the target, at the same "
                                 "place relative to the link, via pyproject.toml "
                                 "force-include): "
                                 + ", ".join("%s line %d: %r" % h for h in hits))

    def test_no_full_self_urls_in_the_wheel(self):
        for name, tree in self.trees.items():
            with self.subTest(build=name):
                hits = [(rel, n, u) for rel in markdown(tree)
                        for n, u in links.self_urls(links.read(os.path.join(tree, rel)))]
                self.assertEqual(hits, [], "shipped markdown links into this repository "
                                 "relatively, never by full URL: "
                                 + ", ".join("%s line %d: %s" % h for h in hits))


class DeadLinks(unittest.TestCase):
    """dead_links on a made-up unzipped tree: no build."""

    def test_reads_every_md_and_resolves_inside_the_tree(self):
        files = {os.path.join(DATA, "config", "README.md"):
                     "[u](../docs/configuration.md#upgrading-from-010)\n[k](keys.md)\n",
                 os.path.join(DATA, "config", "keys.md"): "# Keys\n[h](#keys)\n",
                 os.path.join(DATA, "docs", "configuration.md"):
                     "## Upgrading from 0.1.0\n[s](settings.md) [r](../README.md#requirements)\n",
                 os.path.join(DATA, "docs", "settings.md"): "[c](configuration.md#nowhere)\n",
                 os.path.join(DATA, "bin", "tool"): "[x](no-such.md)\n"}
        with tempfile.TemporaryDirectory() as tree:
            for rel, body in files.items():
                os.makedirs(os.path.join(tree, os.path.dirname(rel)), exist_ok=True)
                with open(os.path.join(tree, rel), "w", encoding="utf-8") as f:
                    f.write(body)
            self.assertEqual(len(markdown(tree)), 4)
            self.assertEqual(dead_links(tree),
                             [(os.path.join(DATA, "docs", "configuration.md"), 2, "../README.md#requirements"),
                              (os.path.join(DATA, "docs", "settings.md"), 1, "configuration.md#nowhere")])

    def test_reference_definitions_and_angle_brackets_are_read(self):
        # docs/dependencies.md's form: [id]: target, at the start of a line.
        page = os.path.join(DATA, "docs", "dependencies.md")
        with tempfile.TemporaryDirectory() as tree:
            os.makedirs(os.path.join(tree, DATA, "docs"))
            with open(os.path.join(tree, page), "w", encoding="utf-8") as f:
                f.write("# Deps\n\nSee [req][r] and [lock][l].\n\n"
                        "[r]: ../README.md#requirements\n[l]: <../uv.lock>\n"
                        "[s]: #deps\n[t](<#nowhere>)\n")
            self.assertEqual(dead_links(tree), [(page, 5, "../README.md#requirements"),
                                                (page, 6, "../uv.lock"), (page, 8, "#nowhere")])

    def test_a_missing_target_is_dead(self):
        with tempfile.TemporaryDirectory() as tree:
            os.makedirs(os.path.join(tree, DATA, "config"))
            with open(os.path.join(tree, DATA, "config", "README.md"), "w", encoding="utf-8") as f:
                f.write("[Upgrading from\n0.1.0](../docs/configuration.md#upgrading-from-010)\n")
            self.assertEqual(dead_links(tree), [(os.path.join(DATA, "config", "README.md"), 2,
                                                 "../docs/configuration.md#upgrading-from-010")])


if __name__ == "__main__":
    unittest.main()
