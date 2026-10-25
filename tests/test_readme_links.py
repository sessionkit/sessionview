"""Guard: the links in README.md and docs/*.md work where the docs are read.

The docs are read in a terminal editor, offline, or on the repository host. A
link from one of them to a file in this repository is relative to the linking
file, so it opens that file in the editor and needs no network. A full URL to
this repository (github.com/sessionkit/sessionview/blob|tree|raw/...) opens a
browser instead, so it is a hit. The package index page, which cannot follow
a relative link, is handled when a release is published, not here.

Checked: inline links [text](target), images ![alt](target) and reference
definitions [id]: target, in README.md and each docs/*.md.

- A relative target resolves: the file or directory exists relative to the
  linking file, and a #anchor matches a heading of the target, by the
  repository host's slug rule. An in-page #anchor matches a heading of the
  linking file.
- A link to another kit repository stays a full URL, and names HEAD, which
  the host resolves to the repository's default branch, or a v* release tag:
  /blob/HEAD/<path> for a file, /tree/HEAD/<path> for a directory. It never
  names a branch. Its text names the package and the path, for a reader
  offline. A repository's root URL (no blob, tree or raw) is fine.
- In README.md, a github.com URL for one of the kit's repositories under the
  old owner is a hit, since the kit's repositories now live under the
  sessionkit owner (the pyproject Homepage). A repository outside the kit
  keeps its own URL.

BranchGate reads every tracked file (tests included) for the same rules: no
kit URL that names a branch (a raw.githubusercontent.com URL included), no full
URL to this repository, and no instruction that names the host's usual default
branch, which the kit's repositories do not have (master is their only branch):
cloning it (-b, --branch), checking it out or switching to it (git checkout,
git switch), pushing to it (git push <remote> <it>, or <ref>:<it>) or naming
origin/<it>. Another branch name in an instruction is not a hit. Its patterns
are built from parts, so this file does not trip it.
"""
import os
import re
import subprocess
import tempfile
import unittest

from tests import support

README = os.path.join(support.REPO, "README.md")
DOCS = os.path.join(support.REPO, "docs")

#: The target of an inline link or image: whatever follows `](`, up to the
#: first space or `)`. Matching on `](` alone also catches a link nested in
#: another link's text, such as an image inside a link.
INLINE = re.compile(r"\]\(\s*<?([^)\s>]*)")

#: A reference definition: `[id]: target` at the start of a line.
REFDEF = re.compile(r"^ {0,3}\[[^\]]+\]:[ \t]*<?([^\s>]*)", re.M)

#: Targets that are not a path in this repository: a URL and mailto:.
#: An in-page anchor (#section) is relative, and is checked like the rest.
ABSOLUTE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*://|mailto:)")

#: The kit's repositories.
KIT = ("sessionview", "sessionmail", "sessiontools", "sessionvoice",
       "sessionkit", "sessionphone")

#: The only branch the kit's repositories have.
BRANCH = "master"
#: The ref a kit URL names: the host's name for the default branch.
REF = "HEAD"
#: Or a release tag.
TAG = re.compile(r"v[0-9][A-Za-z0-9._-]*")
#: The host's usual default branch, which the kit's repositories do not have.
#: Kept in a variable so the patterns below do not spell a hit themselves.
OTHER = "ma" + "in"

#: The kit's owner on the repository host, in a URL.
HOST = r"github\.com/sessionkit/"
#: The kit's owner on the host's raw-file server: /<repo>/<ref>/<path>.
RAW_HOST = r"raw\.githubusercontent\.com/sessionkit/"
#: The end of a branch name: no name character follows, nor a dot that
#: carries the name on (origin/X..HEAD and "on X." end it; X.old does not).
END = r"(?![A-Za-z0-9_-]|\.[A-Za-z0-9_])"

#: A full URL to a file or directory of this repository.
SELF_URL = re.compile(HOST + r"sessionview/(blob|tree|raw)/|" + RAW_HOST + r"sessionview/")

