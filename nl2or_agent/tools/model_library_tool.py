"""Tools over the model bank: bounded candidate search and template detail."""

from __future__ import annotations

from hamlet.core.tools import Tool

from core.model_library import describe_model as _describe_model
from core.model_library import search_entries as _search_entries


class SearchModelLibraryTool(Tool):
    """Search the model bank for candidate templates and composable blocks."""

    name = "search_model_library"
    description = (
        "Search the model bank (models and composable constraint blocks) for candidates. "
        "Returns a compact table: id, name, one-line description — no formulas. "
        "Call it in Step 1 with keywords from the user's problem (Chinese works; "
        "several keywords narrow the result) before building the Problem IR. "
        "Omit keywords to list every model. Follow up with describe_model(id) on the "
        "chosen template. Input: keywords (a string, or None/'' for the full model list)."
    )
    inputs = {
        "keywords": {
            "type": "string",
            "nullable": True,
            "description": (
                "Space- or 、-separated keywords from the problem, e.g. '选址 容量' "
                "or 'knapsack'; empty means list all models."
            ),
        },
    }
    output_type = "string"

    def forward(self, keywords: str | None = None) -> str:
        return _search_entries(keywords)


class DescribeModelTool(Tool):
    """Show one model template's required blocks, data, objective and variables."""

    name = "describe_model"
    description = (
        "Return one model template from the bank: its required constraint blocks with "
        "required parameters, its objective block and sense, its data parameters and "
        "decision variables — enough to build the Problem IR. Only required blocks are "
        "listed; formulas are rendered later by model_math. "
        "Input: model_id exactly as returned by search_model_library."
    )
    inputs = {
        "model_id": {
            "type": "string",
            "description": "Model id from search_model_library, e.g. 'facility_location'.",
        },
    }
    output_type = "string"

    def forward(self, model_id: str) -> str:
        return _describe_model(str(model_id))
