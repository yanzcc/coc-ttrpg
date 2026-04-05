"""战斗Agent

管理战斗轮次，解析行动，协调伤害计算。
"""

from __future__ import annotations

from typing import AsyncGenerator, Optional

from .base import BaseAgent
from ..config import get_settings
from ..middleware.token_tracker import TokenTracker

COMBAT_SYSTEM_PROMPT = """你是克苏鲁的呼唤第7版的战斗叙事者。

你的职责是将战斗行动和结果描述为紧张、生动的叙事。

# 规则
- 描述攻击、闪避、伤害的过程
- 重伤和死亡需要特别戏剧性的描述
- 保持CoC恐怖基调，战斗应该感觉危险且致命
- 每个行动描述50-100字
- 使用中文
"""


class CombatAgent(BaseAgent):
    def __init__(
        self,
        token_tracker: Optional[TokenTracker] = None,
        model: Optional[str] = None,
    ):
        super().__init__(
            name="战斗",
            system_prompt=COMBAT_SYSTEM_PROMPT,
            token_tracker=token_tracker,
            model=model,
            max_tokens=get_settings().agents.combat,
        )

    async def narrate_attack(
        self,
        attacker: str,
        defender: str,
        weapon: str,
        roll_value: int,
        success_level: str,
        damage: int,
        defender_response: str = "",
        defender_result: str = "",
        context: str = "",
    ) -> str:
        """叙述攻击过程和结果

        Args:
            attacker: 攻击者名字
            defender: 防御者名字
            weapon: 使用的武器
            roll_value: 攻击骰结果
            success_level: 成功等级（如"普通成功"、"极难成功"等）
            damage: 造成的伤害值
            defender_response: 防御者的反应动作（如"闪避"、"反击"、"无"）
            defender_result: 防御者反应的结果（如"闪避成功"、"闪避失败"）
            context: 当前战斗场景描述

        Returns:
            攻击叙事文本（50-100字）
        """
        prompt = f"攻击者：{attacker}，使用{weapon}攻击{defender}。\n"
        prompt += f"攻击骰：{roll_value}，结果：{success_level}，伤害：{damage}点。\n"
        if defender_response:
            prompt += f"防御者反应：{defender_response}，结果：{defender_result}。\n"
        if context:
            prompt += f"场景背景：{context}\n"
        prompt += "请用50-100字描述这次攻击的过程和结果。"

        messages = [{"role": "user", "content": prompt}]
        text, _usage = await self.invoke(messages, temperature=0.8)
        return text.strip()

    async def narrate_round_summary(
        self,
        round_number: int,
        actions: list[dict],
        context: str = "",
    ) -> str:
        """叙述战斗轮摘要

        Args:
            round_number: 当前战斗轮数
            actions: 本轮所有行动列表，每个元素为字典，包含：
                - actor: 行动者名字
                - action_type: 行动类型（攻击/闪避/逃跑/施法等）
                - target: 目标（如有）
                - result: 结果描述
                - damage: 伤害值（如有）
            context: 当前战斗场景描述

        Returns:
            战斗轮摘要叙事文本
        """
        action_lines: list[str] = []
        for i, act in enumerate(actions, 1):
            actor = act.get("actor", "未知")
            action_type = act.get("action_type", "行动")
            target = act.get("target", "")
            result = act.get("result", "")
            damage = act.get("damage", 0)
            line = f"{i}. {actor}：{action_type}"
            if target:
                line += f" → {target}"
            if result:
                line += f"（{result}"
                if damage:
                    line += f"，{damage}点伤害"
                line += "）"
            action_lines.append(line)

        prompt = f"第{round_number}轮战斗行动：\n"
        prompt += "\n".join(action_lines) + "\n"
        if context:
            prompt += f"场景背景：{context}\n"
        prompt += "请将以上行动整合为一段流畅的战斗轮摘要叙事。"

        messages = [{"role": "user", "content": prompt}]
        text, _usage = await self.invoke(messages, temperature=0.8)
        return text.strip()

    async def narrate_combat_end(
        self,
        reason: str,
        casualties: list[dict],
        context: str = "",
    ) -> str:
        """叙述战斗结束

        Args:
            reason: 战斗结束原因（如"敌人全灭"、"调查员撤退"、"敌人逃跑"等）
            casualties: 伤亡列表，每个元素为字典，包含：
                - name: 角色名字
                - status: 状态（死亡/重伤/昏迷/轻伤等）
                - cause: 伤亡原因
            context: 当前战斗场景描述

        Returns:
            战斗结束叙事文本
        """
        casualty_lines: list[str] = []
        for c in casualties:
            name = c.get("name", "未知")
            status = c.get("status", "未知")
            cause = c.get("cause", "")
            line = f"- {name}：{status}"
            if cause:
                line += f"（{cause}）"
            casualty_lines.append(line)

        prompt = f"战斗结束。原因：{reason}。\n"
        if casualty_lines:
            prompt += "伤亡情况：\n" + "\n".join(casualty_lines) + "\n"
        else:
            prompt += "无人员伤亡。\n"
        if context:
            prompt += f"场景背景：{context}\n"
        prompt += "请写一段战斗结束后的叙事，描述战场的余波和氛围。"

        messages = [{"role": "user", "content": prompt}]
        text, _usage = await self.invoke(messages, temperature=0.8)
        return text.strip()
