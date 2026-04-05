"""LangGraph节点函数

每个节点对应一个Agent或处理步骤。
节点接收当前状态，返回状态更新。
"""

from __future__ import annotations

import re
from typing import Optional

from ..agents.game_master import GameMasterAgent, build_context_prompt
from ..agents.base import BaseAgent
from ..agents.combat import CombatAgent
from ..agents.hierarchical_keeper import UnifiedKP
from ..agents.skill_check import SkillCheckAgent
from ..middleware.token_tracker import TokenTracker
from ..models.game_state import NarrativeEntry, GamePhase, CombatState, CombatParticipant
from ..models.character import Investigator, CombatStatus
from ..rules.skill_check import check_skill, Difficulty, SuccessLevel
from ..rules.sanity import check_sanity, roll_temporary_insanity, roll_indefinite_insanity
from ..rules.combat_rules import (
    resolve_attack, resolve_dodge, resolve_fighting_back,
    check_major_wound, calculate_initiative_order, MELEE_WEAPONS,
)
from ..rules.health import apply_damage, apply_first_aid, major_wound_con_check
from .state import (
    GraphState, ActionType, SkillCheckRequest, SanityCheckRequest,
)

# 机制标记正则
SKILL_CHECK_PATTERN = re.compile(r'【技能检定：([^/】]+)(?:/(\w+))?】')
SANITY_CHECK_PATTERN = re.compile(r'【理智检定：([^/】]+)/([^】]+)】')
COMBAT_PATTERN = re.compile(r'【进入战斗】')

# Token追踪器缓存
_trackers: dict[str, TokenTracker] = {}


def _get_tracker(session_id: str) -> TokenTracker:
    if session_id not in _trackers:
        _trackers[session_id] = TokenTracker(session_id)
    return _trackers[session_id]


def _success_cn(level: SuccessLevel) -> str:
    return {
        SuccessLevel.FUMBLE: "大失败",
        SuccessLevel.FAILURE: "失败",
        SuccessLevel.REGULAR: "普通成功",
        SuccessLevel.HARD: "困难成功",
        SuccessLevel.EXTREME: "极难成功",
        SuccessLevel.CRITICAL: "大成功",
    }.get(level, str(level))


# === 节点函数 ===


async def classify_action_node(state: GraphState) -> dict:
    """行动分类节点

    使用守密人Agent的工具调用来分类玩家行动。
    """
    tracker = _get_tracker(state.session_id)
    gm = GameMasterAgent(token_tracker=tracker)

    try:
        classification = await gm.classify_action(
            player_action=state.current_action,
            session=_state_to_session_stub(state),
        )
        action_type = ActionType(classification.get("action_type", "narration"))

        # 如果分类为技能检定，提取技能信息
        pending_checks = []
        if action_type == ActionType.SKILL_CHECK:
            skill_name = classification.get("skill_name", "")
            difficulty = classification.get("difficulty", "普通")
            if skill_name and state.investigators:
                inv_id = list(state.investigators.keys())[0]
                pending_checks.append(SkillCheckRequest(
                    investigator_id=inv_id,
                    skill_name=skill_name,
                    difficulty=difficulty,
                    context=state.current_action,
                ))

        return {
            "action_type": action_type,
            "pending_skill_checks": pending_checks,
        }
    except Exception as e:
        return {"action_type": ActionType.NARRATION, "error": str(e)}


