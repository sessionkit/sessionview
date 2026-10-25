"""The installer never moves links that run another checkout (SV-198).

Twice in one day a probe in a second checkout re-pointed a machine's
~/.local/bin into that checkout. The first was `make -s -f Makefile -p` in a
task worktree, run to read one variable: `-p` builds the default goal, and that
was `install`. The second was a bare `make -s` in a scratch clone. Both moved
every link without a word on screen. Two layers close it, and this file
pins both:

- the Makefile's default goal is `help`, so `make`, `make -s` and `make -p`
  touch nothing;
- bin/sessionview-install refuses (exit 3, nothing changed) when a tool's name
  in the bin dir is already a link into a DIFFERENT checkout, or a file that
  is not a link. `--relink` moves them on purpose. A fresh bin dir, or a re-run
  from the checkout the links point into, links as before.

Every case runs under scratch_env() with PREFIX set inside the scratch HOME,
so nothing here can reach a real bin dir. "Another checkout" is a directory
of stand-in executables. The guard compares paths only, so a real second
clone would add time and prove nothing more. One case installs a copied
checkout for real first, then runs this one: the incident end to end.
"""
import os
import re
import shutil
import subprocess
import unittest

from tests import support

INSTALLER = os.path.join(support.BIN, "sessionview-install")
# The checkout as the installer names it: it resolves its root with
# readlink -f, so a suite run through a symlinked checkout path (a logical
# -t, or a linked clone) must compare against the physical path.
REPO = os.path.realpath(support.REPO)


def tools():
    """The names the installer links: bin/sessionview* and tmux-sidebar,
    executable files only (its own glob)."""
    out = []
    for name in sorted(os.listdir(support.BIN)):
        p = os.path.join(support.BIN, name)
        if (name.startswith("sessionview") or name == "tmux-sidebar") and \
                os.path.isfile(p) and os.access(p, os.X_OK):
            out.append(name)
    return out


def snapshot(bindir):
    """{name: link text, or 'FILE'} for every entry in BINDIR."""
    if not os.path.isdir(bindir):
        return {}
    out = {}
    for name in sorted(os.listdir(bindir)):
        p = os.path.join(bindir, name)
        out[name] = os.readlink(p) if os.path.islink(p) else "FILE"
    return out


class ScratchBin(unittest.TestCase):
    """A scratch HOME, PREFIX inside it, and a stand-in other checkout."""

    def setUp(self):
        self._ctx = support.scratch_env()
        self.env, self.home = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        # The physical path: macOS's default TMPDIR is under /var, a link to
        # /private/var. The installer resolves its checkout with readlink -f,
        # and the kernel walks a relative link's `..` from the physical dir,
        # so every path these cases build or compare must be physical too.
        self.home = os.path.realpath(self.home)
        self.env["PREFIX"] = os.path.join(self.home, ".local")
        self.bin = os.path.join(self.env["PREFIX"], "bin")
        # The safety net: no case may name a bin dir outside the scratch HOME.
        self.assertTrue(self.bin.startswith(self.home + os.sep), self.bin)
        # "Another checkout": the same tool names, as stand-in executables.
        self.other = os.path.join(self.home, "other-checkout", "bin")
        os.makedirs(self.other)
        for name in tools():
            p = os.path.join(self.other, name)
            with open(p, "w") as f:
                f.write("#!/bin/sh\nexit 0\n")
            os.chmod(p, 0o755)

    def install(self, *args):
        return subprocess.run([INSTALLER, *args], env=self.env, cwd=support.REPO,
                              capture_output=True, text=True, timeout=60)

    def link_all_to_other(self):
        os.makedirs(self.bin, exist_ok=True)
        for name in tools():
            os.symlink(os.path.join(self.other, name), os.path.join(self.bin, name))
        return snapshot(self.bin)

    def assertOurs(self):
        for name in tools():
            self.assertEqual(os.path.realpath(os.path.join(self.bin, name)),
                             os.path.realpath(os.path.join(support.BIN, name)), name)

    def assertRefused(self, r, before):
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("refusing to re-point links in " + self.bin, r.stderr)
        self.assertIn("--relink", r.stderr)
        self.assertIn(REPO, r.stderr)
        self.assertNotIn("linked", r.stdout)
        self.assertNotIn("requirements:", r.stdout)
        self.assertEqual(snapshot(self.bin), before, "a refusal changed the bin dir")


