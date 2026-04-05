"""Token用量追踪中间件

记录每次Claude API调用的token消耗，支持按会话、按Agent统计。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..config import get_settings


@dataclass
class APICallRecord:
    """单次API调用记录"""
    timestamp: datetime
    agent_name: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def estimated_cost_usd(self) -> float:
        """基于Claude Sonnet定价估算"""
        input_cost = (self.input_tokens - self.cache_read_tokens) * 3.0 / 1_000_000
        cache_cost = self.cache_read_tokens * 0.3 / 1_000_000
        output_cost = self.output_tokens * 15.0 / 1_000_000
        return input_cost + cache_cost + output_cost


class TokenTracker:
    """Token用量追踪器

    每个游戏会话一个实例，记录所有Agent的token消耗。
    """

    def __init__(self, session_id: str, budget: Optional[int] = None):
        self.session_id = session_id
        _s = get_settings().session
        self.budget = budget if budget is not None else _s.default_token_budget
        self.records: list[APICallRecord] = []
        self._warning_thresholds = list(_s.token_warning_thresholds)
        self._warnings_sent: set[int] = set()

    def record(self, agent_name: str, usage: dict, model: str = "") -> APICallRecord:
        """记录一次API调用

        Args:
            agent_name: Agent名称（如"守密人"、"技能鉴定"）
            usage: Anthropic API返回的usage字典
            model: 使用的模型名

        Returns:
            APICallRecord
        """
        record = APICallRecord(
            timestamp=datetime.now(),
            agent_name=agent_name,
            model=model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
        )
        self.records.append(record)
        return record

    @property
    def total_input(self) -> int:
        return sum(r.input_tokens for r in self.records)

    @property
    def total_output(self) -> int:
        return sum(r.output_tokens for r in self.records)

    @property
    def total_cached(self) -> int:
        return sum(r.cache_read_tokens for r in self.records)

    @property
    def total_tokens(self) -> int:
        return self.total_input + self.total_output

    @property
    def total_cost(self) -> float:
        return sum(r.estimated_cost_usd for r in self.records)

    @property
    def budget_used_pct(self) -> float:
        if self.budget <= 0:
            return 0
        return self.total_tokens / self.budget * 100

    def check_budget_warnings(self) -> Optional[str]:
        """检查是否需要发出预算警告

        Returns:
            警告消息，无警告时返回None
        """
        pct = self.budget_used_pct
        for threshold in self._warning_thresholds:
            if pct >= threshold and threshold not in self._warnings_sent:
                self._warnings_sent.add(threshold)
                return (
                    f"Token预算警告：已使用 {pct:.1f}%"
                    f"（{self.total_tokens:,} / {self.budget:,}）"
                    f"，预估费用 ${self.total_cost:.4f}"
                )
        return None

    def get_summary(self) -> dict:
        """获取用量摘要"""
        by_agent: dict[str, dict] = {}
        for r in self.records:
            if r.agent_name not in by_agent:
                by_agent[r.agent_name] = {
                    "input": 0, "output": 0, "cached": 0,
                    "cost": 0.0, "calls": 0,
                }
            entry = by_agent[r.agent_name]
            entry["input"] += r.input_tokens
            entry["output"] += r.output_tokens
            entry["cached"] += r.cache_read_tokens
            entry["cost"] += r.estimated_cost_usd
            entry["calls"] += 1

        for entry in by_agent.values():
            entry["cost"] = round(entry["cost"], 4)

        return {
            "session_id": self.session_id,
            "total": {
                "input": self.total_input,
                "output": self.total_output,
                "cached": self.total_cached,
                "tokens": self.total_tokens,
                "cost": round(self.total_cost, 4),
                "budget": self.budget,
                "budget_used_pct": round(self.budget_used_pct, 1),
            },
            "by_agent": by_agent,
            "call_count": len(self.records),
        }

    @property
    def suggested_verbosity(self) -> str:
        """根据预算消耗建议叙事详细程度"""
        pct = self.budget_used_pct
        if pct < 50:
            return "详细"   # 正常叙事
        elif pct < 80:
            return "简洁"   # 缩短叙事
        else:
            return "极简"   # 最小化输出
