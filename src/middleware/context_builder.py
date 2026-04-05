"""上下文构建器

负责在Token预算内组装最优的上下文信息。
使用优先级窗口策略：规则 > 当前场景 > 模组信息 > 角色 > 近期历史 > 摘要。
"""

from __future__ import annotations

import os
from typing import Optional

from ..config import get_settings
from ..models.character import Investigator
from ..models.game_state import GameSession, NarrativeEntry
from ..models.story_module import StoryModule


class ContextBuilder:
    """上下文构建器

    管理提示词的各个部分，按优先级在Token预算内组装。
    """

    # 粗略估算：1个中文字符 ≈ 1.5 tokens
    CHARS_PER_TOKEN = 0.67  # 1 token ≈ 0.67个中文字符

    def __init__(self, max_tokens: Optional[int] = None):
        """
        Args:
            max_tokens: 上下文最大Token数（不含system prompt）
        """
        self.max_tokens = (
            max_tokens
            if max_tokens is not None
            else get_settings().context.builder_max_tokens
        )

    def build(
        self,
        session: GameSession,
        investigators: list[Investigator],
        recent_narrative: list[NarrativeEntry],
        module: Optional[StoryModule] = None,
        verbosity: str = "详细",
    ) -> str:
        """构建完整上下文

        按优先级组装各部分，确保不超过Token预算。

        Args:
            session: 当前游戏会话
            investigators: 参与的调查员列表
            recent_narrative: 近期叙事记录
            module: 当前故事模组（可选）
            verbosity: 详细程度 - "详细"/"简洁"/"极简"

        Returns:
            组装好的上下文字符串
        """
        sections: list[tuple[str, str, int]] = []

        # 优先级1: 当前场景描述
        scene_ctx = self._build_scene_context(session, verbosity)
        if scene_ctx:
            sections.append(("当前场景", scene_ctx, 1))

        # 优先级2: 模组当前阶段信息
        if module is not None:
            module_ctx = self._build_module_context(module, session, verbosity)
            if module_ctx:
                sections.append(("模组信息", module_ctx, 2))

        # 优先级3: 角色状态概要
        char_ctx = self._build_character_context(investigators, verbosity)
        if char_ctx:
            sections.append(("调查员状态", char_ctx, 3))

        # 优先级4: 近期叙事记录
        narr_ctx = self._build_narrative_context(recent_narrative)
        if narr_ctx:
            sections.append(("近期事件", narr_ctx, 4))

        # 优先级5: 历史摘要
        summary_ctx = self._build_summary_context(session)
        if summary_ctx:
            sections.append(("历史摘要", summary_ctx, 5))

        return self._truncate_to_budget(sections, self.max_tokens)

    def _build_scene_context(
        self, session: GameSession, verbosity: str = "详细"
    ) -> str:
        """构建当前场景上下文"""
        scene = session.current_scene
        if scene is None:
            return ""

        parts: list[str] = []

        # 场景基本信息（所有模式都包含）
        parts.append(f"场景：{scene.name}")
        if scene.description:
            parts.append(f"描述：{scene.description}")
        if scene.location_type:
            parts.append(f"类型：{scene.location_type}")

        # 详细和简洁模式包含氛围
        if verbosity != "极简" and scene.atmosphere:
            parts.append(f"氛围：{scene.atmosphere}")

        # 在场NPC
        if scene.npcs_present:
            npc_names: list[str] = []
            for npc_id in scene.npcs_present:
                npc = session.npcs.get(npc_id)
                if npc and npc.is_alive:
                    attitude_tag = ""
                    if verbosity == "详细":
                        attitude_tag = f"（{npc.attitude}）"
                    npc_names.append(f"{npc.name}{attitude_tag}")
            if npc_names:
                parts.append(f"在场NPC：{'、'.join(npc_names)}")

        # 详细模式包含NPC秘密信息
        if verbosity == "详细":
            for npc_id in scene.npcs_present:
                npc = session.npcs.get(npc_id)
                if npc and npc.secret:
                    parts.append(f"  [{npc.name}的秘密] {npc.secret}")

        # 可用出口
        if verbosity != "极简" and scene.exits:
            exits_str = "、".join(
                f"{direction}→{target}" for direction, target in scene.exits.items()
            )
            parts.append(f"出口：{exits_str}")

        # 已发现的线索（详细模式）
        if verbosity == "详细" and scene.clues_discovered:
            discovered: list[str] = []
            for clue_id in scene.clues_discovered:
                clue = session.clues.get(clue_id)
                if clue:
                    discovered.append(f"{clue.name}：{clue.description}")
            if discovered:
                parts.append("已发现线索：\n  " + "\n  ".join(discovered))

        # 未发现的线索数量提示（非极简模式）
        if verbosity != "极简":
            undiscovered_count = len(scene.clues_available) - len(
                scene.clues_discovered
            )
            if undiscovered_count > 0:
                parts.append(f"（还有{undiscovered_count}条未发现的线索）")

        # 当前游戏阶段
        parts.append(f"游戏阶段：{session.phase.value}")

        # 战斗状态
        if session.combat is not None:
            combat = session.combat
            current = combat.current_participant
            current_name = current.name if current else "未知"
            parts.append(
                f"战斗中：第{combat.round_number}轮，"
                f"当前行动者：{current_name}"
            )

        # 待处理检定
        if session.pending_check is not None:
            check = session.pending_check
            parts.append(
                f"待处理检定：{check.skill_name}（{check.difficulty}），"
                f"上下文：{check.context}"
            )

        return "\n".join(parts)

    def _build_module_context(
        self,
        module: StoryModule,
        session: GameSession,
        verbosity: str = "详细",
    ) -> str:
        """构建模组上下文（当前场景相关的模组信息）"""
        parts: list[str] = []

        # 模组基本信息
        parts.append(f"模组：{module.metadata.title}")
        if verbosity == "详细" and module.metadata.summary:
            parts.append(f"概要：{module.metadata.summary}")

        # 找到当前对应的模组场景
        current_module_scene = None
        if session.current_scene is not None:
            current_module_scene = module.get_scene(session.current_scene.id)

        if current_module_scene is not None:
            scene = current_module_scene
            if scene.read_aloud:
                parts.append(f"朗读文本：{scene.read_aloud}")

            if verbosity != "极简":
                # 可能的技能检定提示
                if scene.likely_skill_checks:
                    parts.append(
                        f"可能的技能检定：{'、'.join(scene.likely_skill_checks)}"
                    )

                # 场景转换条件
                if scene.transitions:
                    trans_parts: list[str] = []
                    for trans in scene.transitions:
                        target = module.get_scene(trans.target_scene_id)
                        target_name = (
                            target.title if target else trans.target_scene_id
                        )
                        condition = trans.condition or "无特定条件"
                        trans_parts.append(f"→{target_name}：{condition}")
                    parts.append("场景转换：\n  " + "\n  ".join(trans_parts))

            if verbosity == "详细":
                # 当前场景的NPC详细信息
                for npc_id in scene.npc_ids:
                    module_npc = module.get_npc(npc_id)
                    if module_npc:
                        npc_info = f"[{module_npc.name}] "
                        if module_npc.personality:
                            npc_info += f"性格：{module_npc.personality}；"
                        if module_npc.motivation:
                            npc_info += f"动机：{module_npc.motivation}；"
                        if module_npc.dialogue_style:
                            npc_info += f"对话风格：{module_npc.dialogue_style}；"
                        if module_npc.secret:
                            npc_info += f"秘密：{module_npc.secret}"
                        parts.append(npc_info)

                # 当前场景可发现的线索（仅守密人可见）
                for clue_id in scene.clue_ids:
                    for clue in module.clues:
                        if clue.id == clue_id:
                            core_tag = "【核心】" if clue.core else ""
                            parts.append(
                                f"  线索{core_tag}「{clue.name}」：{clue.description}"
                                f"（发现方式：{clue.discovery_method or '自由'}，"
                                f"难度：{clue.discovery_difficulty}）"
                            )
                            break

        # 时间线事件提示（简洁以上模式）
        if verbosity != "极简" and module.timeline:
            upcoming = [
                evt
                for evt in module.timeline
                if evt.trigger_condition  # 有触发条件的事件
            ]
            if upcoming:
                parts.append("时间线提醒：")
                for evt in upcoming[:3]:  # 最多展示3条
                    parts.append(
                        f"  - {evt.trigger_condition}：{evt.description}"
                    )

        return "\n".join(parts)

    def _build_character_context(
        self, investigators: list[Investigator], verbosity: str
    ) -> str:
        """构建角色上下文"""
        if not investigators:
            return ""

        parts: list[str] = []

        for inv in investigators:
            if verbosity == "极简":
                inv_line = (
                    f"{inv.name}：HP {inv.derived.hp}/{inv.derived.hp_max}，"
                    f"SAN {inv.derived.san}/{inv.derived.san_max}，"
                    f"状态 {inv.combat_status.value}"
                )
                if inv.inventory:
                    inv_line += "；持有：" + "、".join(
                        i.name + (f"×{i.quantity}" if i.quantity > 1 else "")
                        for i in inv.inventory[:8]
                    )
                parts.append(inv_line)
            elif verbosity == "简洁":
                # 简洁：基本属性 + 关键状态
                inv_parts = [
                    f"【{inv.name}】{inv.occupation}，{inv.age}岁",
                    f"  HP {inv.derived.hp}/{inv.derived.hp_max}，"
                    f"SAN {inv.derived.san}/{inv.derived.san_max}，"
                    f"MP {inv.derived.mp}/{inv.derived.mp_max}，"
                    f"幸运 {inv.derived.luck}",
                    f"  状态：{inv.combat_status.value}",
                ]
                if inv.insanity.type.value != "无":
                    inv_parts.append(
                        f"  精神状态：{inv.insanity.type.value}"
                        f"（{inv.insanity.description}）"
                    )
                # 主要技能（前5高的）
                top_skills = sorted(
                    inv.skills.items(),
                    key=lambda x: x[1].current,
                    reverse=True,
                )[:5]
                if top_skills:
                    skills_str = "、".join(
                        f"{name} {sv.current}" for name, sv in top_skills
                    )
                    inv_parts.append(f"  主要技能：{skills_str}")
                if inv.inventory:
                    items_s = "、".join(
                        (f"{i.name}（武器 {i.damage}）" if i.is_weapon and i.damage else i.name)
                        + (f"×{i.quantity}" if i.quantity > 1 else "")
                        for i in inv.inventory
                    )
                    inv_parts.append(f"  持有物：{items_s}")
                parts.append("\n".join(inv_parts))
            else:
                # 详细：完整信息
                inv_parts = [
                    f"【{inv.name}】{inv.occupation}，{inv.gender.value}，{inv.age}岁",
                    f"  STR {inv.characteristics.STR} CON {inv.characteristics.CON} "
                    f"SIZ {inv.characteristics.SIZ} DEX {inv.characteristics.DEX}",
                    f"  APP {inv.characteristics.APP} INT {inv.characteristics.INT} "
                    f"POW {inv.characteristics.POW} EDU {inv.characteristics.EDU}",
                    f"  HP {inv.derived.hp}/{inv.derived.hp_max}，"
                    f"SAN {inv.derived.san}/{inv.derived.san_max}，"
                    f"MP {inv.derived.mp}/{inv.derived.mp_max}，"
                    f"幸运 {inv.derived.luck}",
                    f"  伤害加值：{inv.characteristics.damage_bonus}，"
                    f"体格：{inv.characteristics.build}，"
                    f"移动：{inv.derived.mov}",
                    f"  战斗状态：{inv.combat_status.value}",
                ]
                if inv.insanity.type.value != "无":
                    inv_parts.append(
                        f"  精神状态：{inv.insanity.type.value}"
                        f"（{inv.insanity.description}）"
                    )
                # 所有技能
                if inv.skills:
                    skills_str = "、".join(
                        f"{name} {sv.current}"
                        for name, sv in sorted(
                            inv.skills.items(),
                            key=lambda x: x[1].current,
                            reverse=True,
                        )
                    )
                    inv_parts.append(f"  技能：{skills_str}")
                # 武器
                weapons = [item for item in inv.inventory if item.is_weapon]
                if weapons:
                    weapons_str = "、".join(
                        f"{w.name}（{w.damage or '未知'}）" for w in weapons
                    )
                    inv_parts.append(f"  武器：{weapons_str}")
                # 重要物品
                items = [item for item in inv.inventory if not item.is_weapon]
                if items:
                    items_str = "、".join(item.name for item in items)
                    inv_parts.append(f"  物品：{items_str}")
                # 背景
                if inv.personal_description:
                    inv_parts.append(f"  描述：{inv.personal_description}")
                parts.append("\n".join(inv_parts))

        return "\n".join(parts)

    def _build_narrative_context(
        self, recent_narrative: list[NarrativeEntry], max_entries: int = 15
    ) -> str:
        """构建近期叙事上下文"""
        if not recent_narrative:
            return ""

        # 取最近的max_entries条
        entries = recent_narrative[-max_entries:]

        parts: list[str] = []
        for entry in entries:
            source_tag = {
                "narration": "叙事",
                "action": "行动",
                "dice_roll": "骰子",
                "system": "系统",
            }.get(entry.entry_type, entry.entry_type)

            time_str = entry.timestamp.strftime("%H:%M")
            parts.append(f"[{time_str}][{source_tag}] {entry.source}：{entry.content}")

        return "\n".join(parts)

    def _build_summary_context(self, session: GameSession) -> str:
        """构建历史摘要上下文"""
        if not session.narrative_summary:
            return ""
        return session.narrative_summary

    def _estimate_tokens(self, text: str) -> int:
        """估算文本Token数

        混合中英文时的粗略估算。中文字符约1.5 token，
        ASCII字符约0.25 token，这里用字符数/CHARS_PER_TOKEN做统一估算。
        """
        return int(len(text) / self.CHARS_PER_TOKEN)

    def _truncate_to_budget(
        self, sections: list[tuple[str, str, int]], budget: int
    ) -> str:
        """按优先级截断到预算内

        Args:
            sections: [(标题, 内容, 优先级)] 优先级数字越小越重要
            budget: Token预算

        Returns:
            组装好的上下文文本
        """
        # 按优先级排序（数字越小越优先）
        sorted_sections = sorted(sections, key=lambda x: x[2])

        used_tokens = 0
        included: list[str] = []

        for title, content, _priority in sorted_sections:
            # 格式化后的段落：标题行 + 分隔线 + 内容 + 空行
            formatted = f"=== {title} ===\n{content}"
            section_tokens = self._estimate_tokens(formatted)

            if used_tokens + section_tokens <= budget:
                # 完整纳入
                included.append(formatted)
                used_tokens += section_tokens
            else:
                # 剩余预算不够放完整段落，尝试截断放入
                remaining_budget = budget - used_tokens
                if remaining_budget <= 50:
                    # 剩余空间太小，停止
                    break
                # 按剩余预算截断内容
                max_chars = int(remaining_budget * self.CHARS_PER_TOKEN)
                # 保留标题行的开销
                header = f"=== {title}（截断） ===\n"
                header_chars = len(header)
                available_chars = max_chars - header_chars
                if available_chars > 20:
                    truncated_content = content[:available_chars] + "……"
                    included.append(f"{header}{truncated_content}")
                break  # 已经截断，后续低优先级的不再尝试

        return "\n\n".join(included)


