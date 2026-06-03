# 008 — `ir_validator.py` 薄封装可合并

**Labels:** `refactor`, `medium-priority`
**Priority:** 🟡 Medium
**Status:** ✅ Won't Fix — 2026-05-27 保持独立

## 问题描述

`core/ir_validator.py` 仅 40 行，本质上是对 `normalize_problem_ir()` 结果的薄封装：

```python
def validate_problem_ir(ir, ...):
    normalized, errors, warnings = normalize_problem_ir(...)
    catalog = load_block_catalog(...)
    # 对每个 constraint block 检查 required params
    return {"valid": len(errors) == 0, ...}
```

## 决策：保持独立

分析后决定**不合并**，理由：

1. `validate_problem_ir` 是 **Tool-facing API**（被 `ValidateProblemIrTool` 直接调用）
2. 它返回的 `{"valid": ..., "normalized_ir": ..., ...}` 与 `normalize_problem_ir` 返回的 tuple 是不同的契约
3. 独立文件更清晰地表达了"校验"与"归一化"的职责区别
4. 未来可能扩展更多校验规则（如 cross-block 约束检查），独立文件更方便
