"""基础Agent类

所有Agent的父类，封装Claude API调用、流式输出、Token追踪。
"""

from __future__ import annotations

import os
from typing import AsyncGenerator, Optional

import anthropic

from ..config import get_settings
from ..middleware.token_tracker import TokenTracker


class BaseAgent:
    """Agent基类

    提供：
    - Claude API客户端（单例）
    - 流式和非流式调用
    - Token用量自动记录
    - 系统提示词管理
    """

    # 类级别共享客户端
    _client: Optional[anthropic.AsyncAnthropic] = None

    def __init__(
        self,
        name: str,
        system_prompt: str,
        token_tracker: Optional[TokenTracker] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.token_tracker = token_tracker
        _s = get_settings()
        self.model = (
            model
            or os.getenv("CLAUDE_MODEL")
            or _s.llm.default_model
        )
        self.max_tokens = (
            max_tokens if max_tokens is not None else _s.agents.base_default
        )

    @classmethod
    def get_client(cls) -> anthropic.AsyncAnthropic:
        """获取或创建异步Anthropic客户端"""
        if cls._client is None:
            key = get_settings().effective_anthropic_api_key()
            cls._client = anthropic.AsyncAnthropic(api_key=key)
        return cls._client

    async def invoke(
        self,
        messages: list[dict],
        temperature: float = 0.7,
    ) -> tuple[str, dict]:
        """非流式调用Claude API

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            temperature: 温度参数

        Returns:
            (响应文本, usage字典)
        """
        client = self.get_client()
        response = await client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            messages=messages,
            temperature=temperature,
        )

        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text

        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        }

        if self.token_tracker:
            self.token_tracker.record(self.name, usage, self.model)

        return text, usage

    async def stream(
        self,
        messages: list[dict],
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """流式调用Claude API

        逐个token产出文本，结束后自动记录用量。

        Args:
            messages: 消息列表
            temperature: 温度参数

        Yields:
            文本片段
        """
        client = self.get_client()
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }

        async with client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            messages=messages,
            temperature=temperature,
        ) as stream:
            async for text in stream.text_stream:
                yield text

            # 流结束后获取完整usage
            final_message = await stream.get_final_message()
            usage["input_tokens"] = final_message.usage.input_tokens
            usage["output_tokens"] = final_message.usage.output_tokens
            usage["cache_read_input_tokens"] = getattr(
                final_message.usage, "cache_read_input_tokens", 0
            ) or 0
            usage["cache_creation_input_tokens"] = getattr(
                final_message.usage, "cache_creation_input_tokens", 0
            ) or 0

        if self.token_tracker:
            self.token_tracker.record(self.name, usage, self.model)

    async def invoke_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.7,
    ) -> tuple[list[dict], dict]:
        """带工具调用的Claude API调用

        用于需要结构化输出的场景（如技能鉴定结果）。

        Args:
            messages: 消息列表
            tools: 工具定义列表
            temperature: 温度参数

        Returns:
            (content_blocks, usage字典)
        """
        client = self.get_client()
        response = await client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            messages=messages,
            tools=tools,
            temperature=temperature,
        )

        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        }

        if self.token_tracker:
            self.token_tracker.record(self.name, usage, self.model)

        # 返回所有内容块
        blocks = []
        for block in response.content:
            if block.type == "text":
                blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        return blocks, usage
