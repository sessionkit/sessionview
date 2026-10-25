"""The test Python is the run Python, and both sit inside requires-python.

`make test` once tried a bare python3 FIRST while the tools tried python3.14
first, so with a python3 of 3.15 on PATH the suite tested 3.15 while the tools
ran 3.14 (SV-171). Every probe site spells its own list (the Makefile, the
sourced lib/python.sh, and the sh trampolines of the Python tools); these tests
hold them to ONE order, and that order to the range pyproject.toml declares.
"""
import os
import re
import shutil
import stat
import subprocess
import tomllib
import unittest

from tests import support

#: The Makefile's PYTHON probe, then each runtime site's probe.
MAKEFILE = "Makefile"
RUNTIME_SITES = ("lib/python.sh", "bin/sessionview-config", "bin/tmux-sidebar",
                 "lib/sessionview-config-screen")
#: `for p in python3.14 ... python3; do` (`_sv_p` in lib/python.sh).
FOR_RX = re.compile(r"\bfor (?:p|_sv_p) in ((?:python3(?:\.\d+)?\s*)+);\s*do\b")


def read(rel):
    with open(os.path.join(support.REPO, rel), encoding="utf-8") as f:
        return f.read()


def probe(rel):
    """The probe list at site REL, as a tuple of names. Exactly one per site."""
    found = FOR_RX.findall(read(rel))
    if len(found) != 1:
        raise AssertionError(f"{rel}: {len(found)} python probe loops, want 1")
    return tuple(found[0].split())


def bounds(spec):
    """(floor, ceiling) minors of '>=3.F,<3.C' in either order, any spacing."""
    parts = sorted(p.strip() for p in spec.split(","))
    m = (re.fullmatch(r"<3\.(\d+)", parts[0]), re.fullmatch(r">=3\.(\d+)", parts[-1]))
    if len(parts) != 2 or not all(m):
        raise AssertionError(f"requires-python {spec!r} is not '>=3.F,<3.C'")
    return int(m[1][1]), int(m[0][1])


class ProbeOrder(unittest.TestCase):
    def test_every_runtime_site_matches_the_makefile(self):
        want = probe(MAKEFILE)
        for rel in RUNTIME_SITES:
            with self.subTest(site=rel):
                self.assertEqual(probe(rel), want)

    def test_bare_python3_is_the_last_resort(self):
        names = probe(MAKEFILE)
        self.assertEqual(names[-1], "python3")
        self.assertNotIn("python3", names[:-1])

    def test_the_versioned_names_are_the_declared_range_newest_first(self):
        floor, ceiling = bounds(tomllib.loads(read("pyproject.toml"))["project"]["requires-python"])
        want = tuple(f"python3.{m}" for m in range(ceiling - 1, floor - 1, -1)) + ("python3",)
        self.assertEqual(probe(MAKEFILE), want)

    def test_the_regex_sees_the_old_order(self):
        # A guard that matched nothing would pass vacuously: the old Makefile line.
        old = "for p in python3 python3.14 python3.13 python3.12 python3.11; do"
        self.assertEqual(FOR_RX.findall(old), ["python3 python3.14 python3.13 python3.12 python3.11"])


class DeclaredRange(unittest.TestCase):
    def test_pyproject_has_the_ceiling(self):
        spec = tomllib.loads(read("pyproject.toml"))["project"]["requires-python"]
        self.assertEqual(bounds(spec), (11, 15))

    def test_uv_lock_matches_pyproject(self):
        project = tomllib.loads(read("pyproject.toml"))["project"]["requires-python"]
        locked = tomllib.loads(read("uv.lock"))["requires-python"]
        self.assertEqual(bounds(locked), bounds(project))

    def test_the_install_check_ceiling_matches_pyproject(self):
        # bin/sessionview-install WARNs on a Python at or past PY_CEILING.
        m = re.findall(r'^PY_CEILING="3, (\d+)"$', read("bin/sessionview-install"), re.M)
        self.assertEqual(len(m), 1, "one PY_CEILING in bin/sessionview-install")
        _floor, ceiling = bounds(tomllib.loads(read("pyproject.toml"))["project"]["requires-python"])
        self.assertEqual(int(m[0]), ceiling)

    def test_every_install_hint_names_3_14(self):
        # A "no Python 3.11+" hint sends a user to 3.14, the newest the kit
        # verifies: never a plain `brew install python` (that is whatever
        # Homebrew's newest is) nor the old `uv python install 3.13 --default`.
        plain = re.compile(r"brew install python(?!@3\.14)|uv python install 3\.13|3\.13 --default")
        # lib/python.sh prints nothing; its callers (the installer) give the hint.
        for rel in (MAKEFILE, "bin/sessionview-install", *RUNTIME_SITES[1:]):
            with self.subTest(site=rel):
                text = read(rel)
                # assertTrue, not assertIn: a failure names the site, not its text.
                for hint in ("brew install python@3.14", "uv python install 3.14"):
                    self.assertTrue(hint in text, f"{rel} has no {hint!r} hint")
                bad = [n for n, line in enumerate(text.splitlines(), 1) if plain.search(line)]
                self.assertEqual(bad, [], f"{rel}: a plain hint on these lines")

    def test_no_shipped_file_has_a_plain_hint(self):
        plain = re.compile(r"brew install python(?!@3\.14)|3\.13 --default")
        hits = []
        for top, dirs, files in os.walk(support.REPO):
            dirs[:] = [d for d in dirs if d not in (".git", "tests", "__pycache__", ".venv")]
            for name in files:
                path = os.path.join(top, name)
                try:
                    with open(path, encoding="utf-8") as f:
                        text = f.read()
                except (UnicodeDecodeError, OSError):
                    continue
                rel = os.path.relpath(path, support.REPO)
                hits += [f"{rel}:{n}" for n, line in enumerate(text.splitlines(), 1) if plain.search(line)]
        self.assertEqual(hits, [])

    def test_the_docs_name_the_range(self):
        # The list lives in docs/dependencies.md; the README links it.
        # assertTrue, not assertIn: a failure names the line, not the whole page.
        text = read(os.path.join("docs", "dependencies.md"))
        self.assertTrue("| Python 3.11 to 3.14 |" in text, "docs/dependencies.md names no 'Python 3.11 to 3.14'")
        for rel in ("README.md", os.path.join("docs", "dependencies.md")):
            self.assertFalse("Python >= 3.11" in read(rel), f"{rel} still says 'Python >= 3.11'")


