"""守密人Agent (Game Master)

核心叙事Agent，负责：
- 场景描述和氛围营造
- NPC对话和行为
- 解读玩家行动
- 判断何时需要技能检定、战斗等
- 推进故事
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional

from .base import BaseAgent
from ..config import get_settings
from ..middleware.token_tracker import TokenTracker
from ..models.character import Investigator
from ..models.game_state import GameSession, NarrativeEntry, SceneState

logger = logging.getLogger(__name__)


def _format_investigator_inventory(inv: Investigator) -> str:
    """格式化为守密人可见的持有物清单（叙事约束用）。"""
    if not inv.inventory:
        return (
            f"{inv.name}：未登记具体物品——勿为其编造特定武器、工具或证物；"
            f"若需要道具，须来自玩家当次行动明确说明并经你认可。"
        )
    bits: list[str] = []
    for it in inv.inventory:
        if it.is_weapon:
            wparts = [it.name]
            if it.damage:
                wparts.append(f"伤害{it.damage}")
            if it.range:
                wparts.append(f"射程{it.range}")
            if it.skill_name:
                wparts.append(f"技能{it.skill_name}")
            bits.append("武器：" + "，".join(wparts))
        else:
            q = f"×{it.quantity}" if it.quantity > 1 else ""
            d = f"（{it.description}）" if it.description else ""
            bits.append(f"{it.name}{q}{d}")
    return f"{inv.name}：" + "；".join(bits)


# 守密人核心系统提示词
KEEPER_SYSTEM_PROMPT = """你是一位经验丰富的克苏鲁的呼唤（第7版）守密人（Keeper of Arcane Lore）。

# 核心职责
你负责主持一场克苏鲁的呼唤桌面角色扮演游戏。你的任务是：
1. 以第二人称描述场景、环境和NPC行为
2. 营造克苏鲁式的恐怖和神秘氛围
3. 解读并回应调查员（玩家角色）的行动
4. 在适当时候触发技能检定（在叙事中用【技能检定：技能名】标记）
5. 在需要时触发战斗（用【进入战斗】标记）
6. 在遭遇超自然恐怖时触发理智检定（用【理智检定：成功损失/失败损失】标记）

# 叙事风格
- 使用中文进行所有叙事
- 维持1920年代（或适合的时代）的氛围
- 描述要生动、感官丰富（视觉、听觉、嗅觉、触觉）
- 保持克苏鲁式的宇宙恐怖基调：未知远比已知更可怕
- NPC对话要有个性，反映其性格和动机
- 不要替调查员做决定，只描述世界对他们行动的反应

# 机制标记格式
当叙事中需要进行游戏机制操作时，使用以下标记（系统会自动解析）：
- 【技能检定：侦查】— 需要普通难度的侦查检定
- 【技能检定：图书馆使用/困难】— 需要困难难度的检定
- 【理智检定：0/1d3】— 成功损失0，失败损失1d3
- 【理智检定：1/1d6】— 成功损失1，失败损失1d6
- 【进入战斗】— 转入战斗轮
- 【场景转换：场景名/场景描述】— 转换到新场景