#: A URL to a file or directory of a sessionkit repository: group 1 is the
#: repository, group 2 the ref (up to the next /, space, quote or bracket).
KIT_URL = re.compile(HOST + r"([A-Za-z0-9_.-]+)/(?:blob|tree|raw)/([^/\s)>\]\"'#?]*)")
#: The same on the raw-file server, where the ref follows the repository.
RAW_URL = re.compile(RAW_HOST + r"([A-Za-z0-9_.-]+)/([^/\s)>\]\"'#?]*)")

#: The start of a word: no name character before it.
WORD = r"(?<![A-Za-z0-9_-])"
#: Flags between a git verb and its arguments: -c, --track, -u.
FLAGS = r"(?:[ \t]+-\S+)*"
#: A branch instruction naming the other branch: -b X, --branch X or
#: --branch=X; git checkout X and git switch X (flags allowed between); git
#: push <remote> X and git push <remote> <ref>:X; and origin/X.
OTHER_BRANCH = re.compile(WORD + r"(-b|--branch)(=|[ \t]+)" + OTHER + END
                          + "|" + WORD + r"git[ \t]+(checkout|switch)" + FLAGS + r"[ \t]+" + OTHER + END
                          + "|" + WORD + r"git[ \t]+push" + FLAGS + r"[ \t]+[^\s-]\S*[ \t]+(\S*:)?"
                          + OTHER + END
                          + "|" + WORD + r"origin/" + OTHER + END)

#: A kit repository under the old owner; another repository there is fine.
OLD_OWNER_KIT = re.compile(r"github\.com/mbailey/(%s)(?![A-Za-z0-9_-])" % "|".join(KIT))

#: An ATX heading: up to three spaces, one to six #, then the text.
HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
#: A fence opening or closing a code block.
FENCE = re.compile(r"^ {0,3}(```|~~~)")


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def targets(text):
    """[(line, target)] for every inline link, image and reference definition."""
    out = []
    for pat in (INLINE, REFDEF):
        for m in pat.finditer(text):
            out.append((line_of(text, m.start(1)), m.group(1)))
    return sorted(out)


def relative(text):
    """The targets in TEXT that are a path in this repository (or an in-page anchor)."""
    return [(n, t) for n, t in targets(text) if not ABSOLUTE.match(t)]


def self_urls(text):
    """[(line, url)] for each full URL to this repository."""
    return [(line_of(text, m.start()), m.group(0)) for m in SELF_URL.finditer(text)]


def allowed_ref(ref):
    """True for the refs a kit URL may name: HEAD and a v* release tag."""
    return ref == REF or bool(TAG.fullmatch(ref))


def kit_branches(text):
    """[(line, url)] for each kit URL (github.com or raw.githubusercontent.com)
    that names a ref other than HEAD or a v* tag: a branch, master included, or
    a commit."""
    return sorted((line_of(text, m.start()), m.group(0))
                  for rx in (KIT_URL, RAW_URL) for m in rx.finditer(text)
                  if not allowed_ref(m.group(2)))


def old_owner(text):
    """[(line, url)] for each kit repository named under the old owner."""
    return [(line_of(text, m.start()), m.group(0))
            for m in OLD_OWNER_KIT.finditer(text)]


def slug(heading):
    """The anchor the repository host gives a heading: its text in lower case,
    with each character that is not a letter, digit, space, hyphen or
    underscore dropped, and each space made a hyphen."""
    text = re.sub(r"!?\[([^\]]*)\](\([^)]*\)|\[[^\]]*\])?", r"\1", heading)
    text = text.replace("`", "").replace("*", "")
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def anchors(text):
    """The anchors of TEXT's headings, outside code blocks; a repeated heading
    gets -1, -2 and so on, as on the repository host."""
    out, seen, fenced = set(), {}, False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        m = None if fenced else HEADING.match(line)
        if m:
            s = slug(m.group(1))
            n = seen.get(s, 0)
            seen[s] = n + 1
            out.add(s if n == 0 else "%s-%d" % (s, n))
    return out


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def unresolved(path, text=None):
    """[(line, target)] for each relative target in the file PATH that does
    not resolve: no such file or directory, or no such heading."""
    text = read(path) if text is None else text
    out = []
    for n, t in relative(text):
        file_part, _, anchor = t.partition("#")
        if not file_part:
            if not anchor or anchor not in anchors(text):
                out.append((n, t))      # an empty target, or no such heading on this page
            continue
        dest = os.path.normpath(os.path.join(os.path.dirname(path), file_part))
        if not os.path.exists(dest):
            out.append((n, t))
        elif anchor and (not os.path.isfile(dest) or anchor not in anchors(read(dest))):
            out.append((n, t))
    return out


