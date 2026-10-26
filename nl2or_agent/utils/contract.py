"""The solver output contract, shared by the tool and the benchmark."""

from __future__ import annotations

import re

OBJECTIVE_LINE_RE = re.compile(r"Objective:\s*(-?\d+(?:\.\d+)?)")
