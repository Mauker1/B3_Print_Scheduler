#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
# This repo's gate. Exits non-zero on any failure. Run it from anywhere; it works from its own root
# and reaches into no sibling checkout.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# lib_bespok3d is a submodule of this repo rather than a sibling checkout, so the path is local.
# This is the one line that knows where the shared tooling lives; see lib_bespok3d/tooling/README.md.
B3D_TOOLING="${B3D_TOOLING:-$REPO_ROOT/lib_bespok3d/tooling}"
if [ ! -f "$B3D_TOOLING/gate-lib.sh" ]; then
    echo "ERROR: $B3D_TOOLING/gate-lib.sh is missing. The lib_bespok3d submodule is not checked out." >&2
    echo "       git submodule sync --recursive && git submodule update --init --recursive" >&2
    exit 2
fi
# shellcheck source=/dev/null
. "$B3D_TOOLING/gate-lib.sh"

cd "$REPO_ROOT" || exit 1

PLUGIN_DIR="$REPO_ROOT/plugin"
# The package lives under files/lib because that is where it lands on the printer, so mypy needs to
# be told where to resolve `print_scheduler` from.
export MYPYPATH="$PLUGIN_DIR/files/lib"

echo ""
echo "print-scheduler gate"

b3d_python_tools

# Scoped to the plugin, never to the repo root: at the root these would walk the submodule's own
# tree, which gates itself and is not ours to rewrite.
run_check "ruff"   ruff_in_dir "$PLUGIN_DIR" files tests
run_check "mypy"   mypy_in_dir "$PLUGIN_DIR" files/lib/print_scheduler tests
run_check "pytest" pytest_in_dir "$PLUGIN_DIR" tests
# The browser harness is ours too, so it is linted. It is not type checked or run here: it
# imports playwright, which is not in the shared tool venv and is not a dependency of this
# repo. CONTRIBUTING.md says when to run it.
run_check "ruff (scripts)" ruff_in_dir "$REPO_ROOT" scripts

release_trigger_check "$REPO_ROOT"
manifest_origin_check "$REPO_ROOT"
workflow_pinning_check "$REPO_ROOT"

# --suffix .conf so the nginx location file is covered; the guard's defaults stop at the formats
# most repos author. notes/ and _trash/ are deliberately absent: neither is committed or shipped.
em_dash_check \
    "$PLUGIN_DIR" \
    "$REPO_ROOT/scripts" \
    "$REPO_ROOT/README.md" \
    "$REPO_ROOT/CLAUDE.md" \
    "$REPO_ROOT/CONTRIBUTING.md" \
    "$REPO_ROOT/AGENTS.md" \
    "$REPO_ROOT/SECURITY.md" \
    "$REPO_ROOT/CHANGELOG-alpha.md" \
    "$REPO_ROOT/.github" \
    --suffix .conf \
    --suffix .yml

shellcheck_repo "$REPO_ROOT/scripts" "$PLUGIN_DIR"

gate_summary || exit 1
