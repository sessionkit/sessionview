"""`make pypi-dist`: the dists a release uploads carry absolute README links.

The package index page shows README.md as the package's long description, and
it cannot follow a relative link. The checkout's README keeps its relative
links (tests/test_readme_links.py), so `make pypi-dist` builds from the release
tag in a scratch stage, pins the STAGED README's links to the tag with
sessionkit's scripts/pypi_readme.py (one copy for the kit, never one here),
builds there, and checks the wheel and the sdist. `make publish` uploads what
it built, never a plain `make build`.

Everything here is offline. The fixture is this checkout's tracked files (as
they are on disk) committed to a scratch repository and tagged v<version>; the
"public" remote is a local bare repository that carries the tag, or one that
does not. The long description is read out of each built dist (the wheel's
METADATA, the sdist's PKG-INFO), and any relative link in it fails the test.

Needs make, git and uv on PATH, and sessionkit's scripts/pypi_readme.py: set
SESSIONKIT to a sessionkit clone that has it (default: a clone beside this
one). Without one the end-to-end class is a LOUD skip naming SESSIONKIT; the
refusals that need no script still run.
"""
import io
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import unittest
import zipfile
from email.parser import Parser

from tests import support
from tests import test_readme_links as links

#: The make variable (and environment variable) naming a sessionkit clone.
KIT_VAR = "SESSIONKIT"
KIT_DIR = os.environ.get(KIT_VAR) or os.path.join(os.path.dirname(support.REPO), "sessionkit")
SCRIPT = os.path.join(KIT_DIR, "scripts", "pypi_readme.py")
KIT_SKIP = ("SKIPPED: needs sessionkit's scripts/pypi_readme.py, not found at %s; "
            "set %s to a sessionkit clone that has it" % (SCRIPT, KIT_VAR))
TOOLS_SKIP = "SKIPPED: needs make, git and uv on PATH (to build the dists)"

#: The public repository the links point at, as OWNER/NAME on the host. Built
#: from parts, so this file holds no full URL to this repository.
REPO_PATH = "sessionkit/" + "sessionview"
#: A link pinned into this repository, as the kit's rewrite writes it: a file
#: or a directory on github.com (blob/tree), or an image on
#: raw.githubusercontent.com. Group "ref" is the ref it is pinned to.
PINNED = re.compile(r"https://(?:github\.com/" + re.escape(REPO_PATH) + r"/(?:blob|tree)"
                    r"|raw\.githubusercontent\.com/" + re.escape(REPO_PATH) + r")"
                    r"/(?P<ref>[^/\s)]+)/")

#: An image the end-to-end fixture adds to its README, once inline and once as
#: a reference definition, so the image pins are tested whatever the checkout's
#: README holds. Written into the scratch fixture only, never into this checkout.
FIXTURE_IMAGE = "pypi-dist-fixture/shot.png"
FIXTURE_README = ("\n![A fixture image](%s)\n\n[fixture-shot]: %s\n"
                  % (FIXTURE_IMAGE, FIXTURE_IMAGE))
#: A 1x1 PNG: the bytes FIXTURE_IMAGE holds.
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000b49444154789c6360000200000500017a5eab3f0000000049454e44ae426082")

#: Any URL scheme, protocol-relative URL or in-page anchor: not relative to a
#: file. The package index renders an in-page #anchor, so it stays as it is.
NOT_RELATIVE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*:|//|#)")


def version():
    with open(os.path.join(support.REPO, "pyproject.toml"), "rb") as f:
        return tomllib.load(f)["project"]["version"]


def have_tools():
    return all(shutil.which(t) for t in ("make", "git", "uv"))


def env():
    """The caller's environment for git, make and uv (uv keeps its own cache
    and index), minus anything that could steer them: a sessionview install, an
    outer make's flags and variables, and the user's git config."""
    drop = ("SESSIONVIEW_", "VIRTUAL_ENV", "MAKE", "MFLAGS", "GIT_", KIT_VAR, "PYPI_README",
            "PUBLIC_REMOTE")
    e = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
    e.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
             GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.invalid",
             GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.invalid")
    return e


