"""Tool for querying the OR model library."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from hamlet.core.tools import Tool


_DEFAULT_BANK_PATH = Path(__file__).parent.parent / "data" / "model_bank" / "models.json"


class QueryModelLibraryTool(Tool):
    """Search the model bank for OR problem templates that match user-provided keywords.

    Returns a JSON string describing matching model templates, including their
    variable definitions, objective, constraints, and a ready-to-adapt code snippet.
    """

    name = "query_model_library"
    description = (
        "Search the Operations Research model library for templates matching the given "
        "problem type or keywords. "
        "Input: a comma-separated list of keywords (e.g. 'transportation, supply, demand'). "
        "Output: JSON string listing matching model templates with descriptions and code scaffolds."
    )
    inputs = {
        "keywords": {
            "type": "string",
            "description": "Comma-separated keywords describing the OR problem type, e.g. 'knapsack, binary, capacity'.",
        }
    }
    output_type = "string"

    def __init__(self, bank_path: str | Path | None = None) -> None:
        super().__init__()
        self._bank_path = Path(bank_path) if bank_path else _DEFAULT_BANK_PATH

    def forward(self, keywords: str) -> str:  # noqa: D102
        """Search model bank by keyword matching."""
        with open(self._bank_path, encoding="utf-8") as f:
            bank: dict[str, Any] = json.load(f)

        keyword_list = [kw.strip().lower() for kw in keywords.split(",") if kw.strip()]
        matches: list[dict] = []

        for model in bank.get("models", []):
            model_keywords = [k.lower() for k in model.get("keywords", [])]
            score = sum(
                1
                for kw in keyword_list
                if any(kw in mk for mk in model_keywords)
                or any(mk in kw for mk in model_keywords)
            )
            if score > 0:
                matches.append({"score": score, "model": model})

        matches.sort(key=lambda x: x["score"], reverse=True)
        results = [item["model"] for item in matches[:3]]

        if not results:
            return json.dumps(
                {"message": "No matching templates found. Proceed with a custom formulation."},
                ensure_ascii=False,
                indent=2,
            )

        # Return only the informative fields, omitting raw template_code for brevity
        compact = [
            {
                "id": m["id"],
                "name": m["name"],
                "type": m["type"],
                "description": m["description"],
                "variables": m["variables"],
                "objective": m["objective"],
                "constraints": m["constraints"],
                "solver_hint": m["solver_hint"],
                "template_code": m["template_code"],
            }
            for m in results
        ]
        return json.dumps(compact, ensure_ascii=False, indent=2)