async def gm_narrate_node(state: GraphState) -> dict:
    """守密人叙事节点

    生成叙事回应，并解析其中的机制标记。
    """
    tracker = _get_tracker(state.session_id)
    session_stub = _state_to_session_stub(state)
    investigators = list(state.investigators.values())
    recent = state.narrative_log[-15:] if state.narrative_log else []
    kp = UnifiedKP(token_tracker=tracker)
    target_npc = await kp.route_player_action(state.current_action, session_stub, recent)

    try:
        if target_npc:
            text, usage = await kp.npc_actor.narrate(
                player_action=state.current_action,
                session=session_stub,
                investigators=investigators,
                recent_narrative=recent,
                npc=target_npc,
            )
        else:
            text, usage = await kp.narration.narrate(
                player_action=state.current_action,
                session=session_stub,
                investigators=investigators,
                recent_narrative=recent,
            )

        # 解析叙事中的机制标记
        pending_checks = list(state.pending_skill_checks)
        pending_sanity = list(state.pending_sanity_checks)
        new_phase = state.phase

        for match in SKILL_CHECK_PATTERN.finditer(text):
            skill_name = match.group(1).strip()
            difficulty = (match.group(2) or "普通").strip()
            if state.investigators:
                inv_id = list(state.investigators.keys())[0]
                pending_checks.append(SkillCheckRequest(
                    investigator_id=inv_id,
                    skill_name=skill_name,
                    difficulty=difficulty,
                    context=text,
                ))

        for match in SANITY_CHECK_PATTERN.finditer(text):
            success_loss = match.group(1).strip()
            fail_loss = match.group(2).strip()
            if state.investigators:
                inv_id = list(state.investigators.keys())[0]
                pending_sanity.append(SanityCheckRequest(
                    investigator_id=inv_id,
                    success_loss=success_loss,
                    fail_loss=fail_loss,
                    context=text,
                ))

        if COMBAT_PATTERN.search(text):
            new_phase = GamePhase.COMBAT

        # 清除叙事中的机制标记（已提取）
        clean_text = SKILL_CHECK_PATTERN.sub('', text)
        clean_text = SANITY_CHECK_PATTERN.sub('', clean_text)
        clean_text = COMBAT_PATTERN.sub('', clean_text)
        clean_text = clean_text.strip()

        # 构建广播消息
        messages = [{
            "type": "narrative",
            "data": {"content": clean_text, "source": "守密人", "type": "narration"},
        }]

        # 叙事日志
        entry = NarrativeEntry(
            source="守密人",
            content=clean_text,
            entry_type="narration",
        )

        return {
            "narrative_output": clean_text,
            "pending_skill_checks": pending_checks,
            "pending_sanity_checks": pending_sanity,
            "phase": new_phase,
            "broadcast_messages": messages,
            "narrative_log": state.narrative_log + [entry],
        }
    except Exception as e:
        return {
            "narrative_output": "",
            "error": f"守密人Agent错误：{str(e)}",
            "broadcast_messages": [{
                "type": "system",
                "data": {"content": f"守密人Agent出错：{str(e)}"},
            }],
        }


async def skill_check_node(state: GraphState) -> dict:
    """技能检定节点

    处理所有待处理的技能检定，使用纯Python规则引擎。
    """
    results = list(state.mechanic_results)
    messages = list(state.broadcast_messages)
    investigators = dict(state.investigators)
    log = list(state.narrative_log)
    tracker = _get_tracker(state.session_id)
    sk_agent = SkillCheckAgent(token_tracker=tracker)

    scene_bits: list[str] = []
    if state.current_scene:
        cs = state.current_scene
        scene_bits.append(
            f"{cs.name} {(cs.description or '')[:400]} {(cs.atmosphere or '')[:200]}"
        )
    for e in state.narrative_log[-4:]:
        scene_bits.append(e.content[:180])
    scene_hint = "\n".join(scene_bits)

    for req in state.pending_skill_checks:
        inv = investigators.get(req.investigator_id)
        if not inv:
            continue

        skill_val = inv.skills.get(req.skill_name)
        if not skill_val:
            # 技能不存在，使用默认基础值1
            current_val = 1
        else:
            current_val = skill_val.current

        difficulty_map = {
            "普通": Difficulty.REGULAR,
            "困难": Difficulty.HARD,
            "极难": Difficulty.EXTREME,
        }
        difficulty_str = (req.difficulty or "普通").strip()
        if difficulty_str == "普通":
            try:
                difficulty_str = await sk_agent.suggest_difficulty(
                    req.skill_name,
                    state.current_action,
                    scene_hint,
                )
            except Exception:
                pass
        difficulty = difficulty_map.get(difficulty_str, Difficulty.REGULAR)

        result = check_skill(
            skill_name=req.skill_name,
            skill_value=current_val,
            difficulty=difficulty,
            bonus_dice=req.bonus_dice,
            penalty_dice=req.penalty_dice,
        )

        flavor = ""
        try:
            flavor = await sk_agent.narrate_result(
                result, inv.name, context=scene_hint[:900],
            )
        except Exception:
            pass

        result_data = {
            "type": "skill_check",
            "investigator": inv.name,
            "investigator_id": req.investigator_id,
            "skill": req.skill_name,
            "value": current_val,
            "target": result.target,
            "roll": result.roll.result,
            "success_level": result.success_level.name,
            "succeeded": result.succeeded,
            "can_push": result.can_push,
            "difficulty_used": difficulty_str,
        }
        results.append(result_data)

        detail = (
            f"🎲 {inv.name} 的{req.skill_name}检定"
            f"（{difficulty_str}，目标 {result.target}）"
            f"：掷出 {result.roll.result}"
            f" — {_success_cn(result.success_level)}"
        )
        if flavor:
            detail += "\n" + flavor
        messages.append({
            "type": "dice_result",
            "data": {**result_data, "detail": detail},
        })

        entry = NarrativeEntry(
            source="系统",
            content=detail,
            entry_type="dice_roll",
        )
        log.append(entry)

        # 经验标记：成功的检定标记经验
        if result.succeeded and skill_val:
            skill_val.experience_check = True
            investigators[req.investigator_id] = inv

    return {
        "mechanic_results": results,
        "broadcast_messages": messages,
        "pending_skill_checks": [],  # 清空已处理
        "investigators": investigators,
        "narrative_log": log,
    }


