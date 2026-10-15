"""Reference solver: set_covering_emergency. Prints the optimal objective."""

import pulp

COVER = [
    [1, 0, 1, 0, 0],
    [1, 1, 0, 0, 0],
    [0, 1, 1, 1, 0],
    [0, 0, 1, 1, 1],
    [0, 0, 0, 1, 1],
    [1, 0, 0, 0, 1],
]
FIXED = [4, 3, 5, 2, 4]
n_d, n_j = 6, 5

prob = pulp.LpProblem("set_covering", pulp.LpMinimize)
y = pulp.LpVariable.dicts("y", range(n_j), cat=pulp.LpBinary)
prob += pulp.lpSum(FIXED[j] * y[j] for j in range(n_j))
for i in range(n_d):
    prob += pulp.lpSum(COVER[i][j] * y[j] for j in range(n_j)) >= 1
prob.solve(pulp.PULP_CBC_CMD(msg=False))
value = pulp.value(prob.objective)
print("Objective:", round(value) if isinstance(value, (int, float)) else 0)
