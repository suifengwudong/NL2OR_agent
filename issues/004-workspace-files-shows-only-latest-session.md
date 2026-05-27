# 004 — Web 工作区文件面板只显示最近一个会话的文件

**Labels:** `ux`, `web`, `low-priority`  
**Priority:** 🟢 Low  
**Status:** 📝 Open

## 问题描述

`web/app.py` 的 `get_workspace_files()` 函数仅展示**最近一个**会话目录中的求解器文件：

```python
def get_workspace_files() -> str:
    sessions = Session.list_all()
    if not sessions:
        return "(no sessions yet)"
    latest = Session.load(sessions[-1])   # ← 只取最后一个
    ...
    return "\n".join(f.name for f in files)
```

当用户在新标签页打开 Web UI（Issue #001 修复后每个标签获得独立 Session），或者多次刷新 / 重建会话后，旧会话生成的求解器文件将不再显示在文件面板中，造成混乱。

此外，在 Issue #003 修复前，`get_session()` 可能因并发覆盖而指向错误的会话，使 "最新会话" 并非当前用户的会话。

## 建议修复

### 方案 A（短期）：展示所有会话的文件，带会话 ID 分组

```python
def get_workspace_files() -> str:
    sessions = Session.list_all()
    if not sessions:
        return "(no sessions yet)"
    lines = []
    for sid in reversed(sessions):  # 最新的在前
        s = Session.load(sid)
        if s is None:
            continue
        files = s.list_code_files()
        if files:
            lines.append(f"[{sid}]")
            lines.extend(f"  {f.name}" for f in files)
    return "\n".join(lines) or "(no solver files yet)"
```

### 方案 B（长期）：将当前会话 ID 存入 `gr.State`，只展示本用户文件

在 Issue #001 的 `gr.State` 修复基础上，将 `Session` 实例也放入 state，使 `get_workspace_files` 接收当前用户的 session 作为参数，只展示属于该用户的文件。

## 影响范围

- `nl2or_agent/web/app.py` — `get_workspace_files()`

## 注意

此问题在单用户单标签页场景下影响有限，但在多用户或多标签页使用时较为明显。建议在 Issue #001 和 #003 修复后一并处理。