async def sanity_check_node(state: GraphState) -> dict:
    """理智检定节点"""
    results = list(state.mechanic_results)
    messages = list(state.broadcast_messages)
    investigators = dict(state.investigators)
    log = list(state.narrative_log)

    for req in state.pending_sanity_checks:
        inv = investigators.get(req.investigator_id)
        if not inv:
            continue

        result = check_sanity(
            current_san=inv.derived.san,
            success_loss=req.success_loss,
            fail_loss=req.fail_loss,
            san_max=inv.derived.san_max,
            int_value=inv.characteristics.INT,
        )

        # 更新调查员SAN
        inv.derived.san = result.new_san
        if result.triggered_permanent:
            from ..models.character import InsanityType, InsanityStatus
            inv.insanity = InsanityStatus(type=InsanityType.PERMANENT)
        elif result.triggered_indefinite:
            from ..models.character import InsanityType, InsanityStatus
            insanity = roll_indefinite_insanity()
            inv.insanity = InsanityStatus(
                type=InsanityType.INDEFINITE,
                description=insanity.symptom,
            )
        elif result.triggered_temporary:
            from ..models.character import InsanityType, InsanityStatus
            insanity = roll_temporary_insanity()
            inv.insanity = InsanityStatus(
                type=InsanityType.TEMPORARY,
                description=insanity.symptom,
                duration_rounds=insanity.duration_rounds,
            )

        investigators[req.investigator_id] = inv

        result_data = {
            "type": "sanity_check",
            "investigator": inv.name,
            "roll": result.roll_value,
            "succeeded": result.succeeded,
            "san_lost": result.san_lost,
            "new_san": result.new_san,
            "temporary_insanity": result.triggered_temporary,
            "indefinite_insanity": result.triggered_indefinite,
            "permanent_insanity": result.triggered_permanent,
        }
        results.append(result_data)

        detail = f"🧠 {inv.name} 的理智检定：{result.details}"
        if result.triggered_temporary:
            detail += f"\n⚠️ 临时疯狂！{inv.insanity.description}"
        elif result.triggered_indefinite:
            detail += f"\n⚠️ 不定期疯狂！{inv.insanity.description}"
        elif result.triggered_permanent:
            detail += "\n💀 永久疯狂！调查员彻底疯狂了。"

        messages.append({
            "type": "dice_result",
            "data": {**result_data, "detail": detail},
        })
        log.append(NarrativeEntry(source="系统", content=detail, entry_type="dice_roll"))

    return {
        "mechanic_results": results,
        "broadcast_messages": messages,
        "pending_sanity_checks": [],
        "investigators": investigators,
        "narrative_log": log,
    }


