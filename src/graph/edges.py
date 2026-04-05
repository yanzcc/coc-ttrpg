"""LangGraph条件边逻辑

根据当前状态决定下一步执行哪个节点。
"""

from __future__ import annotations

from ..models.game_state import GamePhase
from .state import GraphState, ActionType


def route_after_classify(state: GraphState) -> str:
    """分类后的路由

    根据action_type决定走哪个分支。
    """
    if state.action_type == ActionType.COMBAT or state.phase == GamePhase.COMBAT:
        return "gm_narrate"  # 战斗中也先让守密人描述

    # 其他类型都先经过守密人叙事
    return "gm_narrate"


def route_after_narrate(state: GraphState) -> str:
    """叙事后的路由

    根据守密人的叙事内容中发现的机制标记决定后续步骤。
    """
    # 有待处理的技能检定
    if state.pending_skill_checks:
        return "skill_check"

    # 有待处理的理智检定
    if state.pending_sanity_checks:
        return "sanity_check"

    # 进入战斗
    if state.phase == GamePhase.COMBAT:
        return "combat"

    # 无机制操作，直接更新角色
    return "update_characters"


def route_after_skill_check(state: GraphState) -> str:
    """技能检定后的路由"""
    # 检定后可能还有理智检定
    if state.pending_sanity_checks:
        return "sanity_check"

    # 战斗中的检定完成后回到战斗
    if state.phase == GamePhase.COMBAT:
        return "combat"

    return "update_characters"


def route_after_sanity_check(state: GraphState) -> str:
    """理智检定后的路由"""
    if state.phase == GamePhase.COMBAT:
        return "combat"

    return "update_characters"


def route_after_combat(state: GraphState) -> str:
    """战斗后的路由"""
    return "update_characters"
