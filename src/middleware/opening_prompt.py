"""模组上下文：开场叙述 + 持续游戏中的模组信息注入。"""

from __future__ import annotations

from typing import Optional

from ..models.game_state import GameSession
from ..models.story_module import StoryModule


OPENING_PLAYER_PROMPT = """【系统指令】游戏刚刚开始，尚无任何调查员行动。
请依据上下文中的【模组导入与开场】材料和【调查员信息】，以守密人身份撰写开场叙述。

# 开场叙述要求
1. **结合调查员身份导入剧情**：根据调查员的职业、背景、人际关系，自然地解释他们为什么会出现在这个故事中。
   例如：记者调查员可能是追踪一条新闻线索；私家侦探可能是接到委托；教授可能收到同事的求助信。
2. **环境与氛围**：用第二人称描写调查员所处的环境、时代感、感官细节。
3. **NPC出场**：如果开场有NPC在场，描写他们的外观、正在做的事（第三人称）。
   NPC的简短开场白（1-2句）可以直接写出；如果NPC需要较长的开场对话，使用【NPC发言：NPC名】标记。
4. **引导行动**：结尾给调查员行动的理由，通过叙事自然引导，不要直接列出选项。
5. **完整呈现**：开场叙述应当是一个完整的场景，不要中途断开。
   叙述模组导入的背景信息、调查员为何卷入、当前面对什么情况——一口气讲完。

# 禁止
- 不要在开场插入技能检定、理智检定或战斗标记（除非导入材料明确要求）
- 不要替调查员做决定或描述他们的内心想法
- 不要编造调查员信息中没有的背景细节"""


def format_module_opening_context(
    module: StoryModule,
    investigators: list | None = None,
) -> str:
    """将模组元数据与开场场景格式化为守密人上下文。"""
    parts: list[str] = []
    meta = module.metadata
    parts.append(f"【模组】{meta.title}（{meta.era}）")
    if meta.author:
        parts.append(f"【作者】{meta.author}")
    if meta.summary:
        parts.append(f"【模组简介】\n{meta.summary}")

    scene = module.get_opening_scene()
    if scene:
        parts.append(f"【开场场景标题】{scene.title}")
        if scene.description:
            parts.append(f"【守密人参考·场景说明】\n{scene.description}")
        if scene.read_aloud:
            parts.append(
                "【导入朗读参考（请改编为自然的第二人称叙事，结合调查员身份重新演绎，勿照搬宣读）】\n"
                + scene.read_aloud
            )
        # 开场NPC提示
        if scene.npc_ids and module.npcs:
            npc_parts = []
            for nid in scene.npc_ids:
                mnpc = module.get_npc(nid)
                if mnpc:
                    desc = f"{mnpc.name}"
                    if mnpc.occupation:
                        desc += f"（{mnpc.occupation}，{mnpc.age}岁）"
                    if mnpc.description:
                        desc += f"：{mnpc.description[:100]}"
                    npc_parts.append(f"  - {desc}")
            if npc_parts:
                parts.append("【开场出现的NPC】\n" + "\n".join(npc_parts))

    # 调查员背景摘要（帮助守密人将调查员融入开场）
    if investigators:
        inv_parts = []
        for inv in investigators:
            line = f"  - {inv.name}（{inv.occupation}，{inv.age}岁）"
            if hasattr(inv, 'personal_description') and inv.personal_description:
                line += f"：{inv.personal_description[:80]}"
            inv_parts.append(line)
        parts.append(
            "【调查员信息——请根据他们的身份和背景，自然地解释他们为何卷入本次事件】\n"
            + "\n".join(inv_parts)
        )

    return "\n\n".join(parts)


def format_free_mode_opening_context(session_name: str) -> str:
    """未加载模组时的最小上下文。"""
    return (
        f"【会话名称】{session_name}\n"
        "当前未加载预设故事模组。请写一段简短的开场白，营造克苏鲁跑团氛围，"
        "邀请调查员描述他们如何登场或开始行动。"
    )


