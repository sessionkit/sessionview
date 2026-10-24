"""Guard: no work-hour stamp in the exported tree (SK-97, a gate on the public release).

A Mon-Fri stamp (weekday, date, and a time of day) whose time starts from 09:00
up to, not including, 17:00 must not ship. The scan runs over `git archive HEAD`,
the tree an export ships (export-ignore honoured), not the working directory.
Remove the time of day from a new stamp, or drop the stamp.

The pattern is the SK-42 STAMP_RE, copied verbatim, with its 09:00-17:00 start
window. This file spells no stamp out, so it does not trip itself.

On a hit the test prints path:count and never the matched text.
"""
import collections
import io
import re
import subprocess
import tarfile
import unittest

from tests import support

STAMP_RE = re.compile(r"[0-9]{1,2}:[0-9]{2}(:[0-9]{2})?(-[0-9]{1,2}:[0-9]{2})?"
                      r" (Mon|Tue|Wed|Thu|Fri) 20[0-9]{2}-[0-9]{2}-[0-9]{2}")

def start_minutes(match):
    """Minutes since midnight of the stamp's (first) time of day."""
    hh, mm = match.group(0).split(" ", 1)[0].split("-", 1)[0].split(":")[:2]
    return int(hh) * 60 + int(mm)


def work_hour_hits(text):
    """How many work-hour stamps `text` holds (09:00 up to, not including, 17:00)."""
    return sum(1 for line in text.splitlines() for m in STAMP_RE.finditer(line)
               if 9 * 60 <= start_minutes(m) < 17 * 60)


def scan_archive(data):
    """{path: hits} over the tar bytes `data`, every file in it."""
    found = collections.Counter()
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            raw = tar.extractfile(member).read()
            if b"\0" in raw[:8192]:
                continue
            hits = work_hour_hits(raw.decode("utf8", "replace"))
            if hits:
                found[member.name] = hits
    return found


class WorkHourStamps(unittest.TestCase):
    def test_regex_window(self):
        # Built at run time so no stamp is spelled in this file.
        # Here and in the planted stamp below, the day name is a STAMP_RE token
        # (Mon-Fri) that is never checked against the date, and the date is a
        # synthetic Sunday on purpose. The mismatch is deliberate: do not "fix" it.
        def stamp(hhmm, day="Wed"):
            return "%s %s 2030-06-09" % (hhmm, day)
        self.assertEqual(work_hour_hits("x " + stamp("09:00") + " y"), 1)
        self.assertEqual(work_hour_hits(stamp("16:59")), 1)
        self.assertEqual(work_hour_hits(stamp("08:59")), 0)
        self.assertEqual(work_hour_hits(stamp("17:00")), 0)
        self.assertEqual(work_hour_hits(stamp("13:37", "Sat")), 0)
        self.assertEqual(work_hour_hits(stamp("13:00-14:00")), 1)
        self.assertEqual(work_hour_hits("Wed 2030-06-09"), 0)

    def test_scan_flags_a_planted_stamp(self):
        planted = ("%s Wed 2030-06-09 planted\n" % "13:37").encode()
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for name in ("docs/planted.md", "config/planted.md", "bin/tmux-sidebar"):
                info = tarfile.TarInfo(name)
                info.size = len(planted)
                tar.addfile(info, io.BytesIO(planted))
        self.assertEqual(dict(scan_archive(buf.getvalue())),
                         {"docs/planted.md": 1, "config/planted.md": 1, "bin/tmux-sidebar": 1})

    def test_exported_tree_has_no_work_hour_stamp(self):
        try:
            data = subprocess.check_output(
                ["git", "-C", support.REPO, "archive", "HEAD"], stderr=subprocess.DEVNULL)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("not a git checkout: no git archive HEAD")
        found = scan_archive(data)
        report = "\n".join("  %s:%d" % (p, n) for p, n in sorted(found.items()))
        self.assertFalse(found, "work-hour stamps in git archive HEAD (path:count):\n" + report)


if __name__ == "__main__":
    unittest.main()
