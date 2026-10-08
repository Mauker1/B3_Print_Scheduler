#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entry point, and nothing else.

The manifest names this file. That name is a legal program and an illegal module, so nothing can
import it, which is why it holds no logic: it puts the plugin's own lib directory on the path and
calls main. Everything worth testing lives in the print_scheduler package beside it.
"""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_LIB = Path(__file__).resolve().parent.parent / "lib"

# append, never insert. At the front this shadows installed packages with whatever is unpacked here,
# silently on the printer's architecture and loudly everywhere else, which makes a test suite
# platform dependent in a way that takes a long afternoon to find.
if str(PLUGIN_LIB) not in sys.path:
    sys.path.append(str(PLUGIN_LIB))

from print_scheduler.cli import main  # noqa: E402  the path must be set up before this import

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
