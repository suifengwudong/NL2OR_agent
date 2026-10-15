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
    '{"problem_families": [{"id": "set_covering", "name": "set_covering", "'
    'confidence": "high", "notes": ""}], "is_hybrid": false, "hybrid_notes"'
    ': "", "entities": {"I": {"size": 6, "ids": []}, "J": {"size": 5, "ids"'
    ': []}}, "parameters": {"fixed_cost": [4, 3, 5, 2, 4], "coverage_matrix'
    '": [[1, 0, 1, 0, 0], [1, 1, 0, 0, 0], [0, 1, 1, 1, 0], [0, 0, 1, 1, 1]'
    ', [0, 0, 0, 1, 1], [1, 0, 0, 0, 1]]}, "decision_variables": [], "objec'
    'tive": {"sense": "minimize", "block_id": "facility_opening_cost_object'
    'ive", "expression": "", "natural_language": "", "parameters": {}}, "co'
    'nstraint_blocks": [{"block_id": "cover_each_demand_at_least_once", "ca'
    'tegory": "coverage", "name": "需求点至少覆盖一次", "parameters": {"coverage_mat'
    'rix": "由覆盖矩阵给定"}, "status": "required", "natural_language": ""}], "cus'
    'tom_constraints": [], "missing_data": []}'
)
DROP = []

result = solve_ir(IR, drop=tuple(DROP))
print('Objective:', result.objective)
for name, value in sorted(result.variables.items()):
    print(f'{name}: {value}')
