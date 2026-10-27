# The default goal is help, never install. A bare `make`, `make -s` or `make -p`
# (which prints make's database AND builds the default goal) must not act. When
# install was the first target, a `make -s -f Makefile -p` run in a task
# worktree to read one variable re-pointed a whole machine's ~/.local/bin into
# that worktree. Installing is always named: make install.
.DEFAULT_GOAL := help

help:  ## list the targets; changes nothing
	@echo "make install   link the bin/ tools into ~/.local/bin (or \$$PREFIX/bin), then check requirements"
	@echo "make check     check requirements only; change nothing"
	@echo "make app       build and install the macOS Dock app"
	@echo "make test      run the suite"
	@echo "make build | release | changelog | push | publish | scan   releases (see the Makefile)"

install:
	@bin/sessionview-install

check:
	@bin/sessionview-install --check

app:
	@bin/sessionview-app-install

# The suite is stdlib unittest (tests/). PYTHON is found as lib/python.sh finds
# the tools' Python: python3.14 ... python3.11, then bare python3 last, the first
# that is >= 3.11 (a stock macOS puts /usr/bin/python3, 3.9, first on PATH, and
# a bare python3 may be newer than the 3.14 ceiling). So the suite runs on the
# Python the tools run on; tests/test_python_probe.py pins the two lists equal.
# `make test PYTHON=/path/to/python3` overrides.
PYTHON ?= $(shell for p in python3.14 python3.13 python3.12 python3.11 python3; do \
	command -v $$p >/dev/null 2>&1 && $$p -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null \
	&& { command -v $$p; break; }; done)

test:
	@if [ -z "$(PYTHON)" ]; then echo "make test: no python3 >= 3.11 on PATH (brew install python@3.14, or: uv python install 3.14)" >&2; exit 1; fi
	@echo "make test: $$($(PYTHON) -c 'import sys; print(sys.executable, sys.version.split()[0])')"
	@$(PYTHON) -B -m unittest discover -s tests -t . -v

.PHONY: help install check app test

# Releases. The ONE version lives in pyproject.toml; scripts/release.py bumps it
# with uv and mirrors it into the plugin manifest(s) and __version__.
BUMP ?= patch
.PHONY: build release changelog push publish

build:  ## wheel + sdist into dist/
	@uv build

# release.py is stdlib-only, so python3 runs it: a plain `uv run` would re-lock
# the project before the script starts.
release:  ## bump (BUMP=patch|minor|major) or set (VERSION=X.Y.Z), then mirror, changelog, commit, tag
	@python3 scripts/release.py $(or $(VERSION),$(BUMP))

# The pending entries live in changelog.d/, one file each; the release collects
# them into CHANGELOG.md. python3, not uv run, for the same reason as release.
changelog:  ## print [Unreleased] as the next release will write it, changelog.d/ collated in; writes nothing
	@python3 scripts/release.py --preview

# Push the branch by name, then the ONE release tag by its full refname. Never a
# push of all tags: that sends every local tag (fallback/*, export/*, ready/*).
# The version is pyproject.toml's, read the way scripts/release.py reads it (a
# read, which never locks). A detached HEAD, an unreadable version or a missing
# tag is refused before anything is pushed, the branch included.
push:  ## push the branch, then the ONE release tag refs/tags/vX.Y.Z by name (pyproject's version); refuses if that tag is not here
	@branch="$$(git symbolic-ref --short -q HEAD)" && [ -n "$$branch" ] || { echo "push: HEAD is detached - check out the release branch; nothing pushed" >&2; exit 1; }; \
	version="$$(uv version --short)" && [ -n "$$version" ] || { echo "push: could not read the version from pyproject.toml (uv version --short) - nothing pushed" >&2; exit 1; }; \
	tag="v$$version"; \
	git rev-parse -q --verify "refs/tags/$$tag" >/dev/null || { echo "push: tag $$tag is not in this repository - run 'make release' first; nothing pushed" >&2; exit 1; }; \
	git push origin "$$branch" && git push origin "refs/tags/$$tag"

# THE TOKEN NEVER TOUCHES A COMMAND LINE. argv is readable by every process
# on the machine (`ps`); a child's environment only by its own user. So the
# token reaches uv as UV_PUBLISH_TOKEN in uv's environment, from one
# `pass show` (one touch), and what `ps` shows is `uv publish dist/...`.
# The process list never includes the password. PYPI_TOKEN_PASS_PATH names the pass entry, e.g.
# pypi/token; set it in your shell profile.
publish: build  ## upload THIS version's wheel + sdist to PyPI; token via $$PYPI_TOKEN_PASS_PATH (pass) or $$UV_PUBLISH_TOKEN, never on a command line
	@dist="dist/$$(echo 'sessionview' | tr '-' '_')-$$(uv version --short)"; \
	if [ -n "$$UV_PUBLISH_TOKEN" ]; then uv publish "$$dist"*; \
	elif [ -n "$$PYPI_TOKEN_PASS_PATH" ]; then UV_PUBLISH_TOKEN="$$(pass show "$$PYPI_TOKEN_PASS_PATH" | head -n1)" uv publish "$$dist"*; \
	else echo "publish: set PYPI_TOKEN_PASS_PATH to the pass entry holding your PyPI token (or UV_PUBLISH_TOKEN); the token is never put on a command line" >&2; exit 1; fi

# The pre-publish scrub check. The scanner and its word list are PRIVATE and never
# live in this repo: SESSIONKIT_SCAN names the release-scan tool (it finds its list,
# or takes SESSIONKIT_SCRUB_RULES). Exits non-zero on any P0 term in HEAD's tree.
.PHONY: scan scrub
scan:  ## scrub check: HEAD's tree against the private word list; fails on any P0 term
	@[ -n "$$SESSIONKIT_SCAN" ] || { echo "scan: set SESSIONKIT_SCAN to the release-scan tool" >&2; exit 2; }
	@"$$SESSIONKIT_SCAN" --here --fail-on P0

scrub: scan  ## the same check, by its other name
