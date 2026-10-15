"""Reference solver: maximum_covering_cities. Prints the optimal objective."""

import pulp

DEMAND = [10, 8, 12, 6, 9, 5]
COVER = [
    [1, 0, 1, 0],
    [1, 1, 0, 0],
    [0, 1, 1, 0],
    [0, 0, 1, 1],
    [0, 0, 0, 1],
    [1, 0, 0, 1],
]
P = 2
n_d, n_j = 6, 4

prob = pulp.LpProblem("max_covering", pulp.LpMaximize)
y = pulp.LpVariable.dicts("y", range(n_j), cat=pulp.LpBinary)
z = pulp.LpVariable.dicts("z", range(n_d), cat=pulp.LpBinary)
prob += pulp.lpSum(DEMAND[i] * z[i] for i in range(n_d))
for i in range(n_d):
    prob += z[i] <= pulp.lpSum(COVER[i][j] * y[j] for j in range(n_j))
prob += pulp.lpSum(y[j] for j in range(n_j)) == P
prob.solve(pulp.PULP_CBC_CMD(msg=False))
value = pulp.value(prob.objective)
print("Objective:", round(value) if isinstance(value, (int, float)) else 0)
