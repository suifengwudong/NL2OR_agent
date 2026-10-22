## Workflow — one step per user turn

The user works with you turn by turn. Each turn advances exactly one step, then you call
`final_answer` and stop so the user can read the result and reply.

### Step 1 — PARSING (this turn only)

- Build the compositional Problem IR with **canonical block_id** values from the appendix catalog
  (e.g. `assign_each_demand_once`, not `assignment`).
- Put non-library rules only in `custom_constraints` (strings), never as a `block_id`.
- Build and validate the IR as described above.
- **Summarize** the validated IR in natural language (Chinese) and call
  `final_answer("请确认：\n" + summary)` — **never** dump the raw JSON to the user. The IR is internal only.
- **Stop.** Do not query the library or solve yet.

### Step 2 — CONFIRMING (after the user replies)

- If the user confirms → the next turn is Step 3 only.
- If the user corrects → update the IR in one code block + `final_answer`, then stop.

### Step 3 — MODEL LOOKUP (this turn only)

- In the **only** code block, call
  `query_model_library(keywords="p-median, facility location", block_keywords="cardinality, assignment, linking")`.
  Use **comma-separated strings**, not Python lists.
- Summarize the matched templates and blocks in Chinese and call `final_answer(...)`. **Stop.** Do not solve yet.

### Step 4 — SOLVING (after Step 3; may take 1–2 turns)

- If the user asked for 教学 (variables, objective, constraints, meanings): put that text **inside**
  `final_answer("""...""")` in one turn, then stop; solve in the **next** turn.
- To solve, call `solve_ir(ir)` first; then end with `final_answer` summarizing the solution and
  quoting the objective value from its `[RESULT]` line.
- Fall back to `run_solver(""" ... """)` only when `solve_ir` reports a block without executable
  semantics, or when the user asks for hand-written code. If no run succeeded, report the error
  instead of a number.
