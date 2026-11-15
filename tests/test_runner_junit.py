"""tests/_runner.py: `make test`'s runner is unittest, plus a junit report
when PYTEST_ADDOPTS asks for one.

A tiny synthetic suite (pass, skip, fail, error, expected failure,
unexpected success, subTests, a class skipped in setUpClass, a class whose
setUpClass errors, a module skipped at import, a module that fails to import)
is run through the runner in a subprocess, and:

- the stream (-v lines, `Ran N tests`, the result line) and the exit code
  equal plain `python -m unittest discover`'s, timings aside;
- with --junitxml (either spelling) the report names every outcome, each
  skip with its reason, and its named skips equal the stream's `skipped=N`,
  read the way a junit-reading check reads it (file::Class::name node ids);
- with no --junitxml, nothing is written.

The child never inherits this run's PYTEST_ADDOPTS (scratch_env keeps only
an allow-list), so a check running this suite under a report is not written
to by the synthetic one.
"""
import os
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest
import xml.etree.ElementTree as ET

from tests import support
from tests import _runner

SYNTH = {
    "synth/__init__.py": "",
    "synth/test_mix.py": '''
        import unittest

        class Mix(unittest.TestCase):
            def test_pass(self):
                pass

            @unittest.skip("not on this machine")
            def test_skip(self):
                pass

            def test_skip_inside(self):
                self.skipTest("decided at run time")

            def test_fail(self):
                self.assertEqual(1, 2)

            def test_error(self):
                raise RuntimeError("boom")

            @unittest.expectedFailure
            def test_xfail(self):
                self.assertTrue(False)

            @unittest.expectedFailure
            def test_xpass(self):
                pass

            def test_subtests(self):
                for i in range(3):
                    with self.subTest(i=i):
                        if i == 1:
                            self.assertEqual(i, 0)
                        if i == 2:
                            self.skipTest("sub skipped")
    ''',
    "synth/test_classskip.py": '''
        import unittest

        class Skipped(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise unittest.SkipTest("the whole class is off")

            def test_one(self):
                pass

            def test_two(self):
                pass

        class Broken(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise RuntimeError("fixture broke")

            def test_never(self):
                pass

        class Fine(unittest.TestCase):
            def test_fine(self):
                pass
    ''',
    "synth/test_modskip.py": '''
        import unittest
        raise unittest.SkipTest("module off here")
    ''',
    "synth/test_broken.py": '''
        import no_such_module_anywhere
    ''',
}

#: Only passes and a skip: a green run, like the real suite's.
GREEN = {
    "green/__init__.py": "",
    "green/test_green.py": '''
        import unittest

        class Green(unittest.TestCase):
            def test_a(self):
                pass

            @unittest.skip("opt-in probe is off")
            def test_probe(self):
                pass
    ''',
}

_TIMING_RE = re.compile(r"^(Ran \d+ tests? in )[\d.]+s$", re.MULTILINE)
#: unittest's result line, as a junit-reading check reads it.
_RESULT_RE = re.compile(r"^(OK|FAILED|NO TESTS RAN)(?: \(((?:[a-z ]+=\d+(?:, )?)+)\))?$",
                        re.MULTILINE)


def _write_tree(root, files):
    for rel, body in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(body))


def _run(root, start, *, runner=True, addopts=None):
    """Run discovery over ROOT/START, via the runner or plain unittest."""
    module = "tests._runner" if runner else "unittest"
    extra = {"PYTHONPATH": support.REPO}
    if addopts is not None:
        extra["PYTEST_ADDOPTS"] = addopts
    with support.scratch_env(**extra) as (env, _home):
        return subprocess.run(
            [sys.executable, "-B", "-m", module, "discover", "-s", start, "-t", ".", "-v"],
            cwd=root, env=env, capture_output=True, text=True, timeout=60)


def _normal(text):
    return _TIMING_RE.sub(r"\1Xs", text)


def _nodeid(file, classname, name):
    """A check's node id: file::Class::name (the module part dropped)."""
    dotted = (file[:-3] if file.endswith(".py") else file).replace("/", ".")
    classes = ""
    if classname and classname != dotted and classname.startswith(dotted + "."):
        classes = classname[len(dotted) + 1:].replace(".", "::")
    return "::".join(p for p in (file, classes, name) if p)


def _read(path):
    """{nodeid: (outcome, reason)} from a report, as a check reads it."""
    out = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        file, classname, name = case.get("file") or "", case.get("classname") or "", case.get("name") or ""
        outcome, reason, collection = "passed", "", False
        for child in case:
            if child.tag == "skipped":
                if child.get("type") == "pytest.xfail":
                    outcome = "xfailed"
                    break
                outcome, reason = "skipped", child.get("message") or ""
                if not classname and reason == "collection skipped":
                    collection = True
                    found = re.search(r"Skipped: (.*?)['\"]\)\s*$", child.text or "", re.DOTALL)
                    reason = found.group(1) if found else reason
                break
            if child.tag in ("failure", "error"):
                outcome = child.tag
                break
        node = file if collection and file else _nodeid(file, classname, name)
        out[node] = (outcome, reason)
    return out


def _stream_skips(text):
    found = _RESULT_RE.findall(text)
    assert found, "no unittest result line in the stream"
    counts = dict((k.strip(), int(v)) for k, v in re.findall(r"([a-z ]+)=(\d+)", found[-1][1]))
    return counts.get("skipped", 0)


class RunnerJunitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="sessionview-runner-")
        cls.root = cls._tmp.name
        _write_tree(cls.root, SYNTH)
        _write_tree(cls.root, GREEN)
        cls.report = os.path.join(cls.root, "out", "junit.xml")
        cls.mixed = _run(cls.root, "synth",
                         addopts=shlex.join(["--junitxml=" + cls.report, "-o", "junit_family=xunit1"]))
        cls.plain = _run(cls.root, "synth", runner=False)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_stream_and_exit_code_equal_plain_unittest(self):
        self.assertEqual(self.mixed.returncode, self.plain.returncode)
        self.assertEqual(self.mixed.returncode, 1)
        self.assertEqual(_normal(self.mixed.stdout), _normal(self.plain.stdout))
        self.assertEqual(_normal(self.mixed.stderr), _normal(self.plain.stderr))
        self.assertIn("FAILED (", self.mixed.stderr)

    def test_report_names_every_outcome(self):
        nodes = _read(self.report)
        mix = "synth/test_mix.py::Mix::"
        want = {
            mix + "test_pass": ("passed", ""),
            mix + "test_skip": ("skipped", "not on this machine"),
            mix + "test_skip_inside": ("skipped", "decided at run time"),
            mix + "test_fail": ("failure", ""),
            mix + "test_error": ("error", ""),
            mix + "test_xfail": ("xfailed", ""),
            mix + "test_xpass": ("failure", ""),
            mix + "test_subtests[i=1]": ("failure", ""),
            mix + "test_subtests[i=2]": ("skipped", "sub skipped"),
            "synth/test_classskip.py::Skipped::setUpClass": ("skipped", "the whole class is off"),
            "synth/test_classskip.py::Broken::setUpClass": ("error", ""),
            "synth/test_classskip.py::Fine::test_fine": ("passed", ""),
            "synth/test_modskip.py": ("skipped", "module off here"),
            "synth/test_broken.py::test_broken": ("error", ""),
        }
        self.assertEqual(nodes, want)

    def test_named_skips_equal_the_stream_count(self):
        nodes = _read(self.report)
        named = sum(1 for outcome, _ in nodes.values() if outcome == "skipped")
        self.assertEqual(named, _stream_skips(self.mixed.stderr))
        self.assertEqual(named, 5)

    def test_report_carries_xunit1_attributes(self):
        root = ET.parse(self.report).getroot()
        cases = list(root.iter("testcase"))
        self.assertTrue(cases)
        for case in cases:
            for attr in ("file", "classname", "name", "time"):
                self.assertIn(attr, case.attrib, ET.tostring(case))
            float(case.get("time"))
        fail = [c for c in cases if c.get("name") == "test_fail"][0]
        self.assertEqual(fail.get("classname"), "synth.test_mix.Mix")
        self.assertIn("AssertionError", fail.find("failure").get("message"))
        self.assertIn("Traceback", fail.find("failure").text)

    def test_space_form_and_green_run(self):
        report = os.path.join(self.root, "green.xml")
        got = _run(self.root, "green", addopts="--junitxml %s -o junit_family=xunit1" % shlex.quote(report))
        plain = _run(self.root, "green", runner=False)
        self.assertEqual(got.returncode, 0)
        self.assertEqual(_normal(got.stderr), _normal(plain.stderr))
        self.assertIn("OK (skipped=1)", got.stderr)
        self.assertEqual(_read(report), {
            "green/test_green.py::Green::test_a": ("passed", ""),
            "green/test_green.py::Green::test_probe": ("skipped", "opt-in probe is off"),
        })

    def test_no_var_writes_nothing(self):
        before = set(os.listdir(self.root))
        got = _run(self.root, "green")
        self.assertEqual(got.returncode, 0)
        self.assertEqual(set(os.listdir(self.root)), before)
        self.assertFalse(any(n.endswith(".xml") for n in os.listdir(os.path.join(self.root, "green"))))


class JunitPathTest(unittest.TestCase):
    def test_flag_forms(self):
        cases = {
            "--junitxml=/x/r.xml -o junit_family=xunit1": "/x/r.xml",
            "--junitxml /x/r.xml -o junit_family=xunit1": "/x/r.xml",
            "-o junit_family=xunit1 --junit-xml=/y.xml": "/y.xml",
            "'--junitxml=/a b/r.xml'": "/a b/r.xml",
            "--junitxml=/one.xml --junitxml=/two.xml": "/two.xml",
            "--deselect tests/test_x.py::T::t": None,
            "--junitxml": None,
            "--junitxml='unclosed": None,
            "": None,
        }
        for value, want in cases.items():
            with self.subTest(value=value):
                self.assertEqual(_runner.junit_path({"PYTEST_ADDOPTS": value}), want)
        self.assertIsNone(_runner.junit_path({}))

    def test_xml_forbidden_characters_are_escaped(self):
        root = _runner.build_report([{
            "file": "t.py", "classname": "t.T", "name": "test_x", "time": 0.0,
            "kind": "skipped", "message": "bell \x07 here", "text": "",
        }], 0.0)
        parsed = ET.fromstring(ET.tostring(root))
        self.assertEqual(parsed.find(".//skipped").get("message"), "bell \\x07 here")


class MakefileTest(unittest.TestCase):
    def test_make_test_runs_the_runner(self):
        with open(os.path.join(support.REPO, "Makefile"), encoding="utf-8") as f:
            text = f.read()
        recipe = re.search(r"^test:\n((?:\t.*\n)+)", text, re.MULTILINE).group(1)
        self.assertIn("-B -m tests._runner discover -s tests -t . -v", recipe)


if __name__ == "__main__":
    unittest.main()
