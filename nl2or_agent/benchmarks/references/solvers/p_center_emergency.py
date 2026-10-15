"""Reference solver: p_center_emergency. Prints the optimal objective."""

import pulp

DIST = [
    [10, 20, 30, 40],
    [20, 15, 25, 35],
    [30, 25, 12, 28],
    [40, 35, 28, 18],
    [25, 22, 20, 15],
    [35, 30, 25, 20],
]
P = 2
n_i, n_j = 6, 4

prob = pulp.LpProblem("p_center", pulp.LpMinimize)
y = pulp.LpVariable.dicts("y", range(n_j), cat=pulp.LpBinary)
x = pulp.LpVariable.dicts("x", (range(n_i), range(n_j)), cat=pulp.LpBinary)
w = pulp.LpVariable("w", lowBound=0)
prob += w
for i in range(n_i):
    prob += pulp.lpSum(x[i][j] for j in range(n_j)) == 1
for i in range(n_i):
    for j in range(n_j):
        prob += x[i][j] <= y[j]
        prob += DIST[i][j] * x[i][j] <= w
prob += pulp.lpSum(y[j] for j in range(n_j)) == P
prob.solve(pulp.PULP_CBC_CMD(msg=False))
value = pulp.value(prob.objective)
print("Objective:", round(value) if isinstance(value, (int, float)) else 0)
