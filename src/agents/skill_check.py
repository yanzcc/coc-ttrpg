"""技能鉴定Agent

负责将骰子结果包装为叙事，处理孤注一掷及其后果。
大部分机制计算由 rules.skill_check 完成，此Agent负责叙事包装。
"""

from __future__ import annotations

from typing import Optional

from .base import BaseAgent
from ..config import get_settings
from ..middleware.token_tracker import TokenTracker
from ..rules.skill_check import SkillCheckResult, SuccessLevel

SKILL_CHECK_SYSTEM_PROMPT = """你是克苏鲁的呼唤第7版的技能鉴定叙事者。

你的职责是将骰子结果包装为生动的游戏叙事。

# 规则
- 根据检定结果（大成功/极难成功/困难成功/普通成功/失败/大失败）生成不同程度的叙事描述
- 大成功：调查员超常发挥，获得额外信息或效果
- 大失败：灾难性后果，可能伤害自己或队友
- 孤注一掷失败：比普通失败更严重的后果
- 保持简洁，50-150字
- 使用中文
"""

# 成功等级到中文名称的映射
_SUCCESS_LEVEL_NAMES: dict[SuccessLevel, str] = {
    SuccessLevel.FUMBLE: "大失败",
    SuccessLevel.FAILURE: "失败",
    SuccessLevel.REGULAR: "普通成功",
    SuccessLevel.HARD: "困难成功",
    SuccessLevel.EXTREME: "极难成功",
    SuccessLevel.CRITICAL: "大成功",
}


class SkillCheckAgent(BaseAgent):
    def __init__(
        self,
        token_tracker: Optional[TokenTracker] = None,
        model: Optional[str] = None,
    ):
        super().__init__(
            name="技能鉴定",
            system_prompt=SKILL_CHECK_SYSTEM_PROMPT,
            token_tracker=token_tracker,
            model=model,
            max_tokens=get_settings().agents.skill_check,
        )

    async def narrate_result(
        self,
        result: SkillCheckResult,
        investigator_name: str,
        context: str = "",
    ) -> str:
        """将检定结果包装为叙事

        Args:
            result: 技能检定结果（由 rules.skill_check 产生）
            investigator_name: 调查员名字
            context: 当前场景描述，帮助LLM生成更贴合的叙事

        Returns:
            叙事文本（50-150字）
        """
        level_name = _SUCCESS_LEVEL_NAMES.get(result.success_level, "未知")
        prompt = (
            f'调查员"{investigator_name}"进行了【{result.skill_name}】检定。\n'
            f"技能值：{result.skill_value}，掷出：{result.roll.result}，"
            f"结果：{level_name}。\n"
        )
        if result.is_pushed:
            prompt += "这是一次孤注一掷。\n"
        if context:
            prompt += f"当前场景：{context}\n"
        prompt += "请为这次检定结果写一段简短的叙事描述。"

        messages = [{"role": "user", "content": prompt}]
        text, _usage = await self.invoke(messages, temperature=0.8)
        return text.strip()

    async def suggest_difficulty(
        self,
        skill_name: str,
        player_action: str,
        scene_hint: str,
    ) -> str:
        """根据处境推断检定难度（普通/困难/极难）。"""
        prompt = (
            f"技能：{skill_name}\n"
            f"调查员行动：{player_action[:600]}\n"
            f"场景与叙事片段：{scene_hint[:1200]}\n\n"
            "只输出一个词：普通、困难 或 极难。不要其它文字。"
        )
        text, _usage = await self.invoke(
            [{"role": "user", "content": prompt}],
            temperature=0.15,
        )
        t = text.strip()
        for d in ("极难", "困难", "普通"):
            if d in t:
                return d
        return "普通"

    async def narrate_push_consequence(
        self,
        original_result: SkillCheckResult,
        pushed_result: SkillCheckResult,
        investigator_name: str,
        context: str = "",
    ) -> str:
        """孤注一掷失败的后果叙事

        当调查员选择孤注一掷但仍然失败时，需要描述比普通失败更严重的后果。

        Args:
            original_result: 第一次检定结果
            pushed_result: 孤注一掷的检定结果
            investigator_name: 调查员名字
            context: 当前场景描述

        Returns:
            后果叙事文本
        """
        orig_level = _SUCCESS_LEVEL_NAMES.get(original_result.success_level, "未知")
        push_level = _SUCCESS_LEVEL_NAMES.get(pushed_result.success_level, "未知")

        prompt = (
            f'调查员"{investigator_name}"在【{original_result.skill_name}】检定中'
            f"第一次{orig_level}（掷出{original_result.roll.result}），"
            f"随后孤注一掷，结果为{push_level}（掷出{pushed_result.roll.result}）。\n"
        )
        if pushed_result.is_fumble:
            prompt += "这是孤注一掷的大失败！请描述灾难性的后果。\n"
        else:
            prompt += "孤注一掷失败了。请描述比普通失败更严重的后果。\n"
        if context:
            prompt += f"当前场景：{context}\n"
        prompt += "请写一段叙事，描述这次孤注一掷失败带来的严重后果。"

        messages = [{"role": "user", "content": prompt}]
        text, _usage = await self.invoke(messages, temperature=0.9)
        return text.strip()