def git(*args, cwd):
    r = subprocess.run(["git", *args], cwd=cwd, env=env(), capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise AssertionError("git %s failed:\n%s" % (" ".join(args), r.stderr))
    return r.stdout


def make(cwd, *args):
    return subprocess.run(["make", "-C", cwd, *args], env=env(), capture_output=True,
                          text=True, timeout=600)


def description(dist):
    """The long description in a wheel's METADATA or an sdist's PKG-INFO."""
    if dist.endswith(".whl"):
        with zipfile.ZipFile(dist) as z:
            names = [n for n in z.namelist() if n.count("/") == 1 and n.endswith(".dist-info/METADATA")]
            raw = z.read(names[0]).decode("utf-8")
    else:
        with tarfile.open(dist) as t:
            members = [m for m in t.getmembers() if m.name.count("/") == 1 and m.name.endswith("/PKG-INFO")]
            raw = t.extractfile(members[0]).read().decode("utf-8")
    msg = Parser().parsestr(raw)
    return msg.get_payload() or msg.get("Description", "")


def relative_links(text):
    """Each link target in TEXT that is relative to a file: what 404s on the
    package index page."""
    return [t for _n, t in links.targets(text) if not NOT_RELATIVE.match(t)]


def fixture_repo(dest, image=False):
    """This checkout's tracked files, as they are on disk, committed to a new
    repository at DEST and tagged v<version>. With IMAGE, the fixture also holds
    FIXTURE_IMAGE and its README links it (FIXTURE_README)."""
    tracked = subprocess.run(["git", "-C", support.REPO, "ls-files", "-z"], env=env(),
                             capture_output=True, check=True).stdout.decode().split("\0")
    for rel in filter(None, tracked):
        src = os.path.join(support.REPO, rel)
        if not os.path.lexists(src):
            continue  # deleted in the working tree, not yet committed
        os.makedirs(os.path.join(dest, os.path.dirname(rel)), exist_ok=True)
        shutil.copy2(src, os.path.join(dest, rel), follow_symlinks=False)
    if image:
        os.makedirs(os.path.join(dest, os.path.dirname(FIXTURE_IMAGE)), exist_ok=True)
        with open(os.path.join(dest, FIXTURE_IMAGE), "wb") as f:
            f.write(PNG_1X1)
        with open(os.path.join(dest, "README.md"), "a", encoding="utf-8") as f:
            f.write(FIXTURE_README)
    git("init", "-q", cwd=dest)
    git("add", "-A", cwd=dest)
    git("commit", "-q", "-m", "fixture", cwd=dest)
    git("tag", "v" + version(), cwd=dest)


def bare_repo(path, source=None, ref=None):
    """A local bare repository at PATH: the 'public' remote. With SOURCE and
    REF, REF is pushed to it from SOURCE."""
    git("init", "-q", "--bare", path, cwd=os.path.dirname(path))
    if source:
        git("push", "-q", path, ref, cwd=source)
    return path


def dists(folder):
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


class Description(unittest.TestCase):
    """The reader and the relative-link finder on made-up dists: no build."""

    def wheel(self, folder, body):
        path = os.path.join(folder, "sessionview-1.2.3-py3-none-any.whl")
        meta = "Metadata-Version: 2.4\nName: sessionview\nVersion: 1.2.3\n\n" + body
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("sessionview-1.2.3.dist-info/METADATA", meta)
        return path

    def sdist(self, folder, body):
        path = os.path.join(folder, "sessionview-1.2.3.tar.gz")
        data = ("Metadata-Version: 2.4\nName: sessionview\nVersion: 1.2.3\n\n" + body).encode()
        with tarfile.open(path, "w:gz") as t:
            info = tarfile.TarInfo("sessionview-1.2.3/PKG-INFO")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        return path

    def test_a_relative_link_in_either_dist_is_found(self):
        body = ("# sessionview\n\n[Install](#install), [spec](SPEC.md), "
                "[home](https://example.org/x), ![shot](docs/shot.png)\n\n[d]: docs/dependencies.md\n")
        with tempfile.TemporaryDirectory() as tmp:
            for dist in (self.wheel(tmp, body), self.sdist(tmp, body)):
                with self.subTest(dist=os.path.basename(dist)):
                    self.assertEqual(sorted(relative_links(description(dist))),
                                     ["SPEC.md", "docs/dependencies.md", "docs/shot.png"])

    def test_pinned_finds_file_directory_and_image_pins(self):
        tag = "v1.2.3"
        body = ("[spec](https://github.com/{r}/blob/{t}/SPEC.md) "
                "[docs](https://github.com/{r}/tree/{t}/docs) "
                "![shot](https://raw.githubusercontent.com/{r}/{t}/docs/images/shot.png)\n"
                "[d]: https://raw.githubusercontent.com/{r}/{t}/docs/shot.png\n").format(r=REPO_PATH, t=tag)
        self.assertEqual([m.group("ref") for m in PINNED.finditer(body)], [tag] * 4)

    def test_pinned_ignores_links_that_are_not_pins_into_this_repository(self):
        body = ("[a](https://github.com/{r}) [b](https://github.com/{r}/raw/v1/x.png) "
                "![c](https://raw.githubusercontent.com/other/{n}/v1/x.png) "
                "![d](https://raw.githubusercontent.com/{r}-x/v1/x.png) "
                "[e](https://example.org/{r}/blob/v1/x)\n").format(r=REPO_PATH, n=REPO_PATH.split("/")[1])
        self.assertEqual(list(PINNED.finditer(body)), [])

    def test_absolute_links_and_anchors_are_not_relative(self):
        pinned = "https://github.com/" + REPO_PATH + "/blob/v1.2.3/SPEC.md"
        body = "[spec](%s) [i](#install) [m](mailto:x@example.invalid)\n" % pinned
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(relative_links(description(self.wheel(tmp, body))), [])


class PublishWiring(unittest.TestCase):
    """The Makefile, read as text: never run."""

    def setUp(self):
        with open(os.path.join(support.REPO, "Makefile"), encoding="utf-8") as f:
            self.text = f.read()

    def test_publish_uploads_what_pypi_dist_built(self):
        m = re.search(r"^publish:([^#\n]*)", self.text, re.MULTILINE)
        self.assertIsNotNone(m, "Makefile has no publish target")
        self.assertEqual(m.group(1).split(), ["pypi-dist"])

    def test_build_stays_a_plain_local_build(self):
        m = re.search(r"^build:[^\n]*\n\t(.+)$", self.text, re.MULTILINE)
        self.assertEqual(m.group(1).strip(), "@uv build")

    def test_the_kit_script_is_never_copied_here(self):
        found = [os.path.join(d, n) for d, _s, files in os.walk(support.REPO)
                 if ".git" not in d.split(os.sep) for n in files if n == "pypi_readme.py"]
        self.assertEqual(found, [], "pypi_readme.py is sessionkit's one copy; point SESSIONKIT at it")
        self.assertRegex(self.text, r"(?m)^PYPI_README \?= python3 \$\(SESSIONKIT\)/scripts/pypi_readme\.py$")

    def test_make_help_lists_pypi_dist(self):
        help_lines = re.search(r"^help:.*\n((?:\t.*\n)+)", self.text, re.MULTILINE).group(1)
        self.assertRegex(help_lines, r"\bpypi-dist\b")


@unittest.skipUnless(have_tools(), TOOLS_SKIP)
class Refusals(unittest.TestCase):
    """pypi-dist builds nothing when it cannot pin the links to a public tag."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="sessionview-pypi-dist-")
        try:
            cls.src = os.path.join(cls._tmp.name, "src")
            os.mkdir(cls.src)
            fixture_repo(cls.src)
            cls.empty = bare_repo(os.path.join(cls._tmp.name, "empty.git"))
        except BaseException:
            cls._tmp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def assertRefused(self, r, *words, src=None):
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        for w in words:
            self.assertIn(w, r.stderr)
        self.assertIn("nothing built", r.stderr)
        self.assertEqual(dists(os.path.join(src or self.src, "dist")), [])

    def test_refuses_without_the_kit_script(self):
        r = make(self.src, "pypi-dist", "PUBLIC_REMOTE=" + self.empty,
                 "SESSIONKIT=" + os.path.join(self._tmp.name, "no-kit"))
        self.assertRefused(r, "set SESSIONKIT", "pypi_readme.py")

    @unittest.skipUnless(os.path.isfile(SCRIPT), KIT_SKIP)
    def test_refuses_when_the_tag_is_not_on_the_public_remote(self):
        r = make(self.src, "pypi-dist", "PUBLIC_REMOTE=" + self.empty, "SESSIONKIT=" + KIT_DIR)
        self.assertRefused(r, "v%s is not on %s" % (version(), self.empty))

    @unittest.skipUnless(os.path.isfile(SCRIPT), KIT_SKIP)
    def test_refuses_when_the_local_tag_was_moved_off_the_public_one(self):
        # The public repo tags commit A; a clone of the fixture then moves its
        # local tag to a new commit B. Both are on disk, so the links would
        # resolve, but to A's tree while the dists are built from B's.
        tag = "v" + version()
        public = bare_repo(os.path.join(self._tmp.name, "moved-public.git"),
                           self.src, "refs/tags/" + tag)
        moved = os.path.join(self._tmp.name, "moved")
        git("clone", "-q", "--no-hardlinks", self.src, moved, cwd=self._tmp.name)
        commit_a = git("rev-parse", tag + "^{commit}", cwd=moved).strip()
        git("commit", "-q", "--allow-empty", "-m", "after the tag", cwd=moved)
        git("tag", "-f", tag, cwd=moved)
        commit_b = git("rev-parse", tag + "^{commit}", cwd=moved).strip()
        self.assertNotEqual(commit_a, commit_b)
        r = make(moved, "pypi-dist", "PUBLIC_REMOTE=" + public, "SESSIONKIT=" + KIT_DIR)
        self.assertRefused(r, "%s differs" % tag, commit_a, commit_b, public, src=moved)


@unittest.skipUnless(have_tools(), TOOLS_SKIP)
@unittest.skipUnless(os.path.isfile(SCRIPT), KIT_SKIP)
class PypiDist(unittest.TestCase):
    """`make pypi-dist` against a local public remote that carries the tag, and
    a plain build of the same tree beside it. Built once for the class."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="sessionview-pypi-dist-")
        try:
            base = cls._tmp.name
            cls.tag = "v" + version()
            cls.src = os.path.join(base, "src")
            os.mkdir(cls.src)
            fixture_repo(cls.src, image=True)
            public = bare_repo(os.path.join(base, "public.git"), cls.src, "refs/tags/" + cls.tag)
            cls.made = make(cls.src, "pypi-dist", "PUBLIC_REMOTE=" + public, "SESSIONKIT=" + KIT_DIR)
            cls.dist = os.path.join(cls.src, "dist")
            cls.plain = os.path.join(base, "plain")
            r = subprocess.run(["uv", "build", "--out-dir", cls.plain, cls.src], env=env(),
                               capture_output=True, text=True, timeout=600, cwd=base)
            if r.returncode != 0:
                raise AssertionError("plain uv build failed:\n" + r.stderr)
        except BaseException:
            cls._tmp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def built(self, folder):
        stem = "sessionview-" + version()
        return [os.path.join(folder, stem + "-py3-none-any.whl"), os.path.join(folder, stem + ".tar.gz")]

    def test_builds_the_wheel_and_the_sdist_and_checks_both(self):
        self.assertEqual(self.made.returncode, 0, self.made.stdout + self.made.stderr)
        for path in self.built(self.dist):
            self.assertTrue(os.path.isfile(path), path)
            self.assertIn("%s: 0 relative link(s)" % os.path.basename(path), self.made.stdout)

    def test_every_readme_link_is_absolute_and_pinned_to_the_tag(self):
        # The fixture's README: the checkout's, plus FIXTURE_README.
        with open(os.path.join(self.src, "README.md"), encoding="utf-8") as f:
            wanted = len(relative_links(f.read()))
        self.assertGreater(wanted, 0, "the README has no relative link: this test proves nothing")
        for path in self.built(self.dist):
            with self.subTest(dist=os.path.basename(path)):
                text = description(path)
                self.assertEqual(relative_links(text), [], "a relative link on the package index page")
                refs = [m.group("ref") for m in PINNED.finditer(text)]
                self.assertEqual(len(refs), wanted, "each relative README link becomes one pinned link")
                self.assertEqual(set(refs), {self.tag})

    def test_a_readme_image_is_pinned_to_the_tag_on_raw_githubusercontent(self):
        # Covers images on their own: FIXTURE_README links one inline and once
        # by a reference definition, whatever the checkout's README holds.
        raw = "https://raw.githubusercontent.com/%s/%s/%s" % (REPO_PATH, self.tag, FIXTURE_IMAGE)
        for path in self.built(self.dist):
            with self.subTest(dist=os.path.basename(path)):
                text = description(path)
                self.assertIn("![A fixture image](%s)" % raw, text)
                self.assertIn("[fixture-shot]: %s" % raw, text)

    def test_the_checkout_readme_keeps_its_relative_links(self):
        self.assertEqual(git("status", "--porcelain", "--untracked-files=no", cwd=self.src), "")

    def test_a_plain_build_fails_the_check(self):
        # Not vacuous: without the rewrite, both dists carry the README's
        # relative links, and the kit's check fails them.
        for path in self.built(self.plain):
            with self.subTest(dist=os.path.basename(path)):
                self.assertNotEqual(relative_links(description(path)), [])
        r = subprocess.run(["python3", SCRIPT, "check", *self.built(self.plain)], env=env(),
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
