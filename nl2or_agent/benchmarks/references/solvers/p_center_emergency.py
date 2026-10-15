"""Reference solver: model built from the case IR by block_model.py."""

import json
import sys
from pathlib import Path

# <repo>/benchmarks/references/solvers/<case>.py -> <repo>
_ROOT = Path(__file__).resolve().parents[3]
if (_ROOT / 'benchmarks').is_dir():
    sys.path.insert(0, str(_ROOT))
else:
    sys.path.insert(0, 'F:\\Uni\\s\\2026_1春\\Project\\Project：OP智能体\\nl2or_agent')

from benchmarks.references.block_model import solve_ir  # noqa: E402

IR = json.loads(
    '{"problem_families": [{"id": "p_center", "name": "p_center", "confiden'
    'ce": "high", "notes": ""}], "is_hybrid": false, "hybrid_notes": "", "e'
    'ntities": {"I": {"size": 6, "ids": []}, "J": {"size": 4, "ids": []}}, '
    '"parameters": {"p": 2, "distance": [[10, 20, 30, 40], [20, 15, 25, 35]'
    ', [30, 25, 12, 28], [40, 35, 28, 18], [25, 22, 20, 15], [35, 30, 25, 2'
    '0]]}, "decision_variables": [], "objective": {"sense": "minimize", "bl'
    'ock_id": "minimize_max_distance_objective", "expression": "", "natural'
    '_language": "", "parameters": {}}, "constraint_blocks": [{"block_id": '
    '"assign_each_demand_once", "category": "assignment", "name": "需求唯一分配",'
    ' "parameters": {}, "status": "required", "natural_language": ""}, {"bl'
    'ock_id": "link_assignment_to_open", "category": "linking", "name": "分配'
    '-开设联动", "parameters": {}, "status": "required", "natural_language": ""'
    '}, {"block_id": "cardinality_open_p_facilities", "category": "cardinal'
    'ity", "name": "恰好开设 P 个设施", "parameters": {"p": 2}, "status": "require'
    'd", "natural_language": ""}, {"block_id": "max_service_distance_bound"'
    ', "category": "distance", "name": "最大服务距离上界", "parameters": {"distance'
    '": "由距离矩阵给定"}, "status": "required", "natural_language": ""}], "custom'
    '_constraints": [], "missing_data": []}'
)
DROP = []

result = solve_ir(IR, drop=tuple(DROP))
print('Objective:', result.objective)
for name, value in sorted(result.variables.items()):
    print(f'{name}: {value}')