class InstallGuardTest(ScratchBin):
    """bin/sessionview-install's different-checkout refusal."""

    # -- as before: a fresh bin dir, a re-run from the same checkout ----------

    def test_fresh_bin_links_every_tool(self):
        r = self.install()
        self.assertNotEqual(r.returncode, 3, r.stderr)
        self.assertIn(f"linked {len(tools())} tools into {self.bin}", r.stdout)
        self.assertOurs()

    def test_rerun_from_the_same_checkout_relinks_quietly(self):
        self.install()
        r = self.install()
        self.assertNotEqual(r.returncode, 3, r.stderr)
        self.assertNotIn("refusing", r.stderr)
        self.assertOurs()

    def test_relative_link_into_this_checkout_is_ours(self):
        os.makedirs(self.bin)
        for name in tools():
            target = os.path.relpath(os.path.join(support.BIN, name), self.bin)
            os.symlink(target, os.path.join(self.bin, name))
        r = self.install()
        self.assertNotEqual(r.returncode, 3, r.stderr)

    def test_a_new_tool_beside_our_links_is_added(self):
        self.install()
        os.remove(os.path.join(self.bin, "tmux-sidebar"))
        r = self.install()
        self.assertNotEqual(r.returncode, 3, r.stderr)
        self.assertOurs()

    # -- the guard -------------------------------------------------------------

    def test_links_into_another_checkout_are_refused(self):
        before = self.link_all_to_other()
        r = self.install()
        self.assertRefused(r, before)
        self.assertIn(os.path.join(self.other, "sessionview"), r.stderr)

    def test_one_foreign_link_among_ours_is_refused(self):
        self.install()
        p = os.path.join(self.bin, "sessionview-config")
        os.remove(p)
        os.symlink(os.path.join(self.other, "sessionview-config"), p)
        before = snapshot(self.bin)
        r = self.install()
        self.assertRefused(r, before)
        self.assertIn("sessionview-config", r.stderr)

    def test_a_dangling_link_into_another_checkout_is_refused(self):
        os.makedirs(self.bin)
        os.symlink(os.path.join(self.home, "gone", "bin", "sessionview"),
                   os.path.join(self.bin, "sessionview"))
        before = snapshot(self.bin)
        r = self.install()
        self.assertRefused(r, before)
        self.assertIn("(missing)", r.stderr)

    def test_a_file_that_is_not_a_link_is_refused(self):
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "sessionview"), "w") as f:
            f.write("#!/bin/sh\n")
        before = snapshot(self.bin)
        r = self.install()
        self.assertRefused(r, before)
        self.assertIn("(a file, not a link)", r.stderr)

    def test_relink_moves_them_on_purpose(self):
        self.link_all_to_other()
        r = self.install("--relink")
        self.assertNotEqual(r.returncode, 3, r.stderr)
        self.assertIn(f"linked {len(tools())} tools", r.stdout)
        self.assertOurs()

    def test_the_dispatcher_takes_the_same_path(self):
        before = self.link_all_to_other()
        r = subprocess.run([os.path.join(support.BIN, "sessionview"), "install"],
                           env=self.env, cwd=support.REPO,
                           capture_output=True, text=True, timeout=60)
        self.assertRefused(r, before)

    def test_check_changes_nothing_and_does_not_refuse(self):
        before = self.link_all_to_other()
        r = self.install("--check")
        self.assertNotEqual(r.returncode, 3, r.stderr)
        self.assertEqual(snapshot(self.bin), before)

    def test_help_prints_the_whole_header_and_acts_on_nothing(self):
        # SV-197's --help printed a fixed line range; this guard's paragraph
        # grew the header past it, and the usage lost its tail. It ends at
        # `set -u` now, so the --relink line and the guard's paragraph show.
        before = self.link_all_to_other()
        for flag in ("--help", "-h"):
            with self.subTest(flag=flag):
                r = self.install(flag)
                self.assertEqual((r.returncode, r.stderr), (0, ""))
                self.assertIn("sessionview-install --relink", r.stdout)
                self.assertIn("Re-running is safe (ln -sfn).", r.stdout)
                self.assertIn("nothing printed a word.)", r.stdout)
                self.assertNotIn("set -u", r.stdout)
                self.assertEqual(snapshot(self.bin), before, f"{flag} changed the bin dir")

    def test_a_second_checkout_cannot_take_over_a_real_install(self):
        # End to end, the incident's shape: checkout A installs for real, then
        # this checkout (B, a task worktree in the incident) runs the same
        # install. A is a copy of bin/ and lib/, all the installer reads.
        a = os.path.join(self.home, "checkout-A")
        for d in ("bin", "lib"):
            shutil.copytree(os.path.join(support.REPO, d), os.path.join(a, d),
                            symlinks=True)
        first = subprocess.run([os.path.join(a, "bin", "sessionview-install")],
                               env=self.env, cwd=a, capture_output=True,
                               text=True, timeout=60)
        self.assertIn(f"linked {len(tools())} tools into {self.bin}", first.stdout,
                      first.stderr)
        before = snapshot(self.bin)
        for name in tools():
            self.assertEqual(before[name], os.path.join(a, "bin", name))
        r = self.install()
        self.assertRefused(r, before)
        self.assertIn(os.path.join(a, "bin", "sessionview"), r.stderr)


