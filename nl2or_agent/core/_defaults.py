"""Default data-file paths shared across core/ and tools/ modules."""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent

MODEL_BANK_PATH: Path = _PROJECT_ROOT / "data" / "model_bank" / "models.json"
BLOCKS_CATALOG_PATH: Path = _PROJECT_ROOT / "data" / "model_bank" / "constraint_blocks.json"
