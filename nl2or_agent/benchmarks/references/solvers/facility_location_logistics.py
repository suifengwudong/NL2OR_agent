"""Reference solver: facility_location_logistics (UFLP). Prints the optimal objective."""

import pulp

FIXED = [100, 80, 120]
SERVICE = [
    [15, 20, 18],
    [22, 12, 25],
    [18, 24, 14],
    [30, 16, 20],
    [12, 22, 19],
]
n_i, n_j = 5, 3

prob = pulp.LpProblem("uflp", pulp.LpMinimize)
y = pulp.LpVariable.dicts("y", range(n_j), cat=pulp.LpBinary)
x = pulp.LpVariable.dicts("x", (range(n_i), range(n_j)), cat=pulp.LpBinary)
prob += pulp.lpSum(FIXED[j] * y[j] for j in range(n_j)) + pulp.lpSum(
    SERVICE[i][j] * x[i][j] for i in range(n_i) for j in range(n_j)
)
for i in range(n_i):
    prob += pulp.lpSum(x[i][j] for j in range(n_j)) == 1
for i in range(n_i):
    for j in range(n_j):
        prob += x[i][j] <= y[j]
prob.solve(pulp.PULP_CBC_CMD(msg=False))
value = pulp.value(prob.objective)
print("Objective:", round(value) if isinstance(value, (int, float)) else 0)