def fake_python(path):
    """A stand-in that passes the >= 3.11 probe: it exits 0 for any argv."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


@unittest.skipUnless(shutil.which("make"), "no make on PATH")
class SameChoice(unittest.TestCase):
    """With a python3 AND a python3.14 on PATH, make and lib/python.sh both
    take python3.14: the suite and the tools pick the same interpreter."""

    def setUp(self):
        self.ctx = support.scratch_env()
        self.env, home = self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        self.env.pop("SESSIONVIEW_PYTHON")      # this test is OF the probe
        self.bin = os.path.join(home, "bin")
        os.mkdir(self.bin)
        for name in ("python3", "python3.14"):
            fake_python(os.path.join(self.bin, name))
        # Only the fakes, the shell and make: no real python3.x on this PATH.
        self.env["PATH"] = os.pathsep.join(
            [self.bin, os.path.dirname(shutil.which("make")), "/usr/bin", "/bin"])
        self.want = os.path.join(self.bin, "python3.14")

    def test_make_takes_python3_14_over_a_bare_python3(self):
        # -n prints the recipe with $(PYTHON) expanded; it runs nothing.
        r = subprocess.run(["make", "-n", "-C", support.REPO, "test"], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f'if [ -z "{self.want}" ]', r.stdout)

    def test_lib_python_sh_takes_the_same(self):
        script = '. "$1/lib/python.sh"; printf %s "$SESSIONVIEW_PYTHON"'
        r = subprocess.run(["/bin/sh", "-c", script, "sh", support.REPO], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, self.want)


def fake_versioned(path, minor):
    """A stand-in for Python 3.MINOR that answers the installer's three
    one-liners: the >= 3.11 probe, the version print and the ceiling probe."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\n"
                'case "$2" in\n'
                f'  *"%d.%d"*) echo 3.{minor} ;;\n'
                f'  *"(3, 15)"*) [ {minor} -ge 15 ] ;;\n'
                "  *) exit 0 ;;\n"
                "esac\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


def fake_failing(path):
    """A stand-in that FAILS the >= 3.11 probe, so the probe passes over it."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\nexit 1\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


class InstallCheckCeiling(unittest.TestCase):
    """`sessionview-install --check` on a Python past the ceiling: a WARN that
    names the supported range, never MISSING (a user on 3.15 is not bricked).

    Hermetic: the fake bindir shadows EVERY versioned name the probe tries
    (python3.14 .. python3.11) with a fake that fails the probe, so the probe
    reaches the fake bare python3 under test. Without them a real
    /usr/bin/python3.1x (a Linux distro's) would win the probe first."""

    def check(self, minor):
        with support.scratch_env() as (env, home):
            env.pop("SESSIONVIEW_PYTHON")       # this test is OF the probe
            bindir = os.path.join(home, "bin")
            os.mkdir(bindir)
            for name in probe(MAKEFILE)[:-1]:
                fake_failing(os.path.join(bindir, name))
            fake_versioned(os.path.join(bindir, "python3"), minor)
            env["PATH"] = os.pathsep.join([bindir, "/usr/bin", "/bin"])
            r = support.run("sessionview-install", "--check", env=env)
        rows = [ln.split(None, 1) for ln in r.stdout.splitlines() if ln.strip()]
        rows = [row for row in rows if len(row) == 2 and row[1].startswith("python ")]
        self.assertEqual(len(rows), 1, r.stdout)
        return rows[0]

    def test_a_python_past_the_ceiling_warns(self):
        level, text = self.check(15)
        self.assertEqual(level, "WARN")
        self.assertIn("python 3.15 ", text)
        self.assertIn("3.11 to 3.14", text)

    def test_a_python_inside_the_range_passes(self):
        level, text = self.check(14)
        self.assertEqual(level, "PASS")
        self.assertIn("python 3.14 ", text)


if __name__ == "__main__":
    unittest.main()
