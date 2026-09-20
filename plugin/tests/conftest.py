# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test setup.

The plugin's package lives under `files/lib` because that is where it has to land on the printer,
inside the placed tree. pytest would not find it on its own, so it goes on the path here. Appended,
never inserted, for the reason spelled out in the entry point.
"""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_LIB = PLUGIN_ROOT / "files" / "lib"

if str(PLUGIN_LIB) not in sys.path:
    sys.path.append(str(PLUGIN_LIB))
