import os

import pytest
from agents import build_nl2or_agent


def test_parsing_step_one():
    """测试 Step 1：解析阶段。
    由于涉及真实的 LLM 调用，这里主要验证接口连通性和初步返回的格式。
    注意：这需要环境变量中有有效的 API Key。
    """
    if not os.getenv("OPENROUTER_API_KEY") or not os.getenv("HAMLET_MODEL_ID"):
        pytest.skip("跳过需要 API Key 或 Model ID 的测试")

    agent = build_nl2or_agent(verbosity_level=1)
    question = "我有100元，想买单价3元的橘子，最多买多少个？"

    # 我们期望 Agent 返回一个包含 'final_answer' 的结果，而不是陷入死循环
    result = agent.run(question)

    assert isinstance(result, str)
    assert len(result) > 0
    # 检查是否包含关键解析词（中文或英文）
    assert any(word in result.lower() for word in ["橘子", "orange", "3", "100"])
