"""Reference solver: knapsack_gadget. Prints the optimal objective."""

import pulp

VALUES = [60, 100, 120]
WEIGHTS = [10, 20, 30]
CAPACITY = 50
n = 3

prob = pulp.LpProblem("knapsack", pulp.LpMaximize)
x = pulp.LpVariable.dicts("x", range(n), cat=pulp.LpBinary)
prob += pulp.lpSum(VALUES[i] * x[i] for i in range(n))
prob += pulp.lpSum(WEIGHTS[i] * x[i] for i in range(n)) <= CAPACITY
prob.solve(pulp.PULP_CBC_CMD(msg=False))
value = pulp.value(prob.objective)
print("Objective:", round(value) if isinstance(value, (int, float)) else 0)