async def combat_node(state: GraphState) -> dict:
    """战斗轮节点

    管理战斗流程：先攻排序、攻击解析、伤害计算。
    """
    messages = list(state.broadcast_messages)
    investigators = dict(state.investigators)
    log = list(state.narrative_log)
    combat = state.combat

    # 初始化战斗
    if combat is None and state.phase == GamePhase.COMBAT:
        participants = []
        for inv_id, inv in investigators.items():
            if inv.is_alive and inv.is_conscious:
                participants.append(CombatParticipant(
                    id=inv_id,
                    is_player=True,
                    name=inv.name,
                    dex=inv.characteristics.DEX,
                ))
        # 加入敌方NPC
        for npc_id, npc in state.npcs.items():
            if npc.is_alive and npc.is_present:
                participants.append(CombatParticipant(
                    id=npc_id,
                    is_player=False,
                    name=npc.name,
                    dex=npc.stats.get("DEX", 50),
                ))

        combat = CombatState(round_number=1, participants=participants)
        combat.sort_by_dex()

        detail = (
            f"⚔️ 战斗开始！第{combat.round_number}轮\n"
            f"行动顺序：{'、'.join(p.name for p in combat.participants)}"
        )
        messages.append({"type": "system", "data": {"content": detail}})
        log.append(NarrativeEntry(source="系统", content=detail, entry_type="system"))

    # 处理战斗行动
    for action in state.pending_combat_actions:
        if combat is None:
            break

        participant = next((p for p in combat.participants if p.id == action.participant_id), None)
        if not participant:
            continue

        if action.action_type == "attack" and action.target_id:
            # 解析攻击
            weapon_data = MELEE_WEAPONS.get(action.weapon or "拳头", MELEE_WEAPONS["拳头"])
            attacker_inv = investigators.get(action.participant_id)
            skill_val = 25  # 默认格斗
            damage_bonus = "0"

            if attacker_inv:
                skill = attacker_inv.skills.get(weapon_data["skill"])
                if skill:
                    skill_val = skill.current
                damage_bonus = attacker_inv.characteristics.damage_bonus

            success, damage, detail_str, _fumble = resolve_attack(
                attack_skill_value=skill_val,
                damage_expression=weapon_data["damage"],
                damage_bonus=damage_bonus,
                is_melee=True,
            )

            roll_m = re.search(r"攻击掷骰(\d+)", detail_str)
            roll_val = int(roll_m.group(1)) if roll_m else 0
            def_name = "目标"
            if action.target_id in investigators:
                def_name = investigators[action.target_id].name
            elif action.target_id and action.target_id in state.npcs:
                def_name = state.npcs[action.target_id].name
            weapon_label = action.weapon or "拳头"
            flavor = ""
            try:
                ca = CombatAgent(token_tracker=_get_tracker(state.session_id))
                ctx_bits = [e.content[:120] for e in log[-3:]]
                flavor = await ca.narrate_attack(
                    attacker=participant.name,
                    defender=def_name,
                    weapon=weapon_label,
                    roll_value=roll_val,
                    success_level=_success_cn(success),
                    damage=damage if success >= SuccessLevel.REGULAR else 0,
                    context="\n".join(ctx_bits),
                )
            except Exception:
                pass

            if success >= SuccessLevel.REGULAR and damage > 0:
                # 应用伤害给目标
                target_inv = investigators.get(action.target_id)
                if target_inv:
                    dmg_result = apply_damage(
                        damage=damage,
                        current_hp=target_inv.derived.hp,
                        max_hp=target_inv.derived.hp_max,
                        already_major_wound=target_inv.combat_status == CombatStatus.MAJOR_WOUND,
                    )
                    target_inv.derived.hp = dmg_result.hp_after
                    if dmg_result.is_dead:
                        target_inv.combat_status = CombatStatus.DEAD
                    elif dmg_result.is_dying:
                        target_inv.combat_status = CombatStatus.DYING
                    elif dmg_result.triggered_major_wound:
                        target_inv.combat_status = CombatStatus.MAJOR_WOUND
                    investigators[action.target_id] = target_inv

                    detail_str += f" → {target_inv.name} {dmg_result.details}"

            combat_detail = f"⚔️ {participant.name} 攻击：{detail_str}"
            if flavor:
                combat_detail += "\n" + flavor
            messages.append({"type": "combat", "data": {"content": combat_detail}})
            log.append(NarrativeEntry(source="系统", content=combat_detail, entry_type="dice_roll"))

        participant.has_acted = True

        # 检查是否所有人都行动完毕
        if combat.all_acted:
            combat.round_number += 1
            for p in combat.participants:
                p.has_acted = False
                p.dodge_used = False
            combat.current_turn_index = 0

            # 检查战斗是否结束（所有敌方倒下）
            enemies_alive = any(
                not p.is_player and p.id in state.npcs and state.npcs[p.id].is_alive
                for p in combat.participants
            )
            players_alive = any(
                p.is_player and p.id in investigators and investigators[p.id].is_alive
                for p in combat.participants
            )

            if not enemies_alive or not players_alive:
                result = "调查员获胜" if players_alive else "调查员落败"
                end_msg = f"⚔️ 战斗结束！{result}"
                messages.append({"type": "system", "data": {"content": end_msg}})
                log.append(NarrativeEntry(source="系统", content=end_msg, entry_type="system"))
                combat = None
                return {
                    "combat": None,
                    "phase": GamePhase.EXPLORATION,
                    "pending_combat_actions": [],
                    "investigators": investigators,
                    "broadcast_messages": messages,
                    "narrative_log": log,
                }

    return {
        "combat": combat,
        "pending_combat_actions": [],
        "investigators": investigators,
        "broadcast_messages": messages,
        "narrative_log": log,
    }


async def update_characters_node(state: GraphState) -> dict:
    """角色状态更新节点

    同步角色状态到持久化存储。
    广播角色卡更新给前端。
    """
    messages = list(state.broadcast_messages)

    # 为每个调查员广播角色卡更新
    for inv_id, inv in state.investigators.items():
        messages.append({
            "type": "character_sheet",
            "data": inv.model_dump(mode="json"),
            "target_player": inv.player_id,
        })

    return {
        "broadcast_messages": messages,
        "turn_count": state.turn_count + 1,
    }


# === 辅助函数 ===

def _state_to_session_stub(state: GraphState):
    """将GraphState转换为GameSession的简化版本（供Agent使用）"""
    from ..models.game_state import GameSession
    return GameSession(
        id=state.session_id,
        phase=state.phase,
        module_id=state.module_id,
        current_scene=state.current_scene,
        scenes=state.scenes,
        npcs=state.npcs,
        clues=state.clues,
        combat=state.combat,
        narrative_summary=state.narrative_summary,
        narrative_log=state.narrative_log,
        keeper_memory=state.keeper_memory,
    )
