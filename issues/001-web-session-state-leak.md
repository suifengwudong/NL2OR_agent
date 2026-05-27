# 001 — Web 会话状态泄漏（跨用户 / 跨标签页）

**Labels:** `bug`, `web`, `high-priority`  
**Priority:** 🔴 High  
**Status:** ✅ Fixed in commit (dev-fix branch)

## 问题描述

`web/app.py` 原始实现中，`create_ui(agent)` 接收一个**全局共享**的 `CodeAgent` 实例，并在 `run_agent` 闭包里通过 `agent.run(..., reset=False)` 调用它。  
`reset=False` 表示 agent 会保留上一轮的对话历史（messages / memory）；这意味着：

- **用户 A** 发送的问题和中间状态会污染 **用户 B** 收到的回答。  
- 多浏览器标签页（同一用户的不同会话）同样共享状态。  
- 在 Gradio 的并发请求模式下，并发调用同一 agent 实例可能导致竞态条件。

### 复现路径

```
浏览器 Tab A: "请为我建立一个 p-median 模型"
浏览器 Tab B: "你好，这是什么工具？"
# Tab B 的 agent 内部历史中已包含 Tab A 传入的 p-median 上下文
```

## 根本原因

`main.py` 中：

```python
# 旧代码 — 所有用户共享同一个 agent 实例
agent = build_nl2or_agent(verbosity_level=0)
launch_web(agent)
```

## 修复方案

改用 **`gr.State`** 持有每用户的 agent 实例，并让 `create_ui` 接收 **工厂函数**而非预先构建的实例。

`web/app.py`（修复后）：

```python
def create_ui(agent_factory: Callable[[], Any]):
    user_agent_state = gr.State(value=None)

    def run_agent(message, history, user_agent):
        if user_agent is None:
            user_agent = agent_factory()   # 首次消息时惰性创建
        result = user_agent.run(message.strip(), reset=False)
        ...
        return history, "", user_agent

    ...
    submit_btn.click(
        fn=run_agent,
        inputs=[msg, chatbot, user_agent_state],
        outputs=[chatbot, msg, user_agent_state],
    )
```

`main.py`（修复后）：

```python
def _run_web():
    from agents import build_nl2or_agent
    from web import launch_web

    def agent_factory():
        return build_nl2or_agent(verbosity_level=0)

    launch_web(agent_factory)
```

## 影响范围

- `nl2or_agent/web/app.py`
- `nl2or_agent/main.py`

## 参考

- [Gradio `gr.State` 文档](https://www.gradio.app/docs/gradio/state)
