"""Default data-file paths shared across core/ and tools/ modules."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

MODEL_BANK_PATH: Path = PROJECT_ROOT / "data" / "model_bank" / "models.json"
BLOCKS_CATALOG_PATH: Path = PROJECT_ROOT / "data" / "model_bank" / "constraint_blocks.json"
WHAT_IF_MANUAL_PATH: Path = PROJECT_ROOT / "data" / "model_bank" / "what_if_manual.json"
