"""skills/neovim/scripts/nvim-sock: the socket name carries the tmux SERVER.

Pane ids count per server, so two tmux servers each have a %0. The nvim that
sessionview-session opens listens on <socket dir>/nvim-show-<key>-pane-<n>,
where the key is the cksum of the server's socket path: show-me's convention,
so show-me reaches the same nvim. A name without the server collides: the
second server's pane %5 hit the first server's socket ("address already in
use"), and nvim-sock looked for the first server's nvim from the second.

Every tmux call is on a private socket (support.private_tmux); nothing here
names or touches a real server. The "nvim" is a bare unix socket at the name.
"""
import os
import socket
import subprocess
import unittest

from tests import support

NVIM_SOCK = os.path.join(support.REPO, "skills", "neovim", "scripts", "nvim-sock")


def server_key(socket_path):
    """The key for a tmux server: cksum of its socket path, no newline."""
    r = subprocess.run(["cksum"], input=socket_path, capture_output=True,
                       text=True, check=True)
    return r.stdout.split()[0]


class NvimSockPerServer(unittest.TestCase):
    def fmt(self, pt, fmt):
        r = pt.tmux("display-message", "-p", "-t", "=probe:", fmt)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def nvim_sock(self, pt, sockdir):
        env = pt.env()
        env["TMPDIR"] = sockdir
        return subprocess.run(["sh", NVIM_SOCK, "-L", pt.sock, "=probe:"], env=env,
                              capture_output=True, text=True, timeout=30)

    def test_finds_its_own_servers_socket_and_never_the_other_servers(self):
        with support.private_tmux("nsa") as a, support.private_tmux("nsb") as b:
            for pt in (a, b):
                r = pt.tmux("new-session", "-d", "-s", "probe", "-x", "80", "-y", "24")
                self.assertEqual(r.returncode, 0, r.stderr)
            pane = self.fmt(a, "#{pane_id}")
            # The collision this guards: the same pane id on both servers.
            self.assertEqual(pane, self.fmt(b, "#{pane_id}"))
            sockdir = a.tmpdir      # short: a unix socket path is capped at ~104 bytes
            name = os.path.join(sockdir, "nvim-show-%s-pane-%s"
                                % (server_key(self.fmt(a, "#{socket_path}")), pane.lstrip("%")))
            nvim = socket.socket(socket.AF_UNIX)
            nvim.bind(name)
            try:
                r = self.nvim_sock(a, sockdir)
                self.assertEqual((r.returncode, r.stdout.strip()), (0, name), r.stderr)
                r = self.nvim_sock(b, sockdir)
                self.assertEqual(r.returncode, 2, "server b found server a's nvim: " + r.stdout)
            finally:
                nvim.close()


if __name__ == "__main__":
    unittest.main()
