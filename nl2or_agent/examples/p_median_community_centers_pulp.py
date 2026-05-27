"""P-Median 社区服务中心 — PuLP 参考解（供 run_solver 或本地验证）."""

import pulp

POP = [80, 120, 100, 90, 110, 70]
DIST = [
    [4, 6, 9, 7, 8],
    [5, 3, 8, 6, 7],
    [9, 7, 4, 5, 6],
    [8, 6, 5, 3, 4],
    [6, 5, 7, 4, 3],
    [7, 8, 6, 5, 4],
]
FAC = ["A", "B", "C", "D", "E"]
P = 3
n_i, n_j = 6, 5

prob = pulp.LpProblem("P_Median", pulp.LpMinimize)
y = pulp.LpVariable.dicts("y", range(n_j), cat=pulp.LpBinary)
x = pulp.LpVariable.dicts("x", (range(n_i), range(n_j)), cat=pulp.LpBinary)
prob += pulp.lpSum(POP[i] * DIST[i][j] * x[i][j] for i in range(n_i) for j in range(n_j))
for i in range(n_i):
    prob += pulp.lpSum(x[i][j] for j in range(n_j)) == 1
for i in range(n_i):
    for j in range(n_j):
        prob += x[i][j] <= y[j]
prob += pulp.lpSum(y[j] for j in range(n_j)) == P
prob.solve(pulp.PULP_CBC_CMD(msg=False))
print("Objective:", pulp.value(prob.objective))
print("Open:", [FAC[j] for j in range(n_j) if pulp.value(y[j]) > 0.5])
for i in range(n_i):
    j = next(j for j in range(n_j) if pulp.value(x[i][j]) > 0.5)
    print(f"居民区{i+1} -> {FAC[j]}")
