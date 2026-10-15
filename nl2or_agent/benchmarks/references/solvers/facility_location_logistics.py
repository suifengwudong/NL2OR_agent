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
    '{"problem_families": [{"id": "facility_location", "name": "facility_lo'
    'cation", "confidence": "high", "notes": ""}], "is_hybrid": false, "hyb'
    'rid_notes": "", "entities": {"I": {"size": 5, "ids": []}, "J": {"size"'
    ': 3, "ids": []}}, "parameters": {"fixed_cost": [100, 80, 120], "servic'
    'e_cost": [[15, 20, 18], [22, 12, 25], [18, 24, 14], [30, 16, 20], [12,'
    ' 22, 19]]}, "decision_variables": [], "objective": {"sense": "minimize'
    '", "block_id": "fixed_plus_service_cost_objective", "expression": "", '
    '"natural_language": "", "parameters": {}}, "constraint_blocks": [{"blo'
    'ck_id": "assign_each_demand_once", "category": "assignment", "name": "'
    '需求唯一分配", "parameters": {}, "status": "required", "natural_language": "'
    '"}, {"block_id": "link_assignment_to_open", "category": "linking", "na'
    'me": "分配-开设联动", "parameters": {}, "status": "required", "natural_langu'
    'age": ""}], "custom_constraints": [], "missing_data": []}'
)
DROP = []

result = solve_ir(IR, drop=tuple(DROP))
print('Objective:', result.objective)
for name, value in sorted(result.variables.items()):
    print(f'{name}: {value}')
