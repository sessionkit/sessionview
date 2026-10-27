"""bin/sessionview-session, project mode: a project's REPO resolves in the
store it was opened from (SV-183).

Two stores each hold a project named `skills`:

- store `forge`: git url `forge:pat/skills.git`, cloned at
  ~/Code/forge/pat/skills (the path the URL maps to);
- store `corp`: git url `gitbox:git/repos/tools-shared.git`, cloned at
  ~/Code/example.com/Corp/tools-shared (a path the URL does NOT map to).

The `tm project get` lookup is already store-scoped (`cd STORE && tm project
get`), and the stub `tm` here answers by cwd, the way the real one does. But
the fallbacks drop the store: the URL is turned into a path
(~/Code/gitbox/git/repos/tools-shared, which does not exist), and then
`~/Code/*/*/skills` takes the first dir named `skills` in ANY tree, so the
corp project opens forge's clone.

Everything runs in a scratch HOME (its own ~/Code, real `git init`ed clones,
GIT_CEILING_DIRECTORIES set), on a curated PATH: the stub `tm` and `message`,
then git, tmux and the suite's python, then /usr/bin:/bin. The real `tm` and
`message` are never reachable. --print builds nothing; the socket is a
private sv-test- one all the same.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest

from tests import support

_TM_STUB = r'''#!{python}
# tm, for this test: `project get NAME -f json` answers for the store the
# CWD is in (the real tm scopes by cwd too); `store list -f json` lists both.
import json, os, sys
FIX = json.load(open({fixtures!r}))
with open({log!r}, "a") as f:
    f.write(os.getcwd() + "\t" + " ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
if a[:2] == ["store", "list"]:
    print(json.dumps([{{"name": s, "store": s, "path": p}} for s, p in FIX["stores"].items()]))
    sys.exit(0)
if a[:2] == ["project", "get"] and len(a) > 2:
    here = os.path.realpath(os.getcwd())
    for s, p in FIX["stores"].items():
        if here == os.path.realpath(p) or here.startswith(os.path.realpath(p) + os.sep):
            rec = FIX["projects"].get(s, {{}}).get(a[2])
            if rec is None:
                print(f"tm: no project {{a[2]}}", file=sys.stderr); sys.exit(1)
            print(json.dumps(dict(rec, name=a[2]))); sys.exit(0)
    print(f"tm: no store at {{here}}", file=sys.stderr); sys.exit(1)
sys.exit(0)
'''

_MESSAGE_STUB = "#!/bin/sh\n# message, for this test: no box ever.\nexit 2\n"

FORGE_URL = "forge:pat/skills.git"
CORP_URL = "gitbox:git/repos/tools-shared.git"


class StoreRepoLookup(unittest.TestCase):
    TAG = "repolook"

    def setUp(self):
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        self.home = os.path.realpath(self.home)
        self._pt = support.private_tmux(self.TAG)
        self.pt = self._pt.__enter__()
        self.base = os.path.join(self.home, "fx")
        self.stub = os.path.join(self.base, "stub")      # tm + message
        self.tools = os.path.join(self.base, "tools")    # git, tmux, python3
        for d in (self.stub, self.tools):
            os.makedirs(d)
        for tool in ("git", "tmux"):
            found = shutil.which(tool)
            if found:
                os.symlink(found, os.path.join(self.tools, tool))
        os.symlink(sys.executable, os.path.join(self.tools, "python3"))
        if not shutil.which("git"):
            self.skipTest("SKIPPED: needs git, which is not on PATH")

        self.stores = {s: os.path.join(self.base, "stores", s) for s in ("forge", "corp")}
        for p in self.stores.values():
            os.makedirs(os.path.join(p, "projects", "skills"))
        self.fixtures = os.path.join(self.base, "fixtures.json")
        self.logfile = os.path.join(self.base, "tm-stub.log")
        self.data = {"stores": self.stores,
                     "projects": {"forge": {"skills": {"url": FORGE_URL}},
                                  "corp": {"skills": {"url": CORP_URL}}}}
        self.save()
        fill = dict(python=sys.executable, fixtures=self.fixtures, log=self.logfile)
        self.write_stub("tm", _TM_STUB.format(**fill))
        self.write_stub("message", _MESSAGE_STUB)

        code = os.path.join(self.home, "Code")
        self.forge_clone = os.path.join(code, "forge", "pat", "skills")
        self.corp_clone = os.path.join(code, "example.com", "Corp", "tools-shared")
        self.env = self.pt.env(env)
        self.env.update({
            "PATH": os.pathsep.join((self.stub, self.tools, "/usr/bin", "/bin")),
            "GIT_CEILING_DIRECTORIES": self.home,
            "GIT_CONFIG_NOSYSTEM": "1",
            "SESSIONVIEW_STATE": os.path.join(self.base, "state"),
            "SESSIONVIEW_CONFIG": os.path.join(self.base, "sessionview-config.json"),
            "VISUAL": "true",
        })
        self.clone(self.forge_clone, FORGE_URL)
        self.clone(self.corp_clone, CORP_URL)

    def tearDown(self):
        self._pt.__exit__(None, None, None)
        self._scratch.__exit__(None, None, None)

    # -- fixtures -------------------------------------------------------------
    def save(self):
        with open(self.fixtures, "w") as f:
            json.dump(self.data, f)

    def write_stub(self, name, text):
        p = os.path.join(self.stub, name)
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, 0o755)

    def clone(self, path, origin):
        """A git repo at PATH whose `origin` is ORIGIN: what a clone looks like
        to `git remote get-url origin`, with no network."""
        os.makedirs(path)
        for argv in (["init", "-q"], ["remote", "add", "origin", origin]):
            subprocess.run(["git", "-C", path, *argv], env=self.env, check=True,
                           capture_output=True, text=True, timeout=30)

    # -- runs -----------------------------------------------------------------
    def plan(self, name, store):
        r = support.run("sessionview-session", name, "--socket", self.pt.sock,
                        "--store", self.stores[store], "--print", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stderr

    def repo(self, name, store):
        """The repo= field of the --print header: a realpath, or NONE ($TMPDIR
        sits behind a symlink on macOS, so a path is compared resolved)."""
        head = self.plan(name, store).splitlines()[0]
        fields = dict(w.split("=", 1) for w in head.split() if "=" in w)
        return fields["repo"] if fields["repo"] == "NONE" else os.path.realpath(fields["repo"])

    # -- the bug ----------------------------------------------------------------
    def test_second_store_opens_its_own_clone(self):
        """corp's `skills` is the clone whose origin is corp's URL, never
        forge's `skills` found by name."""
        self.assertEqual(self.repo("skills", "corp"), self.corp_clone)

    def test_store_url_never_falls_back_to_another_stores_name_match(self):
        """The store gave a URL and no clone has that origin: no repo from a
        bare-name match in another tree."""
        shutil.rmtree(self.corp_clone)
        self.assertNotEqual(self.repo("skills", "corp"), self.forge_clone)

    def test_ssh_form_origin_matches_scp_url(self):
        """The store's scp-form URL matches a clone whose origin is the ssh://
        form of it, with or without .git."""
        subprocess.run(["git", "-C", self.corp_clone, "remote", "set-url", "origin",
                        "ssh://gitbox/git/repos/tools-shared"], env=self.env,
                       check=True, capture_output=True, text=True, timeout=30)
        self.assertEqual(self.repo("skills", "corp"), self.corp_clone)

    # -- the fix: origin decides, once the store gave a URL ---------------------
    def set_origin(self, path, url):
        subprocess.run(["git", "-C", path, "remote", "set-url", "origin", url],
                       env=self.env, check=True, capture_output=True, text=True, timeout=30)

    def test_store_url_with_no_matching_clone_is_no_repo(self):
        """Strict: no clone has the store's origin, so repo=NONE, not some
        other dir of the same name."""
        shutil.rmtree(self.corp_clone)
        self.assertEqual(self.repo("skills", "corp"), "NONE")

    def test_https_and_user_forms_match(self):
        """https://host/path and user@host:path.git read as the same repo as
        the store's host:path.git."""
        for url in ("https://gitbox/git/repos/tools-shared.git",
                    "git@gitbox:git/repos/tools-shared",
                    "ssh://git@gitbox:22/git/repos/tools-shared.git/"):
            with self.subTest(url=url):
                self.set_origin(self.corp_clone, url)
                self.assertEqual(self.repo("skills", "corp"), self.corp_clone)

    def test_url_spelled_path_must_pass_the_origin_check(self):
        """A dir at the path the URL spells is not taken on its path alone:
        its origin is another repo's, so the real clone wins."""
        spelled = os.path.join(self.home, "Code", "gitbox", "git", "repos", "tools-shared")
        self.clone(spelled, "forge:pat/something-else.git")
        self.assertEqual(self.repo("skills", "corp"), self.corp_clone)

    def test_url_spelled_path_with_its_origin_is_taken(self):
        """The path the URL spells, holding a clone with that origin, is the
        first candidate, ahead of one found by name."""
        spelled = os.path.join(self.home, "Code", "gitbox", "git", "repos", "tools-shared")
        self.clone(spelled, CORP_URL)
        self.assertEqual(self.repo("skills", "corp"), spelled)

    def test_url_spelled_path_is_the_last_resort(self):
        """No clone has the store's origin, but the path the URL spells holds
        a repo whose origin is another spelling of the same remote (a host
        alias with the forge's own path). It is named by this store's URL,
        not by NAME, so it opens, as it did before: never forge's clone."""
        shutil.rmtree(self.corp_clone)
        spelled = os.path.join(self.home, "Code", "gitbox", "git", "repos", "tools-shared")
        self.clone(spelled, "gitbox-alias:srv/git/tools-shared.git")
        self.assertEqual(self.repo("skills", "corp"), spelled)

    def test_origin_match_under_project_dirs(self):
        """A clone outside ~/Code, under `project_dirs`, is found by origin."""
        shutil.rmtree(self.corp_clone)
        ws = os.path.join(self.home, "workspace", "corp", "tools-shared")
        self.clone(ws, CORP_URL)
        self.assertEqual(self.repo("skills", "corp"), ws)

    def test_store_url_never_takes_a_name_match_under_project_dirs(self):
        """The store gave a URL and no clone has its origin: a dir named NAME
        under `project_dirs`, another store's clone, is not taken either."""
        shutil.rmtree(self.corp_clone)
        shutil.rmtree(self.forge_clone)
        ws = os.path.join(self.home, "workspace", "skills")
        self.clone(ws, FORGE_URL)
        self.assertEqual(self.repo("skills", "corp"), "NONE")

    def test_store_url_never_takes_a_url_named_dir_with_another_origin(self):
        """A dir named for the URL's last part is a candidate, not an answer:
        with another repo's origin it is not taken."""
        shutil.rmtree(self.corp_clone)
        other = os.path.join(self.home, "Code", "elsewhere", "pat", "tools-shared")
        self.clone(other, "forge:pat/tools-shared.git")
        self.assertEqual(self.repo("skills", "corp"), "NONE")

    def test_store_without_the_project_keeps_the_name_glob(self):
        """The store holds no such project (no URL): a name is all there is,
        and the ~/Code/*/*/NAME glob still opens."""
        del self.data["projects"]["corp"]["skills"]
        self.save()
        self.assertEqual(self.repo("skills", "corp"), self.forge_clone)

    # -- what already works and must keep working ---------------------------------
    def test_first_store_opens_its_own_clone(self):
        self.assertEqual(self.repo("skills", "forge"), self.forge_clone)

    def test_lookup_is_asked_from_the_store(self):
        self.repo("skills", "corp")
        with open(self.logfile) as f:
            gets = [l.split("\t") for l in f.read().splitlines() if "\tproject get " in l]
        self.assertTrue(gets, "tm project get was never asked")
        self.assertEqual(os.path.realpath(gets[0][0]), os.path.realpath(self.stores["corp"]))

    def test_no_taskmaster_keeps_project_dirs(self):
        """No tm on PATH at all: a name opens from `project_dirs`."""
        os.remove(os.path.join(self.stub, "tm"))
        app = os.path.join(self.home, "workspace", "app")
        self.clone(app, "forge:pat/app.git")
        self.assertEqual(self.repo("app", "forge"), app)


if __name__ == "__main__":
    unittest.main()