async def summarize_narrative(
    narrative_entries: list[NarrativeEntry],
    existing_summary: str = "",
) -> str:
    """将叙事历史压缩为摘要（用于上下文窗口管理）

    当叙事历史超过约50条时调用，将旧条目压缩为摘要。
    此函数会使用Claude API进行压缩。

    Args:
        narrative_entries: 需要压缩的叙事条目列表
        existing_summary: 已有的历史摘要（会与新摘要合并）

    Returns:
        压缩后的摘要文本
    """
    import anthropic

    if not narrative_entries:
        return existing_summary

    # 将叙事条目格式化为文本
    entries_text_parts: list[str] = []
    for entry in narrative_entries:
        source_tag = {
            "narration": "叙事",
            "action": "行动",
            "dice_roll": "骰子",
            "system": "系统",
        }.get(entry.entry_type, entry.entry_type)
        entries_text_parts.append(
            f"[{source_tag}] {entry.source}：{entry.content}"
        )
    entries_text = "\n".join(entries_text_parts)

    # 构建摘要提示词
    prompt_parts: list[str] = []
    prompt_parts.append(
        "你是一个克苏鲁的呼唤（CoC）TTRPG游戏的记录员。"
        "请将以下游戏叙事记录压缩为一段简洁的摘要，"
        "保留关键情节、重要线索发现、角色状态变化和重要骰子结果。"
        "摘要应该让守密人能快速回忆起发生过什么。"
    )

    if existing_summary:
        prompt_parts.append(f"\n已有的历史摘要：\n{existing_summary}")

    prompt_parts.append(f"\n需要压缩的新叙事记录：\n{entries_text}")

    prompt_parts.append(
        "\n请输出合并后的完整摘要（将已有摘要和新记录整合），"
        "控制在500字以内。只输出摘要本身，不要加任何前缀说明。"
    )

    prompt = "\n".join(prompt_parts)

    _s = get_settings()
    key = _s.effective_anthropic_api_key()
    client = anthropic.AsyncAnthropic(api_key=key)
    model = os.getenv("CLAUDE_MODEL") or _s.llm.default_model

    message = await client.messages.create(
        model=model,
        max_tokens=_s.context.summarize_max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )

    # 提取文本响应
    summary = ""
    for block in message.content:
        if block.type == "text":
            summary += block.text

    return summary.strip()
