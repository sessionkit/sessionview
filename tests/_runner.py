"""`python -m unittest`, plus a per-test junit report when one is asked for.

    python3 -B -m tests._runner discover -s tests -t . -v

This runs exactly what `python3 -m unittest discover -s tests -t . -v` runs:
the same discovery, the same -v stream, the same `Ran N tests` and
`OK (skipped=N)` summary, the same exit code. It is unittest.main() with a
TextTestRunner subclass, so every unittest flag still works.

What it adds: when PYTEST_ADDOPTS carries `--junitxml=PATH` (or
`--junitxml PATH`), it also writes an xunit1 junit report to PATH, the shape
pytest writes and junit readers already parse. Unittest itself writes no
per-test report, so a tool that reads one (a check that must name each
skipped test and its reason) has nothing to read without it. Every other
option in PYTEST_ADDOPTS is ignored. With no --junitxml there, it writes
nothing, and the run is plain unittest.

The report holds one <testcase> per outcome unittest counts, so its named
skips always equal the stream's `skipped=N`:

- a test: file (repo-relative), classname (module.Class), name, time;
- a skip: <skipped message="reason">, one per skip unittest counts, including
  a skip inside a subTest;
- an expected failure: <skipped type="pytest.xfail">, as pytest writes one;
- a failure, an error, an unexpected success: <failure> or <error>;
- a subTest that fails or skips: its own case, `test_x[params]`;
- a setUpClass / setUpModule that skips or fails (unittest counts ONE skip or
  error for the whole class or module): a case named setUpClass or
  setUpModule under that class or module, never dropped;
- a module that raises SkipTest at import: a collection skip, the way pytest
  records a module skipped at collection;
- a module that fails to import: an error case under that module's file.

Stdlib only, by design: the suite has no dependencies.
"""
import os
import re
import shlex
import sys
import time
import unittest
import unittest.case
import unittest.loader
import xml.etree.ElementTree as ET

#: The variable a check tool sets to ask for a report (pytest's own).
ADDOPTS_VAR = "PYTEST_ADDOPTS"
#: The flag that names the report's path, in both of pytest's spellings.
JUNIT_FLAGS = ("--junitxml", "--junit-xml")

#: `setUpClass (tests.test_x.Class)`: unittest's name for a class- or
#: module-level fixture outcome.
_HOLDER_RE = re.compile(r"^(\w+) \((.+)\)$")
#: Characters XML 1.0 cannot carry, even escaped.
_XML_BAD_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


def junit_path(environ=None):
    """The report path PYTEST_ADDOPTS asks for, or None.

    `--junitxml=PATH` and `--junitxml PATH` both count (and pytest's
    `--junit-xml` alias); the last one wins, as in pytest. A value that does
    not split (an unclosed quote) asks for nothing."""
    environ = os.environ if environ is None else environ
    try:
        args = shlex.split(environ.get(ADDOPTS_VAR, "") or "")
    except ValueError:
        return None
    path = None
    for i, arg in enumerate(args):
        flag, eq, value = arg.partition("=")
        if flag not in JUNIT_FLAGS:
            continue
        if eq:
            path = value
        elif i + 1 < len(args):
            path = args[i + 1]
    return path or None


def _clean(text):
    """`text` as XML can carry it: a character XML 1.0 forbids becomes \\xNN."""
    return _XML_BAD_RE.sub(lambda m: "\\x%02x" % ord(m.group()), str(text))


def _module_file(module):
    """The repo-relative file of a dotted module name (`tests/test_x.py`)."""
    mod = sys.modules.get(module)
    path = getattr(mod, "__file__", None)
    if path:
        rel = os.path.relpath(os.path.abspath(path), os.getcwd())
        if not rel.startswith(os.pardir):
            return rel.replace(os.sep, "/")
    return module.replace(".", "/") + ".py"


def _split_dotted(dotted):
    """`tests.test_x.Class` -> (`tests.test_x`, `tests.test_x.Class`): the
    longest prefix that is an imported module is the module."""
    parts = dotted.split(".")
    for n in range(len(parts), 0, -1):
        if ".".join(parts[:n]) in sys.modules:
            return ".".join(parts[:n])
    return dotted


def _subtest_label(subtest):
    """A subTest's params as a pytest-style id suffix: `i=1`, `[msg] (i=1)`."""
    label = subtest._subDescription()
    if label.startswith("(") and label.endswith(")") and "(" not in label[1:-1]:
        label = label[1:-1]
    return label


