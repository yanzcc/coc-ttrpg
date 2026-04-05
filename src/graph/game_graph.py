"""LangGraph游戏图定义

定义完整的游戏状态机：节点、边、条件路由。
这是整个系统的核心骨架。
"""

from __future__ import annotations

from typing import Optional

from langgraph.graph import StateGraph, END

from .state import GraphState
from .nodes import (
    classify_action_node,
    gm_narrate_node,
    skill_check_node,
    sanity_check_node,
    combat_node,
    update_characters_node,
)
from .edges import (
    route_after_classify,
    route_after_narrate,
    route_after_skill_check,
    route_after_sanity_check,
    route_after_combat,
)


def build_game_graph() -> StateGraph:
    """构建游戏状态图

    流程：
    classify_action -> gm_narrate -> [skill_check | sanity_check | combat | update_characters]
                                         |               |             |
                                         v               v             v
                                    [sanity_check | combat | update_characters]
                                                                       |
                                                                       v
                                                                      END

    Returns:
        编译好的StateGraph
    """
    graph = StateGraph(GraphState)

    # === 添加节点 ===
    graph.add_node("classify_action", classify_action_node)
    graph.add_node("gm_narrate", gm_narrate_node)
    graph.add_node("skill_check", skill_check_node)
    graph.add_node("sanity_check", sanity_check_node)
    graph.add_node("combat", combat_node)
    graph.add_node("update_characters", update_characters_node)

    # === 入口 ===
    graph.set_entry_point("classify_action")

    # === 条件边 ===
    graph.add_conditional_edges(
        "classify_action",
        route_after_classify,
        {
            "gm_narrate": "gm_narrate",
        },
    )

    graph.add_conditional_edges(
        "gm_narrate",
        route_after_narrate,
        {
            "skill_check": "skill_check",
            "sanity_check": "sanity_check",
            "combat": "combat",
            "update_characters": "update_characters",
        },
    )

    graph.add_conditional_edges(
        "skill_check",
        route_after_skill_check,
        {
            "sanity_check": "sanity_check",
            "combat": "combat",
            "update_characters": "update_characters",
        },
    )

    graph.add_conditional_edges(
        "sanity_check",
        route_after_sanity_check,
        {
            "combat": "combat",
            "update_characters": "update_characters",
        },
    )

    graph.add_conditional_edges(
        "combat",
        route_after_combat,
        {
            "update_characters": "update_characters",
        },
    )

    # === 终点 ===
    graph.add_edge("update_characters", END)

    return graph.compile()


# 编译好的图实例（可重用）
_compiled_graph = None


def get_game_graph():
    """获取编译好的游戏图（单例）"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_game_graph()
    return _compiled_graph