# 重要规则
- 你不负责掷骰或计算数值——只需标记何时需要检定
- 不要自行判定检定结果，等待系统反馈
- 关注调查员的背景故事，利用它们丰富叙事
- 核心线索不应该隐藏在单次检定之后（允许多种方式发现）
- 保持节奏——不要在无事发生时拖沓，也不要过快推进
- 调查员的武器、工具与随身物品必须严格依据下文「调查员持有物」列表；不得编造列表中不存在的具体物品
"""


def build_context_prompt(
    session: GameSession,
    investigators: list[Investigator],
    recent_narrative: list[NarrativeEntry],
    verbosity: str = "详细",
    module_context: str = "",
) -> str:
    """构建上下文信息（附加到系统提示词之后）

    根据当前游戏状态构建Agent需要的所有上下文信息。

    Args:
        session: 游戏会话状态
        investigators: 所有调查员
        recent_narrative: 近期叙事记录
        verbosity: 详细程度（"详细"/"简洁"/"极简"）
        module_context: 模组相关的额外信息

    Returns:
        上下文提示词字符串
    """
    parts = []

    # 叙事详细程度指示（与 TokenTracker.suggested_verbosity 联动）
    # 说明：max_tokens 只是生成长度上限，模型默认不会写满；「详细」模式需明确允许写长，否则会偏短。
    if verbosity == "简洁":
        parts.append("【注意：Token预算已用较多，请优先简洁，每次回应宜控制在约200字以内；但若未到合法停止点仍需写够情节。】")
    elif verbosity == "极简":
        parts.append("【注意：Token预算接近上限，请用最短方式叙事，每次回应宜控制在约100字以内；仍须满足合法停止点规则。】")
    else:
        parts.append(
            "【叙事体量：当前为详细模式。可按情节需要充分展开环境与事件（常见可达数百字至更长），"
            "勿因习惯而过度压缩；只要未到合法停止点、且尚未写出机制标记，就应继续写下去。】"
        )

    # 守密人记忆（事实 / 地点定稿 / 分NPC）
    mem = getattr(session, "keeper_memory", None)
    if mem is not None:
        mem_block = mem.to_prompt_block()
        if mem_block.strip():
            parts.append(mem_block)

    # 当前场景
    if session.current_scene:
        scene = session.current_scene
        parts.append(f"\n# 当前场景\n场景：{scene.name}\n描述：{scene.description}")
        if scene.atmosphere:
            parts.append(f"氛围：{scene.atmosphere}")
        if scene.npcs_present:
            npc_names = []
            for npc_id in scene.npcs_present:
                npc = session.npcs.get(npc_id)
                if npc:
                    npc_names.append(f"{npc.name}（{npc.attitude}）")
            if npc_names:
                parts.append(f"在场NPC：{'、'.join(npc_names)}")

    # 调查员信息
    if investigators:
        parts.append("\n# 调查员")
        for inv in investigators:
            status_parts = [
                f"HP {inv.derived.hp}/{inv.derived.hp_max}",
                f"SAN {inv.derived.san}/{inv.derived.san_max}",
                f"MP {inv.derived.mp}/{inv.derived.mp_max}",
            ]
            if inv.combat_status.value != "正常":
                status_parts.append(f"状态：{inv.combat_status.value}")
            if inv.insanity.type.value != "无":
                status_parts.append(f"疯狂：{inv.insanity.type.value}")
            parts.append(
                f"- {inv.name}（{inv.occupation}，{inv.age}岁）— {'，'.join(status_parts)}"
            )
        parts.append(
            "\n# 调查员持有物（叙事唯一依据；不得编造未列出的具体物品、武器或证物）"
        )
        for inv in investigators:
            parts.append("- " + _format_investigator_inventory(inv))

    # NPC秘密信息（仅守密人可见）
    secret_npcs = [npc for npc in session.npcs.values() if npc.secret]
    if secret_npcs:
        parts.append("\n# NPC秘密（仅守密人可见）")
        for npc in secret_npcs:
            parts.append(f"- {npc.name}：{npc.secret}")

    # 已发现的线索
    discovered = [c for c in session.clues.values() if c.is_discovered]
    if discovered:
        parts.append("\n# 已发现线索")
        for clue in discovered:
            parts.append(f"- {clue.name}：{clue.description}")

    # 模组上下文
    if module_context:
        parts.append(f"\n# 模组信息\n{module_context}")

    # 历史摘要
    if session.narrative_summary:
        parts.append(f"\n# 故事摘要\n{session.narrative_summary}")

    result = "\n".join(parts)
    logger.info(
        "===== build_context_prompt (%d chars) =====\n%s\n===== /build_context_prompt =====",
        len(result), result,
    )
    return result


class GameMasterAgent(BaseAgent):
    """守密人Agent"""

    def __init__(
        self,
        token_tracker: Optional[TokenTracker] = None,
        model: Optional[str] = None,
    ):
        super().__init__(
            name="守密人",
            system_prompt=KEEPER_SYSTEM_PROMPT,
            token_tracker=token_tracker,
            model=model,
            max_tokens=get_settings().agents.game_master,
        )

    def _build_messages(
        self,
        player_action: str,
        context: str,
        recent_narrative: list[NarrativeEntry],
    ) -> list[dict]:
        """构建消息列表

        将上下文、近期历史和玩家行动组合为API消息格式。
        """
        messages = []

        # 将上下文作为第一条用户消息
        if context:
            messages.append({
                "role": "user",
                "content": f"[游戏上下文]\n{context}",
            })
            messages.append({
                "role": "assistant",
                "content": "明白，我已了解当前游戏状态。",
            })

        # 近期叙事历史
        for entry in recent_narrative:
            if entry.source == "守密人":
                messages.append({"role": "assistant", "content": entry.content})
            else:
                prefix = f"[{entry.source}]" if entry.entry_type == "action" else ""
                messages.append({"role": "user", "content": f"{prefix} {entry.content}"})

        # 当前玩家行动
        messages.append({"role": "user", "content": player_action})

        return messages

    async def narrate(
        self,
        player_action: str,
        session: GameSession,
        investigators: list[Investigator],
        recent_narrative: list[NarrativeEntry],
        module_context: str = "",
    ) -> tuple[str, dict]:
        """非流式叙事（用于简短回应）"""
        verbosity = "详细"
        if self.token_tracker:
            verbosity = self.token_tracker.suggested_verbosity

        context = build_context_prompt(
            session, investigators, recent_narrative,
            verbosity=verbosity, module_context=module_context,
        )
        messages = self._build_messages(player_action, context, recent_narrative)

        # 临时设置包含上下文的system prompt
        full_system = self.system_prompt
        if context:
            full_system = self.system_prompt + "\n\n" + context

        old_prompt = self.system_prompt
        self.system_prompt = full_system
        try:
            return await self.invoke(messages, temperature=0.8)
        finally:
            self.system_prompt = old_prompt

    async def narrate_stream(
        self,
        player_action: str,
        session: GameSession,
        investigators: list[Investigator],
        recent_narrative: list[NarrativeEntry],
        module_context: str = "",
    ) -> AsyncGenerator[str, None]:
        """流式叙事（逐字输出，用于实时显示）"""
        verbosity = "详细"
        if self.token_tracker:
            verbosity = self.token_tracker.suggested_verbosity

        context = build_context_prompt(
            session, investigators, recent_narrative,
            verbosity=verbosity, module_context=module_context,
        )
        messages = self._build_messages(player_action, context, recent_narrative)

        full_system = self.system_prompt
        if context:
            full_system = self.system_prompt + "\n\n" + context

        old_prompt = self.system_prompt
        self.system_prompt = full_system
        try:
            async for chunk in self.stream(messages, temperature=0.8):
                yield chunk
        finally:
            self.system_prompt = old_prompt

    async def classify_action(
        self,
        player_action: str,
        session: GameSession,
    ) -> dict:
        """分类玩家行动

        判断行动类型：叙事、技能检定、战斗、其他。
        使用工具调用获取结构化输出。

        Returns:
            {"type": "narration"|"skill_check"|"combat"|"sanity", ...}
        """
        tools = [{
            "name": "classify_player_action",
            "description": "将玩家的行动分类为游戏机制类型",
            "input_schema": {
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "enum": ["narration", "skill_check", "combat", "sanity", "character"],
                        "description": "行动类型：narration（纯叙事）、skill_check（需要技能检定）、combat（战斗相关）、sanity（涉及理智）、character（角色管理）",
                    },
                    "skill_name": {
                        "type": "string",
                        "description": "如果是技能检定，指定技能名称",
                    },
                    "difficulty": {
                        "type": "string",
                        "enum": ["普通", "困难", "极难"],
                        "description": "检定难度",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "分类理由（简短）",
                    },
                },
                "required": ["action_type", "reasoning"],
            },
        }]

        messages = [{
            "role": "user",
            "content": (
                f"当前游戏阶段：{session.phase.value}\n"
                f"玩家行动：{player_action}\n\n"
                "请判断这个行动的类型。"
            ),
        }]

        blocks, usage = await self.invoke_with_tools(messages, tools, temperature=0.0)

        # 提取工具调用结果
        for block in blocks:
            if block["type"] == "tool_use" and block["name"] == "classify_player_action":
                return block["input"]

        # 默认为叙事
        return {"action_type": "narration", "reasoning": "无法分类，默认为叙事"}
