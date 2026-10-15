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
    '{"problem_families": [{"id": "p_median", "name": "p_median", "confiden'
    'ce": "high", "notes": ""}], "is_hybrid": false, "hybrid_notes": "", "e'
    'ntities": {"I": {"size": 6, "ids": []}, "J": {"size": 5, "ids": ["A", '
    '"B", "C", "D", "E"]}}, "parameters": {"p": 3, "demand": [80, 120, 100,'
    ' 90, 110, 70], "distance": [[4, 6, 9, 7, 8], [5, 3, 8, 6, 7], [9, 7, 4'
    ', 5, 6], [8, 6, 5, 3, 4], [6, 5, 7, 4, 3], [7, 8, 6, 5, 4]]}, "decisio'
    'n_variables": [], "objective": {"sense": "minimize", "block_id": "weig'
    'hted_service_distance_objective", "expression": "minimize_total_weight'
    'ed_distance", "natural_language": "minimize_total_weighted_distance", '
    '"parameters": {}}, "constraint_blocks": [{"block_id": "assign_each_dem'
    'and_once", "category": "assignment", "name": "需求唯一分配", "parameters": {'
    '}, "status": "required", "natural_language": ""}, {"block_id": "link_a'
    'ssignment_to_open", "category": "linking", "name": "分配-开设联动", "paramet'
    'ers": {}, "status": "required", "natural_language": ""}, {"block_id": '
    '"cardinality_open_p_facilities", "category": "cardinality", "name": "恰'
    '好开设 P 个设施", "parameters": {"p": 3}, "status": "required", "natural_lan'
    'guage": ""}], "custom_constraints": [], "missing_data": []}'
)
DROP = []

result = solve_ir(IR, drop=tuple(DROP))
print('Objective:', result.objective)
for name, value in sorted(result.variables.items()):
    print(f'{name}: {value}')
