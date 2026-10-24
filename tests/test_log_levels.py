"""bin/tmux-sidebar: ONE log, three levels (`log_level`, $SESSIONVIEW_LOG_LEVEL).

error (the default) writes only what went wrong, in the line format it always
had; timing adds `timing` lines (each command of TIMING_MIN_MS or more);
debug adds every command. The module is loaded into a child process the way
test_ready_where does, with its own HOME and state directory.

The clock is the HARNESS's, not the host's (SV-193). Each command really
runs, through the subprocess.run the module installs, but the milliseconds
it is timed at come from a fake `monotonic` the harness sets: 4x the floor,
exactly the floor, one below it, and 1ms. On a loaded host `python -c pass`
once took 50ms by the wall clock and earned a timing line; with the clock
faked, host load cannot move a command across the floor. The floor itself is
the module's own TIMING_MIN_MS, read at run time, so the >= comparison is
what is tested, at its edge."""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

from tests import support

SIDEBAR = os.path.join(support.BIN, "tmux-sidebar")
HARNESS = textwrap.dedent('''
    import importlib.machinery, importlib.util, sys, time
    loader = importlib.machinery.SourceFileLoader("sidebar", sys.argv[1])
    spec = importlib.util.spec_from_loader("sidebar", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)

    class Clock:
        """The module's `time`, but `monotonic` reads NOW, set by the harness."""
        now = 0.0
        def monotonic(self):
            return self.now
        def __getattr__(self, name):
            return getattr(time, name)
    clock = m.time = Clock()

    took = {}                       # tag -> the ms the command is timed at
    real_run = m._RUN
    def fake_run(*args, **kw):
        r = real_run(*args, **kw)   # the command really runs
        clock.now = took[args[0][-1]] / 1000
        return r
    m._RUN = fake_run

    floor = m.TIMING_MIN_MS
    print(floor)
    print(m.LOG_LEVEL)
    m.log_err("probe", "it broke")
    for tag, ms in (("slow-one", floor * 4), ("at-floor", floor),
                    ("below-floor", floor - 1), ("fast-one", 1)):
        took[tag] = ms
        clock.now = 0.0             # t0 is 0: the ms logged is exactly MS
        m.subprocess.run([sys.executable, "-c", "pass", tag])
    m.log("debug", "mouse", "btn=0 x=1 y=1")
''')


class LogLevels(unittest.TestCase):

    def run_at(self, level):
        """Run the harness at LEVEL; return (level it chose, floor, log)."""
        tmp = tempfile.TemporaryDirectory(prefix="sv-log-")
        self.addCleanup(tmp.cleanup)
        root = os.path.realpath(tmp.name)
        state = os.path.join(root, "state")
        env = {k: os.environ[k] for k in support.KEEP if k in os.environ}
        env.update(HOME=root, SESSIONVIEW_STATE=state)
        if level is not None:
            env["SESSIONVIEW_LOG_LEVEL"] = level
        r = subprocess.run([sys.executable, "-c", HARNESS, SIDEBAR], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        try:
            with open(os.path.join(state, "sessionview.log")) as f:
                log = f.read()
        except OSError:
            log = ""
        floor, chosen = r.stdout.strip().splitlines()[-2:]
        return chosen, int(floor), log

    def run_line(self, level, ms, tag):
        """The exact log line a timed `python -c pass TAG` gets at LEVEL."""
        return rf"(?m) {level} run: {ms}ms \S+ -c pass {tag}$"

    def test_the_floor_is_the_documented_50ms(self):
        # README, config/README and the CHANGELOG all say "50 ms or more".
        _, floor, _ = self.run_at("timing")
        self.assertEqual(floor, 50)

    def test_error_is_the_default_and_logs_errors_only(self):
        level, _, log = self.run_at(None)
        self.assertEqual(level, "error")
        self.assertRegex(log, r"(?m)^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d sock=\S+ probe: it broke$")
        self.assertNotIn(" timing ", log)
        self.assertNotIn(" debug ", log)
        self.assertNotIn(" run: ", log)

    def test_timing_names_the_slow_command_not_the_fast_one(self):
        level, floor, log = self.run_at("timing")
        self.assertEqual(level, "timing")
        self.assertIn("probe: it broke", log)
        self.assertRegex(log, self.run_line("timing", floor * 4, "slow-one"))
        self.assertNotIn("fast-one", log)
        self.assertNotIn(" debug ", log)

    def test_timing_at_the_floor_gets_a_line_one_below_does_not(self):
        level, floor, log = self.run_at("timing")
        self.assertEqual(level, "timing")
        self.assertRegex(log, self.run_line("timing", floor, "at-floor"))
        self.assertNotIn("below-floor", log)
        # Exactly two commands reached the floor: the slow one and the edge.
        self.assertEqual(log.count(" timing run: "), 2, log)

    def test_debug_adds_every_command_and_the_mouse(self):
        level, floor, log = self.run_at("DEBUG")
        self.assertEqual(level, "debug")
        # At or over the floor a command is still a timing line at debug;
        # under it, a debug line. Every command is named once.
        self.assertRegex(log, self.run_line("timing", floor * 4, "slow-one"))
        self.assertRegex(log, self.run_line("timing", floor, "at-floor"))
        self.assertRegex(log, self.run_line("debug", floor - 1, "below-floor"))
        self.assertRegex(log, self.run_line("debug", 1, "fast-one"))
        self.assertEqual(log.count(" run: "), 4, log)
        self.assertIn(" debug mouse: btn=0 x=1 y=1", log)

    def test_an_unknown_level_is_error_and_says_so(self):
        level, _, log = self.run_at("loud")
        self.assertEqual(level, "error")
        self.assertIn("log_level: unknown level 'loud': using error", log)
        self.assertNotIn(" run: ", log)


if __name__ == "__main__":
    unittest.main()
