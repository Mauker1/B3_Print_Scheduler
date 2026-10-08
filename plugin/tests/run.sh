#!/bin/sh
# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
# The plugin's tests, as the release pipeline runs them. b3-builder calls `sh <plugin>/tests/run.sh`
# from the repository root once every package is packed, and a non-zero exit aborts the run before
# a single release is cut. That is the only caller this file is written for: on a development
# machine run scripts/check.sh instead, which runs these same tests along with the linting, the
# type checking and the guards.
#
# It builds a throwaway virtualenv rather than reusing the shared tool venv that the gate
# provisions, because that venv lives inside the lib_bespok3d submodule and the submodule is a
# private repository. A release run checks this repo out with its own token, which cannot read it.
#
# Python 3.11 and nothing else: the printer runs 3.11, and a suite that passes on some other
# interpreter says nothing about the machine it exists to protect.
set -eu

# Importing the plugin writes __pycache__ beside its source, inside the tree the packer ships, and
# the daemon refuses a package holding a member the manifest's files[] does not list. One of these
# tests checks for exactly that, so without this line the act of testing fails the suite.
export PYTHONDONTWRITEBYTECODE=1

tests_dir="$(cd "$(dirname "$0")" && pwd)"
plugin_dir="$(dirname "$tests_dir")"

interpreter=""
for candidate in python3.11 python3 python; do
    command -v "$candidate" > /dev/null 2>&1 || continue
    "$candidate" --version 2>&1 | grep -q "^Python 3\.11\." || continue
    interpreter="$candidate"
    break
done

# The same last resort the gate uses: a standalone 3.11 in uv's cache, on a machine whose system
# Python is something else. CI has no uv and needs none, because the workflow sets 3.11 up first.
if [ -z "$interpreter" ] && command -v uv > /dev/null 2>&1; then
    uv python install 3.11 > /dev/null 2>&1 || true
    interpreter="$(uv python find 3.11 2> /dev/null || true)"
fi

if [ -z "$interpreter" ]; then
    echo "no Python 3.11 on PATH, which is the version the printer runs; refusing to test on" \
         "another interpreter" >&2
    exit 2
fi

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

"$interpreter" -m venv "$workdir/venv"
"$workdir/venv/bin/pip" install --quiet --upgrade pip
# Matched to the shared tool set in lib_bespok3d/tooling/python-tools.txt. The plugin itself has no
# dependencies at all: everything installed here is the runner.
"$workdir/venv/bin/pip" install --quiet "pytest>=8.0" "pytest-timeout>=2.3"

cd "$plugin_dir"
# A hung test fails with a stack dump at the deadlock rather than holding the runner until GitHub
# kills the job six hours later. The timeout matches the shared pytest.ini.
"$workdir/venv/bin/pytest" --rootdir . -q --timeout 60 --timeout-method thread tests