class CheckSeesForeignLinksTest(ScratchBin):
    """`--check` WARNs on each tool name the install would refuse over.

    The refusal only shows when someone runs an install. The read-only check
    uses the same detection, so a machine whose links run another checkout
    shows it on `--check` too: one WARN per name, nothing written, and the
    exit status the requirements give, as before.
    """

    def warned(self, r):
        """{name: rest of line} for each foreign-link WARN in R's stdout."""
        out = {}
        for line in r.stdout.splitlines():
            m = re.match(r"^  WARN +(\S+) -> (.*)$", line)
            if m:
                out[m.group(1)] = m.group(2)
        return out

    def check(self):
        before = snapshot(self.bin)
        r = self.install("--check")
        self.assertEqual(snapshot(self.bin), before, "--check changed the bin dir")
        self.assertNotIn("refusing", r.stderr)
        self.assertNotIn("linked", r.stdout)
        return r

    def test_every_link_into_another_checkout_is_warned(self):
        self.link_all_to_other()
        w = self.warned(self.check())
        self.assertEqual(sorted(w), tools())
        for name in tools():
            self.assertIn(os.path.join(self.other, name), w[name])
            self.assertIn("--relink", w[name])

    def test_one_foreign_link_among_ours_is_the_one_warned(self):
        self.install()
        p = os.path.join(self.bin, "sessionview-config")
        os.remove(p)
        os.symlink(os.path.join(self.other, "sessionview-config"), p)
        self.assertEqual(sorted(self.warned(self.check())), ["sessionview-config"])

    def test_a_dangling_link_is_warned(self):
        os.makedirs(self.bin)
        os.symlink(os.path.join(self.home, "gone", "bin", "sessionview"),
                   os.path.join(self.bin, "sessionview"))
        w = self.warned(self.check())
        self.assertEqual(sorted(w), ["sessionview"])
        self.assertIn("(missing)", w["sessionview"])

    def test_a_file_that_is_not_a_link_is_warned(self):
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "sessionview"), "w") as f:
            f.write("#!/bin/sh\n")
        w = self.warned(self.check())
        self.assertEqual(sorted(w), ["sessionview"])
        self.assertIn("(a file, not a link)", w["sessionview"])

    def test_our_own_links_and_an_empty_bin_warn_nothing(self):
        self.assertEqual(self.warned(self.check()), {}, "empty bin dir")
        self.install()
        self.assertEqual(self.warned(self.check()), {}, "after our own install")

    def test_a_warn_leaves_the_exit_status_as_it_was(self):
        # The exit status is the requirements' (tmux, python, neomutt on this
        # host), so compare against the same check over our own links.
        self.install()
        clean = self.check()
        self.link_all_to_other()  # over ours: replace each with a foreign one
        foreign = self.check()
        self.assertTrue(self.warned(foreign))
        self.assertEqual(foreign.returncode, clean.returncode,
                         foreign.stdout + foreign.stderr)

    def link_all_to_other(self):
        os.makedirs(self.bin, exist_ok=True)
        for name in tools():
            p = os.path.join(self.bin, name)
            if os.path.lexists(p):
                os.remove(p)
            os.symlink(os.path.join(self.other, name), p)
        return snapshot(self.bin)


class LinkReplacesDirLinkTest(ScratchBin):
    """The link step replaces a link to a directory; it never writes into it.

    `ln -sf SRC LINK`, when LINK is a symlink to a directory, follows it and
    puts a new link INSIDE that directory, leaving LINK as it was. `ln -sfn`
    replaces LINK itself.
    """

    def test_relink_over_a_link_to_a_directory_replaces_it(self):
        os.makedirs(self.bin)
        target = os.path.join(self.home, "some-dir")
        os.makedirs(target)
        os.symlink(target, os.path.join(self.bin, "sessionview"))
        r = self.install("--relink")
        self.assertNotEqual(r.returncode, 3, r.stderr)
        self.assertEqual(os.listdir(target), [], "the link step wrote into the directory")
        self.assertOurs()


class MakeDefaultGoalTest(ScratchBin):
    """The Makefile's default goal is help: `make`, `-s`, `-p` touch nothing."""

    def make(self, *args):
        if shutil.which("make") is None:
            self.skipTest("SKIPPED: needs make, which is not on PATH")
        return subprocess.run(["make", *args], env=self.env, cwd=support.REPO,
                              capture_output=True, text=True, timeout=60)

    def test_make_print_database_installs_nothing(self):
        # The first incident's command, verbatim (`-p` builds the default goal).
        before = self.link_all_to_other()
        self.make("-s", "-f", "Makefile", "-p")
        self.assertEqual(snapshot(self.bin), before)

    def test_bare_make_into_an_empty_bin_links_nothing(self):
        # The second incident's command. The empty bin is the case the link
        # guard cannot catch (nothing there to protect), so only the goal can.
        r = self.make("-s")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("make install", r.stdout)
        self.assertEqual(snapshot(self.bin), {})


if __name__ == "__main__":
    unittest.main()
