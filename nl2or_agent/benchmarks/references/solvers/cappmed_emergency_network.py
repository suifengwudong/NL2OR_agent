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
    '{"problem_families": [{"id": "capacitated_p_median", "name": "capacita'
    'ted_p_median", "confidence": "high", "notes": ""}], "is_hybrid": false'
    ', "hybrid_notes": "", "entities": {"I": {"size": 12, "ids": []}, "J": '
    '{"size": 8, "ids": ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]}},'
    ' "parameters": {"p": 3, "demand": [14, 9, 11, 7, 16, 5, 12, 8, 13, 6, '
    '10, 4], "distance": [[2, 2, 12, 8, 13, 8, 18, 18], [2, 6, 8, 4, 9, 12,'
    ' 14, 14], [8, 8, 2, 6, 5, 14, 8, 8], [5, 3, 11, 3, 8, 5, 13, 13], [8, '
    '8, 6, 2, 3, 10, 8, 8], [8, 4, 14, 6, 7, 2, 12, 12], [8, 8, 10, 2, 3, 6'
    ', 8, 8], [13, 13, 5, 7, 2, 11, 3, 5], [8, 8, 14, 6, 7, 2, 8, 8], [13, '
    '13, 9, 7, 2, 7, 3, 3], [11, 9, 17, 9, 10, 3, 11, 7], [13, 13, 13, 7, 6'
    ', 7, 7, 3]], "facility_capacity": [40, 40, 40, 40, 40, 40, 40, 40], "f'
    'orced_open": ["F7"], "forced_closed": ["F1"]}, "decision_variables": ['
    '], "objective": {"sense": "minimize", "block_id": "total_service_dista'
    'nce_objective", "expression": "", "natural_language": "", "parameters"'
    ': {}}, "constraint_blocks": [{"block_id": "assign_each_demand_once", "'
    'category": "assignment", "name": "需求唯一分配", "parameters": {}, "status":'
    ' "required", "natural_language": ""}, {"block_id": "link_assignment_to'
    '_open", "category": "linking", "name": "分配-开设联动", "parameters": {}, "s'
    'tatus": "required", "natural_language": ""}, {"block_id": "cardinality'
    '_open_p_facilities", "category": "cardinality", "name": "恰好开设 P 个设施", '
    '"parameters": {"p": 3}, "status": "required", "natural_language": ""},'
    ' {"block_id": "facility_capacity", "category": "capacity", "name": "设施'
    '容量约束", "parameters": {"facility_capacity": [40, 40, 40, 40, 40, 40, 40'
    ', 40], "demand": [14, 9, 11, 7, 16, 5, 12, 8, 13, 6, 10, 4]}, "status"'
    ': "required", "natural_language": ""}, {"block_id": "force_facility_op'
    'en", "category": "forcing", "name": "强制开设设施", "parameters": {"forced_o'
    'pen": ["F7"]}, "status": "user_specified", "natural_language": ""}, {"'
    'block_id": "force_facility_closed", "category": "forcing", "name": "强制'
    '不开设设施", "parameters": {"forced_closed": ["F1"]}, "status": "user_speci'
    'fied", "natural_language": ""}], "custom_constraints": [], "missing_da'
    'ta": []}'
)
DROP = []

result = solve_ir(IR, drop=tuple(DROP))
print('Objective:', result.objective)
for name, value in sorted(result.variables.items()):
    print(f'{name}: {value}')
