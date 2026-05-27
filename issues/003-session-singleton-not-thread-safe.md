# 003 — `utils/session.py` 模块级单例在并发请求下非线程安全

**Labels:** `bug`, `concurrency`, `medium-priority`  
**Priority:** 🟡 Medium  
**Status:** 📝 Open

## 问题描述

`utils/session.py` 使用模块级全局变量 `_current_session` 维护"当前会话"单例：

```python
_current_session: Session | None = None

def get_session(session_id: str | None = None) -> Session:
    global _current_session
    if _current_session is None or (session_id and _current_session.session_id != session_id):
        _current_session = Session(session_id=session_id)
    return _current_session
```

`tools/solver_tool.py` 在未指定 `workspace_dir` 时调用 `get_session()`：

```python
session = get_session()
workspace = str(session.code_dir)
```

### 并发风险

Gradio 默认在**多线程**模式下处理并发请求（`queue()` 开启时可同时运行多个请求）。在这种情况下：

1. **用户 A** 触发 solver，调用 `get_session()`，`_current_session` 被设置为 Session-A。  
2. **用户 B** 的请求恰好同时执行，覆盖 `_current_session` 为 Session-B。  
3. 用户 A 的 solver 实际写入了 Session-B 的工作目录，导致文件混乱。

注意：此问题独立于 Issue #001（已通过 `gr.State` 隔离 agent 实例），因为 `get_session()` 是在 `solver_tool.py` 内部调用的，不经过 Gradio state 传递。

## 建议修复

### 方案 A（推荐）：使用 `threading.local` 实现线程隔离

```python
import threading

_tls = threading.local()

def get_session(session_id: str | None = None) -> Session:
    current = getattr(_tls, "session", None)
    if current is None or (session_id and current.session_id != session_id):
        _tls.session = Session(session_id=session_id)
    return _tls.session

def reset_session() -> None:
    _tls.session = None
```

### 方案 B：通过 `gr.State` 将 Session 注入工具

将 `Session` 实例作为参数显式传入每个工具的 `forward()` 调用，而不是依赖全局状态。这需要重构工具接口，代价较高，适合长期改进。

### 方案 C：禁用 Gradio 并发

在 `launch_web` 中使用 `max_threads=1` 彻底禁止并发，代价是降低响应性：

```python
ui.launch(share=False, max_threads=1)
```

## 影响范围

- `nl2or_agent/utils/session.py` — `_current_session` 全局变量、`get_session()`、`reset_session()`
- `nl2or_agent/tools/solver_tool.py` — 调用 `get_session()` 的代码路径

## 复现条件

- Gradio 并发模式开启（`queue()` 或默认多线程）
- 两个用户同时发送消息并触发 solver