def doc_files():
    """README.md and each docs/*.md."""
    return [README] + sorted(os.path.join(DOCS, n) for n in os.listdir(DOCS) if n.endswith(".md"))


def rel(path):
    return os.path.relpath(path, support.REPO)


def report(by_file):
    return ", ".join("%s line %d: %r" % (p, n, t) for p, hits in by_file for n, t in hits)


def over_docs(check):
    """[(path, hits)] for each doc file where CHECK(text) finds hits; the path
    is relative to the checkout."""
    return [(rel(p), hits) for p in doc_files() for hits in [check(read(p))] if hits]


class DocLinks(unittest.TestCase):
    def test_finds_links(self):
        # Not vacuous: the README and the docs have links, and the parser sees them.
        for path in doc_files():
            with self.subTest(path=rel(path)):
                self.assertTrue(targets(read(path)))
        self.assertTrue(relative(read(README)))

    def test_no_full_self_urls(self):
        hits = over_docs(self_urls)
        self.assertEqual(hits, [], "a link to a file in this repository is relative to the "
                         "linking file (docs/settings.md, or ../config/keys.md from docs/), "
                         "never a full URL: " + report(hits))

    def test_relative_links_resolve(self):
        hits = [(rel(p), u) for p in doc_files() for u in [unresolved(p)] if u]
        self.assertEqual(hits, [], "relative link with no such file, or no such heading: "
                         + report(hits))

    def test_kit_links_name_head_or_tag(self):
        hits = over_docs(kit_branches)
        self.assertEqual(hits, [], "a link to another kit repository names HEAD or a v* "
                         "tag, never a branch (/blob/HEAD/<path>, /tree/HEAD/<path>): "
                         + report(hits))

    def test_kit_repos_under_sessionkit(self):
        hits = old_owner(read(README))
        self.assertEqual(hits, [], "a kit repository lives under github.com/sessionkit: "
                         + ", ".join(f"line {n}: {u}" for n, u in hits))


