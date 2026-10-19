"""bin/sessionview-messages: the sidebar rows, boxes down the side, one of
them Asks.

The rows are per project and written into the per-folder rc; config/neomuttrc
is the look. Three rows when notmuch holds the folder: the box, Asks, and
Asks · threads; none, and the sidebar hidden, when it does not. The notmuch
here is a shim in the fixture bin (first on PATH), so the real index is never
read and the fixture folder can be put under, or outside, its database.path.
"""
import os
import unittest

from tests import support
from tests.test_project_messages import ProjectMailBase

CMD = "sessionview-messages"

SHIM = '''#!/bin/sh
# notmuch shim: `config get KEY` answers from env NM_<KEY with . -> _>
[ "$1" = config ] && [ "$2" = get ] || exit 1
k="NM_$(printf '%s' "$3" | tr '.' '_')"
eval "v=\\${$k:-}"; printf '%s\\n' "$v"
'''


class SidebarRows(ProjectMailBase):
    TAG = "sbar"

    def setUp(self):
        super().setUp()
        self.boxes("fx-corp/store")
        p = os.path.join(self.fx.bin, "notmuch")
        with open(p, "w") as f:
            f.write(SHIM)
        os.chmod(p, 0o755)
        self.folder = self.data["boxes"]["fx-corp/store"]

    def plan_messages(self, **nm):
        env = dict(self.env)
        env.update({"NM_" + k.replace(".", "_"): v for k, v in nm.items()})
        r = support.run(CMD, "store", "--store", "fx-corp", "--print", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_indexed_headers_give_the_three_rows(self):
        out = self.plan_messages(**{"database.path": os.path.join(self.fx.base, "mail"),
                                    "index.header.Type": "Type",
                                    "index.header.Project": "Project"})
        self.assertIn("sidebar=store, Asks, Asks · threads\n", out)
        q = 'Type:ask and (to:\\"store+ask\\" or Project:\\"store\\")'
        self.assertIn(f'named-mailboxes "store" "{self.folder}"', out)
        self.assertIn(f'virtual-mailboxes "Asks" "notmuch://?query={q}"', out)
        self.assertIn(f'virtual-mailboxes "Asks · threads" "notmuch://?type=threads&query={q}"', out)
        self.assertIn(f'set nm_default_url="notmuch://{os.path.join(self.fx.base, "mail")}"', out)
        self.assertNotIn("sidebar_visible=no", out)
        # the rows come BEFORE the shared look, so the user's rc (last) still wins
        self.assertLess(out.index("virtual-mailboxes"), out.index("config/neomuttrc"))

    def test_unindexed_headers_fall_back_to_the_plus_ask_box(self):
        out = self.plan_messages(**{"database.path": os.path.join(self.fx.base, "mail")})
        self.assertIn('virtual-mailboxes "Asks" "notmuch://?query=to:\\"store+ask\\""', out)
        self.assertIn("# sidebar: notmuch does not index Type and Project", out)
        self.assertIn("notmuch config set index.header.Type Type", out)

    def test_folder_outside_the_database_hides_the_sidebar(self):
        out = self.plan_messages(**{"database.path": os.path.join(self.fx.base, "elsewhere")})
        self.assertIn("sidebar=none: ", out)
        self.assertIn("is not under notmuch database.path", out)
        self.assertNotIn("virtual-mailboxes", out)
        # hidden AFTER the shared rc turned it on
        self.assertLess(out.index("config/neomuttrc"), out.index("set sidebar_visible=no"))
        # and the folder lines the tab always had are still first
        self.assertIn(f'box=fx-corp/store folder={self.folder} ', out)


if __name__ == "__main__":
    unittest.main()
