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

.PHONY: install check app test

# Releases. The ONE version lives in pyproject.toml; scripts/release.py bumps it
# with uv and mirrors it into the plugin manifest(s) and __version__.
BUMP ?= patch
.PHONY: build release push publish

build:  ## wheel + sdist into dist/
	@uv build

release:  ## bump (BUMP=patch|minor|major) or set (VERSION=X.Y.Z), then mirror, changelog, commit, tag
	@uv run python scripts/release.py $(or $(VERSION),$(BUMP))

push:  ## push the branch and the tags to origin (release never pushes; this is the line it printed)
	@git push origin HEAD && git push origin --tags

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
