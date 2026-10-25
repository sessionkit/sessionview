"""bin/sessionview-messages: nothing reaches the rc that neomutt runs unless it
is a plain box name or a plain folder path.

The tab writes an rc (`set folder="FOLDER"`, `named-mailboxes "NAME" ...`,
the Asks queries built from NAME) and runs it with `neomutt -F`. Inside an rc's
double quotes a backtick RUNS a command, `$` expands, `\\` escapes and `"`
ends the string; a line break starts a new rc line. So:

  PROJECT and --store SLUG   letters, digits and . _ + - only, else refused;
                             and never `.`, `..` or a leading . or - (the
                             name is joined under the mail root by `message
                             path`, which does not refuse `..` itself)
  FOLDER (`message path`)    refused when it holds " ` \\ $ or a control char

Each refusal is exit 2 before the rc is written (and, for a name, before
`message path` is asked). No neomutt runs here: a stub stands in, and every
probe is --print.
"""
import os
import shlex
import unittest

from tests import support

CMD = "sessionview-messages"

# message: `path BOX` prints $SV_FOLDER, and logs BOX
MESSAGE = '''#!/bin/sh
[ "$1" = path ] || exit 0
printf '%s\\n' "$2" >> {log}
printf '%s\\n' "$SV_FOLDER"
'''


class BoxNames(unittest.TestCase):

    def setUp(self):
        self._scratch = support.scratch_env()
        env, self.home = self._scratch.__enter__()
        stubs = os.path.join(self.home, "stubs")
        os.makedirs(stubs)
        self.log = os.path.join(self.home, "message.log")
        for name, text in (("message", MESSAGE.format(log=shlex.quote(self.log))),
                           ("neomutt", "#!/bin/sh\nexit 0\n"),
                           ("notmuch", "#!/bin/sh\nexit 1\n")):
            p = os.path.join(stubs, name)
            with open(p, "w") as f:
                f.write(text)
            os.chmod(p, 0o755)
        self.state = os.path.join(self.home, "state")
        self.folder = self.maildir("mail", "box")
        self.env = dict(env, PATH=stubs + os.pathsep + env.get("PATH", ""),
                        SESSIONVIEW_STATE=self.state, SV_FOLDER=self.folder)

    def tearDown(self):
        self._scratch.__exit__(None, None, None)

    def maildir(self, *parts):
        d = os.path.join(self.home, *parts)
        for sub in ("new", "cur", "tmp"):
            os.makedirs(os.path.join(d, sub), exist_ok=True)
        return d

    def messages(self, *args, folder=None):
        env = dict(self.env)
        if folder is not None:
            env["SV_FOLDER"] = folder
        return support.run(CMD, *args, "--print", env=env)

    def rcs(self):
        d = os.path.join(self.state, "mutt")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def asked(self):
        try:
            with open(self.log) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def assertRefused(self, r, what):
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn(what, r.stderr)
        self.assertEqual(self.rcs(), [], "an rc was written")

    # -- the good names still open ---------------------------------------------
    def test_plain_names_open(self):
        for args in (["store"], ["my.proj_1+x-y", "--store", "fx-corp"], ["P2", "--store", "A.b+c_d-e"]):
            with self.subTest(args=args):
                r = self.messages(*args)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(f'set folder="{self.folder}"', r.stdout)

    # -- PROJECT -------------------------------------------------------------------
    def test_a_project_name_outside_the_box_chars_is_refused(self):
        for name in ('p"x', "p`touch marker`", "p$HOME", "p\\x", "p x", "a/b", "p\nsource x", "pé"):
            with self.subTest(name=name):
                r = self.messages(name)
                self.assertRefused(r, "PROJECT")
        self.assertEqual(self.asked(), [], "message path was asked for a refused name")

    # -- --store SLUG --------------------------------------------------------------
    def test_a_store_slug_outside_the_box_chars_is_refused(self):
        for slug in ('s"x', "s`touch marker`", "s/x", "s;x"):
            with self.subTest(slug=slug):
                r = self.messages("store", "--store", slug)
                self.assertRefused(r, "--store")
        self.assertEqual(self.asked(), [], "message path was asked for a refused slug")

    # -- the SHAPE of a name: . .. and a leading . or - -------------------------
    def test_a_name_shaped_as_a_path_step_or_a_flag_is_refused(self):
        for name in (".", "..", ".x", "..x", ".hidden"):
            with self.subTest(project=name):
                r = self.messages(name)
                self.assertRefused(r, "PROJECT")
                self.assertIn("does not begin with . or -", r.stderr)
            with self.subTest(store=name):
                r = self.messages("store", "--store", name)
                self.assertRefused(r, "--store")
                self.assertIn("does not begin with . or -", r.stderr)
        # a leading - never reaches the box either: it is read as a flag
        for args in (["-x"], ["store", "--store", "-x"]):
            with self.subTest(args=args):
                self.assertEqual(self.messages(*args).returncode, 2)
                self.assertEqual(self.rcs(), [], "an rc was written")
        self.assertEqual(self.asked(), [], "message path was asked for a refused name")

    def test_a_dot_or_dash_inside_or_at_the_end_still_opens(self):
        for args in (["a.b"], ["x-"], ["x."], ["p", "--store", "s..t"], ["p", "--store", "s-"]):
            with self.subTest(args=args):
                r = self.messages(*args)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(f'set folder="{self.folder}"', r.stdout)

    # -- FOLDER ----------------------------------------------------------------------
    def test_a_folder_that_would_break_the_rc_is_refused(self):
        for bad in ('q"x', "q`touch marker`", "q\\x", "q$x", "q\nsource x"):
            with self.subTest(folder=bad):
                folder = self.maildir("mail", bad)
                r = self.messages("store", folder=folder)
                self.assertRefused(r, "folder")

    def test_a_folder_with_a_space_still_opens(self):
        folder = self.maildir("mail box", "store")
        r = self.messages("store", folder=folder)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f'set folder="{folder}"', r.stdout)


if __name__ == "__main__":
    unittest.main()
