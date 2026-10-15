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
    '{"problem_families": [{"id": "knapsack", "name": "knapsack", "confiden'
    'ce": "high", "notes": ""}], "is_hybrid": false, "hybrid_notes": "", "e'
    'ntities": {"I": {"size": 3, "ids": []}}, "parameters": {"value": [60, '
    '100, 120], "weight": [10, 20, 30], "capacity": 50}, "decision_variable'
    's": [], "objective": {"sense": "maximize", "block_id": "total_value_ob'
    'jective", "expression": "", "natural_language": "", "parameters": {}},'
    ' "constraint_blocks": [{"block_id": "knapsack_capacity", "category": "'
    'capacity", "name": "背包容量约束", "parameters": {"capacity": 50}, "status":'
    ' "required", "natural_language": ""}], "custom_constraints": [], "miss'
    'ing_data": []}'
)
DROP = []

result = solve_ir(IR, drop=tuple(DROP))
print('Objective:', result.objective)
for name, value in sorted(result.variables.items()):
    print(f'{name}: {value}')