def format_ongoing_module_context(
    module: StoryModule,
    session: GameSession,
) -> str:
    """为持续游戏构建模组上下文（非开场，每轮注入守密人）。

    **仅包含 session 运行时状态中没有的守密人专用指导信息**：
    - 当前场景的守密人参考描述（模组原文，比 session.current_scene.description 更详细）
    - 可能触发的技能检定提示
    - 可用的场景转换及条件
    - 未发现的核心线索（引导用）
    - 时间线事件（主动推进用）
    - 结局场景提示

    NPC 详细信息、已发现线索等已由 build_context_prompt() 从 session 状态注入，
    此处不再重复。
    """
    parts: list[str] = []

    # ---- 当前场景的守密人参考（模组原文，可能比 session 中更丰富） ----
    current_scene_id = session.current_scene.id if session.current_scene else None
    if current_scene_id:
        mscene = module.get_scene(current_scene_id)
        if mscene:
            # 仅当模组有额外守密人参考时才注入
            if mscene.description:
                parts.append(f"【当前场景·守密人参考】\n{mscene.description}")
            if mscene.likely_skill_checks:
                parts.append(
                    "【本场景可能触发的检定】"
                    + "、".join(mscene.likely_skill_checks)
                )
            # 可用转场
            if mscene.transitions:
                trans_lines = []
                for t in mscene.transitions:
                    target = module.get_scene(t.target_scene_id)
                    label = target.title if target else t.target_scene_id
                    cond = f"（条件：{t.condition}）" if t.condition else ""
                    auto = " [自动触发]" if t.auto_trigger else ""
                    trans_lines.append(f"  → {label}{cond}{auto}")
                parts.append("【可能的场景转换】\n" + "\n".join(trans_lines))

    # ---- 未发现的核心线索提示 ----
    discovered_ids = set()
    if session.current_scene:
        discovered_ids = set(session.current_scene.clues_discovered)
    for cid, clue in session.clues.items():
        if clue.is_discovered:
            discovered_ids.add(cid)
    undiscovered_core = [
        c for c in module.get_core_clues()
        if c.id not in discovered_ids
    ]
    if undiscovered_core:
        hints = []
        for c in undiscovered_core:
            method = f"（发现方式：{c.discovery_method}）" if c.discovery_method else ""
            hints.append(f"  - {c.name}{method}")
        parts.append(
            "【尚未发现的核心线索——请通过叙事自然引导调查员发现，切勿直接告知】\n"
            + "\n".join(hints)
        )

    # ---- 时间线事件（条件满足时主动推进） ----
    if module.timeline:
        tl_lines = []
        for ev in module.timeline:
            cond = f"触发：{ev.trigger_condition}" if ev.trigger_condition else ""
            tl_lines.append(f"  - {ev.description}（{cond}）")
        parts.append(
            "【时间线事件——条件满足时守密人应主动推进，不必等玩家询问】\n"
            + "\n".join(tl_lines)
        )

    # ---- 结局引导（每轮注入，不绑定场景） ----
    in_ending_scene = False
    if current_scene_id:
        mscene = module.get_scene(current_scene_id)
        if mscene and mscene.is_ending:
            in_ending_scene = True

    if in_ending_scene:
        # 已经在结局��景：明确要求输出标记
        parts.append(
            "【守密人注意：当前是结局场景。完成结局叙述后请在末尾加上 【模组结束】 标记。"
            "叙述应包含：结局描述、调查员的最终命运暗示、对整个冒险的收束感。"
            "如果模组有多个结局分支，根据调查员之前的行动和发现的线索选择最合适的结局。】"
        )
    else:
        # 不在结局场景：告知守密人什么条件下应该触发结局
        ending_hints = _build_ending_hints(module, session)
        if ending_hints:
            parts.append(ending_hints)

    return "\n\n".join(parts)


def _build_ending_hints(module: StoryModule, session: GameSession) -> str:
    """构建结局条件提示（非结局场景时使用）。

    从三个来源汇总：
    1. module.ending_conditions（显式声明的结局条件）
    2. is_ending 场景的描述（隐含的结局触发）
    3. 时间线末尾事件（时间驱动的结局）
    """
    lines: list[str] = []

    # 来源1：显式结局条件
    if module.ending_conditions:
        for ec in module.ending_conditions:
            tag = {"bad": "（坏结局）", "secret": "（隐藏结局）"}.get(ec.type, "")
            hint = ec.trigger_hint or ec.description
            lines.append(f"  - {hint}{tag}")

    # 来源2：从 is_ending 场景提取条件
    if not module.ending_conditions:
        for scene in module.scenes:
            if scene.is_ending and scene.description:
                # 取描述的前100字作为结局条件暗示
                desc_short = scene.description[:100].split("。")[0]
                lines.append(f"  - 场景「{scene.title}」：{desc_short}")

    # 来源3：时间线最后一个事件（常为终局事件）
    if module.timeline:
        last_ev = module.timeline[-1]
        if last_ev.trigger_condition and any(
            kw in last_ev.description for kw in ("结束", "苏醒", "离去", "死", "封", "游戏")
        ):
            lines.append(f"  - 时间线终点：{last_ev.description}（{last_ev.trigger_condition}）")

    if not lines:
        return ""

    # 检查核心线索发现进度，给守密人提供感知
    core_clues = module.get_core_clues()
    if core_clues:
        discovered_ids = set()
        if session.current_scene:
            discovered_ids = set(session.current_scene.clues_discovered)
        for cid, clue in session.clues.items():
            if clue.is_discovered:
                discovered_ids.add(cid)
        found = sum(1 for c in core_clues if c.id in discovered_ids)
        lines.append(f"  （核心线索进度：{found}/{len(core_clues)}）")

    # 通用脱轨结局条件（所有模组都适用）
    lines.append(
        "  - 【脱轨结局】若调查员明确表示永久离开故事发生的地区（如离开城镇、放弃调查、"
        "拒绝参与冒险），且多次引导后仍无回头意向，守密人应叙述调查员离开后的结果"
        "（如：未解之谜悬而未决、NPC的命运、事件的后续发展），然后使用【模组结束】"
    )

    return (
        "【模组结局条件——当以下任一条件满足时，守密人可在叙事完成后使用 【模组结束】 标记，"
        "不必等待调查员走到特定场景】\n"
        + "\n".join(lines)
    )