class Patterns(unittest.TestCase):
    """The parser and the checks, on text made up for the purpose."""

    def test_inline_relative(self):
        self.assertEqual(relative("Read [the spec](SPEC.md) first."), [(1, "SPEC.md")])
        self.assertEqual(relative("see [docs](docs/)"), [(1, "docs/")])
        self.assertEqual(relative("see [up](../x.md#a)"), [(1, "../x.md#a")])
        self.assertEqual(relative("an [empty]() link"), [(1, "")])
        self.assertEqual(relative('[t](SPEC.md "title")'), [(1, "SPEC.md")])
        self.assertEqual(relative("[t](<SPEC.md>)"), [(1, "SPEC.md")])
        self.assertEqual(relative("[Install](#install)"), [(1, "#install")])

    def test_image_relative(self):
        self.assertEqual(relative("![shot](docs/shot.png)"), [(1, "docs/shot.png")])
        # An image inside a link: both targets are seen.
        self.assertEqual(relative("[![b](b.svg)](https://example.org/)"), [(1, "b.svg")])

    def test_reference_definition_relative(self):
        text = "Read [the spec][s].\n\n[s]: SPEC.md\n  [t]: <docs/x.md> \"title\"\n"
        self.assertEqual(relative(text), [(3, "SPEC.md"), (4, "docs/x.md")])

    def test_absolute_not_relative(self):
        text = ("[s](SPEC.md) [k](https://github.com/sessionkit/sessionkit/blob/HEAD/docs/settings.md)\n"
                "![i](https://example.org/i.png) [m](mailto:someone@example.org)\n"
                "[d](docs/configuration.md#mail-sender)\n"
                "[r]: https://example.org/ref\n")
        self.assertEqual(len(targets(text)), 6)
        self.assertEqual(relative(text), [(1, "SPEC.md"), (3, "docs/configuration.md#mail-sender")])

    def test_line_numbers(self):
        self.assertEqual(relative("one\ntwo\n[x](y.md)\n"), [(3, "y.md")])

    def test_self_urls(self):
        url = "https://" + HOST.replace("\\", "") + "sessionview/"
        for kind in ("blob", "tree", "raw"):
            for branch in (BRANCH, OTHER):
                with self.subTest(kind=kind, branch=branch):
                    self.assertEqual(self_urls("x\n[s](%s%s/%s/SPEC.md)" % (url, kind, branch)),
                                     [(2, url[len("https://"):] + kind + "/")])
        # The repository's home page, and another kit repository, are not self links.
        self.assertEqual(self_urls(url.rstrip("/")), [])
        self.assertEqual(self_urls(url + "issues"), [])
        self.assertEqual(self_urls(url.replace("sessionview", "sessionmail") + "blob/master/x"), [])

    def test_kit_branches(self):
        host = HOST.replace("\\", "")
        for repo in KIT:
            for kind in ("blob", "tree", "raw"):
                with self.subTest(repo=repo, kind=kind):
                    for ref in (REF, "v0.2.0", "v1"):
                        self.assertEqual(kit_branches("%s%s/%s/%s/docs" % (host, repo, kind, ref)), [])
                    for ref in (BRANCH, OTHER, "develop", "0123abc", "head", "HEADS", "version", ""):
                        self.assertEqual(len(kit_branches("[d](https://%s%s/%s/%s/docs)" % (host, repo, kind, ref))),
                                         1, ref)
        # The bare repository URL, and a page that is not a file or directory, name no ref.
        self.assertEqual(kit_branches("https://%ssessionkit" % host), [])
        self.assertEqual(kit_branches("https://%ssessionkit/issues" % host), [])
        # The ref ends at a quote, a bracket, a space or an anchor.
        self.assertEqual(kit_branches("<%ssessionkit/blob/HEAD>" % host), [])
        self.assertEqual(kit_branches("[x](%ssessionkit/tree/HEAD) " % host), [])
        self.assertEqual(kit_branches('"%ssessionkit/tree/%s"' % (host, BRANCH)),
                         [(1, "%ssessionkit/tree/%s" % (host, BRANCH))])

    def test_slug(self):
        self.assertEqual(slug("Upgrading from 0.1.0"), "upgrading-from-010")
        self.assertEqual(slug("Mail sender"), "mail-sender")
        self.assertEqual(slug("[Settings][settings]"), "settings")
        self.assertEqual(slug("The kit's settings"), "the-kits-settings")
        self.assertEqual(slug("Dock app (macOS, optional)"), "dock-app-macos-optional")
        self.assertEqual(slug("`sessionview config`"), "sessionview-config")
        self.assertEqual(slug("snake_case and-dash"), "snake_case-and-dash")

    def test_anchors(self):
        text = ("# Title\n\n## Mail sender\n\n```sh\n# not a heading\n```\n"
                "## Notes\n## Notes ##\n    # indented code\n#nospace\n")
        self.assertEqual(anchors(text), {"title", "mail-sender", "notes", "notes-1"})

    def test_unresolved(self):
        # Made-up docs in the checkout's layout: the paths are read, not written.
        page = os.path.join(DOCS, "planted.md")
        good = ("[c](configuration.md) [u](configuration.md#upgrading-from-010)\n"
                "[k]: ../config/keys.md\n[d](../docs/) [h](#here)\n\n## Here\n")
        self.assertEqual(unresolved(page, good), [])
        bad = ("[a](configuration.md#no-such-heading)\n[b](no-such-file.md)\n"
               "[c](config/keys.md)\n[d](#nowhere)\n[e]()\n[f](../config/#x)\n")
        self.assertEqual(unresolved(page, bad), [(1, "configuration.md#no-such-heading"),
                                                 (2, "no-such-file.md"), (3, "config/keys.md"),
                                                 (4, "#nowhere"), (5, ""), (6, "../config/#x")])

    def test_old_owner_kit(self):
        for repo in KIT:
            with self.subTest(repo=repo):
                self.assertTrue(old_owner(f"git clone https://github.com/mbailey/{repo} dir"))
                self.assertFalse(old_owner(f"https://github.com/sessionkit/{repo}"))
        self.assertTrue(old_owner("https://github.com/mbailey/sessionview.git"))
        self.assertTrue(old_owner("at github.com/mbailey/sessionmail."))
        # A repository outside the kit, or a longer name, is not a hit.
        self.assertFalse(old_owner("show-me (github.com/mbailey/show-me)"))
        self.assertFalse(old_owner("github.com/mbailey/sessionview-extra"))
        self.assertFalse(old_owner("github.com/mbailey/session"))