def locate(test):
    """`(file, classname, name)` for anything unittest reports an outcome on.

    `classname` is the dotted module plus class (`tests.test_x.Class`); a
    module-level outcome has the bare module as its classname; a module
    skipped whole at import has an empty classname (the collection form)."""
    if isinstance(test, unittest.case._SubTest):
        file, classname, name = locate(test.test_case)
        return file, classname, "%s[%s]" % (name, _subtest_label(test))
    cls = type(test)
    if cls.__module__ == "unittest.loader" and isinstance(test, unittest.TestCase):
        # A module that failed to import (_FailedTest) or raised SkipTest at
        # import (ModuleSkipped): the method name is the module's dotted name.
        module = test._testMethodName
        if cls.__name__ == "ModuleSkipped":
            return _module_file(module), "", module
        return _module_file(module), module, module.rpartition(".")[2]
    if isinstance(test, unittest.TestCase):
        classname = "%s.%s" % (cls.__module__, cls.__qualname__)
        return _module_file(cls.__module__), classname, test._testMethodName
    # suite._ErrorHolder: `setUpClass (tests.test_x.Class)`.
    found = _HOLDER_RE.match(str(test))
    if found:
        method, parent = found.groups()
        return _module_file(_split_dotted(parent)), parent, method
    return "", "", str(test)


class _RecordingResult(unittest.TextTestResult):
    """TextTestResult, unchanged on the stream, that also records one entry
    per outcome for the report. Every hook calls the parent first."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []
        self._started = time.perf_counter()

    def _record(self, test, kind=None, message="", text=""):
        file, classname, name = locate(test)
        self.cases.append({
            "file": file, "classname": classname, "name": name,
            "time": time.perf_counter() - self._started if isinstance(
                test, (unittest.TestCase, unittest.case._SubTest)) else 0.0,
            "kind": kind, "message": message, "text": text,
        })

    @staticmethod
    def _message(err):
        exc_type, value = err[0], err[1]
        first = str(value).splitlines()[0] if str(value) else ""
        return "%s: %s" % (exc_type.__name__, first) if first else exc_type.__name__

    def startTest(self, test):
        super().startTest(test)
        self._started = time.perf_counter()

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failure", self._message(err), self.failures[-1][1])

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "error", self._message(err), self.errors[-1][1])

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "skipped", reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test, "xfail", self._message(err), self.expectedFailures[-1][1])

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, "failure", "unexpected success: the test is marked expectedFailure")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is None:
            return  # a passing subTest is part of its test's own outcome
        if issubclass(err[0], test.failureException):
            self._record(subtest, "failure", self._message(err), self.failures[-1][1])
        else:
            self._record(subtest, "error", self._message(err), self.errors[-1][1])


def build_report(cases, elapsed):
    """The xunit1 report for recorded `cases`, as an ElementTree root."""
    count = lambda kind: sum(1 for c in cases if c["kind"] == kind)  # noqa: E731
    suites = ET.Element("testsuites")
    suite = ET.SubElement(suites, "testsuite", {
        "name": "unittest", "tests": str(len(cases)),
        "failures": str(count("failure")), "errors": str(count("error")),
        "skipped": str(count("skipped") + count("xfail")),
        "time": "%.3f" % elapsed,
    })
    for c in cases:
        case = ET.SubElement(suite, "testcase", {
            "classname": _clean(c["classname"]), "name": _clean(c["name"]),
            "file": _clean(c["file"]), "time": "%.3f" % c["time"],
        })
        kind = c["kind"]
        if kind == "skipped" and not c["classname"]:
            # A whole module skipped at import: pytest's collection-skip shape.
            child = ET.SubElement(case, "skipped", {
                "type": "pytest.skip", "message": "collection skipped"})
            child.text = _clean(repr((c["file"], 0, "Skipped: " + c["message"])))
        elif kind == "skipped":
            child = ET.SubElement(case, "skipped", {
                "type": "pytest.skip", "message": _clean(c["message"])})
            child.text = _clean(c["message"])
        elif kind == "xfail":
            child = ET.SubElement(case, "skipped", {
                "type": "pytest.xfail", "message": _clean(c["message"])})
            child.text = _clean(c["text"])
        elif kind in ("failure", "error"):
            child = ET.SubElement(case, kind, {"message": _clean(c["message"])})
            child.text = _clean(c["text"])
    return suites


def write_report(path, cases, elapsed):
    """Write the report to `path` whole: a reader never sees half a file."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    ET.ElementTree(build_report(cases, elapsed)).write(
        tmp, encoding="utf-8", xml_declaration=True)
    os.replace(tmp, path)


class JUnitTestRunner(unittest.TextTestRunner):
    """TextTestRunner that writes the junit report PYTEST_ADDOPTS asks for."""

    resultclass = _RecordingResult

    def run(self, test):
        began = time.perf_counter()
        result = super().run(test)
        path = junit_path()
        if path:
            try:
                write_report(path, result.cases, time.perf_counter() - began)
            except OSError as exc:
                print("tests._runner: could not write the junit report %s: %s"
                      % (path, exc), file=sys.stderr)
        return result


def main(argv=None):
    """`python -m unittest` with the junit-writing runner; exits as it does."""
    argv = sys.argv[1:] if argv is None else argv
    unittest.main(module=None, argv=["python -m unittest"] + list(argv),
                  testRunner=JUnitTestRunner)


if __name__ == "__main__":
    main()
