"""Reference solver: model built from the case IR by block_model.py."""

import json
import sys
from pathlib import Path

_REPO_MARKER = Path('core') / 'block_model.py'


def _repo_root() -> Path:
    for base in Path(__file__).resolve().parents:
        if (base / _REPO_MARKER).is_file():
            return base
    return Path('F:\\Uni\\s\\2026_1春\\Project\\Project：OP智能体\\nl2or_agent')

sys.path.insert(0, str(_repo_root()))

from core.block_model import solve_ir  # noqa: E402

IR = json.loads(
    '{"problem_families": [{"id": "maximum_covering", "name": "maximum_cove'
    'ring", "confidence": "high", "notes": ""}], "is_hybrid": false, "hybri'
    'd_notes": "", "entities": {"I": {"size": 6, "ids": []}, "J": {"size": '
    '4, "ids": []}}, "parameters": {"p": 2, "demand": [10, 8, 12, 6, 9, 5],'
    ' "coverage_matrix": [[1, 0, 1, 0], [1, 1, 0, 0], [0, 1, 1, 0], [0, 0, '
    '1, 1], [0, 0, 0, 1], [1, 0, 0, 1]]}, "decision_variables": [], "object'
    'ive": {"sense": "maximize", "block_id": "covered_demand_objective", "e'
    'xpression": "", "natural_language": "", "parameters": {}}, "constraint'
    '_blocks": [{"block_id": "demand_coverage_activation", "category": "cov'
    'erage", "name": "需求覆盖状态联动", "parameters": {"coverage_matrix": "由覆盖矩阵给定'
    '"}, "status": "required", "natural_language": ""}, {"block_id": "cardi'
    'nality_open_p_facilities", "category": "cardinality", "name": "恰好开设 P '
    '个设施", "parameters": {"p": 2}, "status": "required", "natural_language"'
    ': ""}], "custom_constraints": [], "missing_data": []}'
)
DROP = []

result = solve_ir(IR, drop=tuple(DROP))
print('Objective:', result.objective)
for name, value in sorted(result.variables.items()):
    print(f'{name}: {value}')
