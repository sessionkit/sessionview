"""sessionview's test suite: stdlib only (unittest), no network, no pytest.

    make test                    the whole suite, from a checkout
    python3 -m unittest discover -s tests -t .     the same, by hand

Every test runs against THIS checkout (support.REPO) with a scratch HOME
(support.scratch_env), so it never reads or writes a real ~/.sessionkit,
any other dot-dir, or another checkout. Add a module as tests/test_<area>.py;
reuse support.run() to call a bin/ tool.
"""
