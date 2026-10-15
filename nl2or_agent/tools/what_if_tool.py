"""Tool: 在同一份已解析模型上比较多组参数情景。"""

from __future__ import annotations

import json
from pathlib import Path

from hamlet.core.tools import Tool

from core.what_if import describe_model, render_comparison, run_scenarios
from utils.session import get_session


class WhatIfTool(Tool):
    """Compare parameter scenarios on the session's model of record."""

    name = "what_if"
    description = (
        "Compare parameter scenarios on the model already built by validate_problem_ir: "
        "each scenario gives parameter overrides, every scenario is solved and the objective "
        "value and decisions are compared against the baseline. "
        "Input: a JSON list of scenarios, each {id, overrides: [{path: 'parameters.<key>', value}]}. "
        "Use it for comparison questions such as 'what if p becomes 4' or 'what if capacity drops'. "
        "Adding or removing constraints is re-modeling, not a scenario."
    )
    inputs = {
        "scenarios_json": {
            "type": "string",
            "description": (
                "List of scenarios (or its JSON string), e.g. "
                '[{"id": "p=2", "overrides": [{"path": "parameters.p", "value": 2}]}]'
            ),
        }
    }
    output_type = "string"

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        super().__init__()
        # None 时读当前会话的模型产物（生产路径），显式给出时读该目录（测试/评测）
        self._workspace: Path | None = Path(workspace_dir) if workspace_dir else None

    def forward(self, scenarios_json: str | list) -> str:
        if isinstance(scenarios_json, str):
            try:
                scenarios = json.loads(scenarios_json)
            except json.JSONDecodeError as exc:
                return f"无法解析 scenarios_json：{exc}"
        elif isinstance(scenarios_json, list):
            # 模型在代码块里直接传 Python 列表是正常写法，与 JSON 字符串同等对待
            scenarios = scenarios_json
        else:
            return f"scenarios_json 必须是场景列表或它的 JSON 字符串，收到 {type(scenarios_json).__name__}"
        if not isinstance(scenarios, list):
            return "scenarios_json 必须是一个场景列表"

        model = self._load_model()
        if model is None:
            return "还没有模型：先调用 validate_problem_ir 建立模型，再比较情景。"
        ir = model.get("ir") or {}

        try:
            comparison = run_scenarios(ir, scenarios)
        except ValueError as exc:
            return f"无法执行情景对比：{exc}"

        return "\n\n".join([describe_model(ir), render_comparison(comparison)])

    def _load_model(self) -> dict | None:
        if self._workspace is not None:
            path = self._workspace / "model.json"
            if not path.is_file():
                return None
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        session = get_session()
        return session.load_model()