def gate_hits(text):
    """[(line, what)] for each line of TEXT the branch gate refuses."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if kit_branches(line):
            out.append((n, "kit URL naming a branch"))
        for what, rx in (("full URL to this repository", SELF_URL),
                         ("branch instruction naming the other branch", OTHER_BRANCH)):
            if rx.search(line):
                out.append((n, what))
    return out


def tracked_files():
    """Every file git tracks in the checkout; outside a git checkout (an
    unpacked release archive), every file under it but dot-directories and
    __pycache__."""
    try:
        top = subprocess.check_output(["git", "-C", support.REPO, "rev-parse", "--show-toplevel"],
                                      stderr=subprocess.DEVNULL, text=True).strip()
        if os.path.realpath(top) == os.path.realpath(support.REPO):
            out = subprocess.check_output(["git", "-C", support.REPO, "ls-files", "-z"],
                                          stderr=subprocess.DEVNULL)
            return sorted(p for p in out.decode().split("\0") if p)
    except (OSError, subprocess.CalledProcessError):
        pass
    found = []
    for d, subdirs, files in os.walk(support.REPO):
        subdirs[:] = [n for n in subdirs if not n.startswith(".") and n != "__pycache__"]
        found += [os.path.relpath(os.path.join(d, n), support.REPO) for n in files]
    return sorted(found)


def scan(paths):
    """{path: [(line, what)]} over the text files among PATHS (relative to the checkout)."""
    found = {}
    for rel in paths:
        path = os.path.join(support.REPO, rel)
        if not os.path.isfile(path):
            continue        # tracked but deleted in the work tree
        with open(path, "rb") as f:
            raw = f.read()
        if b"\0" in raw[:8192]:
            continue        # a binary (the Dock icon): its bytes are noise
        hits = gate_hits(raw.decode("utf8", "replace"))
        if hits:
            found[rel] = hits
    return found


class BranchGate(unittest.TestCase):
    """The whole tracked tree, tests included, names master and links relative."""

    def test_pattern(self):
        host = "https://" + HOST.replace("\\", "")
        raw = "https://" + RAW_HOST.replace("\\", "")
        for text in (host + "sessionmail/blob/" + OTHER + "/README.md",
                     host + "sessionkit/tree/" + OTHER,
                     host + "sessionphone/raw/" + OTHER + "/x.sh",
                     host + "sessionmail/blob/" + BRANCH + "/README.md",
                     host + "sessionkit/tree/" + BRANCH,
                     host + "sessiontools/blob/develop/x",
                     host + "sessionview/blob/" + REF + "/SPEC.md",
                     host + "sessionview/blob/" + BRANCH + "/SPEC.md",
                     host + "sessionview/tree/" + BRANCH + "/docs",
                     "git clone -b " + OTHER + " https://example.org/r",
                     "git clone --branch " + OTHER + " url",
                     "git clone --branch=" + OTHER + " url",
                     "git rebase origin/" + OTHER,
                     "git diff origin/" + OTHER + "..HEAD",
                     "see " + host + "sessionmail/tree/" + OTHER + ".",
                     "git checkout " + OTHER,
                     "git switch " + OTHER,
                     "git switch -c " + OTHER,
                     "git checkout --track " + OTHER,
                     "  then `git switch " + OTHER + "`.",
                     "git push origin " + OTHER,
                     "git push -u origin " + OTHER,
                     "git push origin HEAD:" + OTHER,
                     "git push origin " + OTHER + " && git push origin refs/tags/v1.2.3",
                     "git push upstream " + OTHER,
                     raw + "sessionmail/" + OTHER + "/install.sh",
                     raw + "sessionkit/" + BRANCH + "/install.sh",
                     raw + "sessionkit/develop/x",
                     raw + "sessionview/" + REF + "/install.sh"):
            with self.subTest(text=text):
                self.assertTrue(gate_hits(text))
        for text in (host + "sessionmail/blob/" + REF + "/README.md",
                     host + "sessionkit/tree/" + REF,
                     host + "sessionkit/blob/v0.2.0/docs/settings.md",
                     host + "sessionview",
                     host + "sessionkit",
                     host + "sessionview/issues",
                     "git clone -b " + BRANCH + " url",
                     "git clone --branch " + BRANCH + " url",
                     "git rebase origin/" + BRANCH,
                     "git rebase origin/" + OTHER + "-old",
                     "git rebase origin/" + OTHER + ".old",
                     "def " + OTHER + "():",
                     '"' + OTHER + '" if has("refs/heads/' + OTHER + '") else "' + BRANCH + '"',
                     "status --porcelain=v2 --branch",
                     "git checkout " + BRANCH,
                     "git switch " + BRANCH,
                     "git checkout " + OTHER + "-old",
                     "git switch release-" + OTHER,
                     "git checkout -- " + OTHER + ".py",
                     "git push origin " + BRANCH,
                     "git push origin rel-branch",
                     "git push origin " + OTHER + "-old",
                     'git push origin "$$branch" && git push origin "refs/tags/$$tag"',
                     "git push origin {branch} && git push origin refs/tags/{tag}",
                     "git push origin refs/tags/v1.2.3",
                     'self.git("init", "-q", "-b", "' + BRANCH + '")',
                     raw + "sessionkit/" + REF + "/install.sh",
                     raw + "sessionmail/v0.2.0/install.sh",
                     "https://raw.githubusercontent.com/other/tool/" + OTHER + "/x.sh"):
            with self.subTest(text=text):
                self.assertEqual(gate_hits(text), [])

    def test_scan_flags_planted_lines(self):
        # Plants in a scratch copy of the layout: one of each kind, in a doc,
        # a tool, a test and a binary; only the text files are hits.
        host = "https://" + HOST.replace("\\", "")
        plants = {"docs/a.md": "ok\n[s](%ssessionview/blob/%s/SPEC.md)\n" % (host, REF),
                  "bin/tool": "git clone --branch %s url\n" % OTHER,
                  "tests/test_x.py": "# %ssessionkit/blob/%s/docs\n" % (host, OTHER),
                  "docs/b.md": "[k](%ssessionkit/blob/%s/docs/settings.md)\n" % (host, BRANCH),
                  "macos/icon.icns": "\0git rebase origin/%s\n" % OTHER,
                  "docs/fine.md": "[k](%ssessionkit/blob/%s/docs/settings.md)\n" % (host, REF)}
        with tempfile.TemporaryDirectory() as tmp:
            for rel, body in plants.items():
                os.makedirs(os.path.join(tmp, os.path.dirname(rel)), exist_ok=True)
                with open(os.path.join(tmp, rel), "w", encoding="utf-8") as f:
                    f.write(body)
            repo, support.REPO = support.REPO, tmp
            try:
                found = scan(sorted(plants))
            finally:
                support.REPO = repo
        self.assertEqual(found, {"docs/a.md": [(2, "full URL to this repository")],
                                 "bin/tool": [(1, "branch instruction naming the other branch")],
                                 "tests/test_x.py": [(1, "kit URL naming a branch")],
                                 "docs/b.md": [(1, "kit URL naming a branch")]})

    def test_tracked_tree(self):
        paths = tracked_files()
        # Not vacuous: the tree is read, this file among it.
        self.assertIn(os.path.join("tests", "test_readme_links.py"), paths)
        found = scan(paths)
        self.assertEqual(found, {}, "a kit URL names HEAD or a v* tag, never a branch; a "
                         "branch instruction names master; a link into this repository is "
                         "relative: "
                         + ", ".join("%s line %d: %s" % (p, n, w)
                                     for p, hits in sorted(found.items()) for n, w in hits))


if __name__ == "__main__":
    unittest.main()
