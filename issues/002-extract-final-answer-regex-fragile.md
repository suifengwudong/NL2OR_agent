# 002 — `_extract_final_answer` 正则表达式不够健壮

**Labels:** `bug`, `web`, `medium-priority`  
**Priority:** 🟡 Medium  
**Status:** 📝 Open

## 问题描述

`web/app.py` 中的 `_extract_final_answer()` 用正则表达式解析 HAMLET agent 返回的原始字符串，以提取 `final_answer(...)` 调用的内容。当前正则：

```python
pattern = r'final_answer\((["\'])(.*?)\1\s*\)'
```

**只能匹配单引号或双引号括起的单行字面量**，以下合法形式均无法匹配：

| 场景 | 示例 | 是否匹配 |
|---|---|---|
| 正常单行字符串 | `final_answer("结果")` | ✅ |
| 三引号多行字符串 | `final_answer("""...""")` | ❌ |
| 表达式形式 | `final_answer("a" + "b")` | ❌ |
| 变量形式 | `final_answer(result)` | ❌ |
| 尾部有注释 | `final_answer("x")  # done` | ✅（偶然匹配） |

当正则匹配失败时，后备逻辑（删去 `Thought:`、`Code:` 等行）可能将 agent 内部推理步骤误当作最终答案展示给用户。

## 建议修复

### 方案 A（推荐）：依赖 HAMLET 原生返回值

`CodeAgent.run()` 设计上返回的是传给 `final_answer()` 的值，而非原始 trace。  
只有在特定 HAMLET 版本将 trace 混入返回值时才需要正则解析。  
**建议先验证当前 HAMLET 版本的 `run()` 行为**，确认是否真的需要此解析步骤：

```python
result = agent.run(message, reset=False)
# 如果 run() 已返回纯净的答案，可直接使用：
answer = result.strip()
```

### 方案 B（增强正则）：扩展正则以覆盖三引号形式

```python
import re

_FA_PATTERNS = [
    # 三引号（多行）
    r'final_answer\("""(.*?)"""\s*\)',
    r"final_answer\('''(.*?)'''\s*\)",
    # 单/双引号（单行）
    r'final_answer\((["\'])(.*?)\1\s*\)',
]

def _extract_final_answer(raw: str) -> str:
    for pat in _FA_PATTERNS:
        flags = re.DOTALL
        matches = list(re.finditer(pat, raw, flags))
        if matches:
            m = matches[-1]
            # 三引号模式 group(1) 即内容；单引号模式 group(2) 是内容
            return (m.group(1) if m.lastindex == 1 else m.group(2)).strip()
    # fallback …
```

### 方案 C（长远）：让 agent 返回结构化数据

在系统提示中要求 agent 以 JSON 格式调用 `final_answer`，或使用 HAMLET 的 structured output 功能，消除对字符串解析的依赖。

## 影响范围

- `nl2or_agent/web/app.py` — `_extract_final_answer()`

## 复现条件

- HAMLET 版本将 trace 混入 `agent.run()` 返回值时
- Agent 在 `final_answer` 中使用多行或拼接字符串时
