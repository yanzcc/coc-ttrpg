"""LangGraph游戏状态定义

定义流经图节点的状态类型，所有Agent通过读写此状态进行通信。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Optional, Any

from pydantic import BaseModel, Field

from ..models.character import Investigator
from ..models.game_state import (
    GamePhase, SceneState, NPC, Clue,
    CombatState, PendingSkillCheck, NarrativeEntry, PlayerAction,
    KeeperMemoryState,
)


class ActionType(str, Enum):
    """行动分类结果"""
    NARRATION = "narration"         # 纯叙事/对话
    SKILL_CHECK = "skill_check"     # 需要技能检定
    COMBAT = "combat"               # 战斗相关
    SANITY = "sanity"               # 理智相关
    CHARACTER = "character"         # 角色管理（查看属性、物品等）
    INVESTIGATION = "investigation" # 调查（搜索线索、询问NPC等）


class SkillCheckRequest(BaseModel):
    """技能检定请求"""
    investigator_id: str
    skill_name: str
    difficulty: str = "普通"
    bonus_dice: int = 0
    penalty_dice: int = 0
    context: str = ""               # 检定的叙事上下文
    can_push: bool = True


class SanityCheckRequest(BaseModel):
    """理智检定请求"""
    investigator_id: str
    success_loss: str               # 如 "0", "1", "1d3"
    fail_loss: str                  # 如 "1d6", "2d6"
    context: str = ""               # 触发原因


class CombatAction(BaseModel):
    """战斗行动"""
    participant_id: str
    action_type: str                # attack/dodge/fight_back/flee/use_item
    target_id: Optional[str] = None
    weapon: Optional[str] = None
    detail: str = ""


class GraphState(BaseModel):
    """LangGraph图状态

    所有节点共享此状态，通过读写字段进行通信。
    每次节点执行后返回需要更新的字段。
    """
    # === 会话基础信息 ===
    session_id: str
    phase: GamePhase = GamePhase.EXPLORATION
    module_id: Optional[str] = None

    # === 当前输入 ===
    current_player_id: str = ""
    current_action: str = ""
    action_type: ActionType = ActionType.NARRATION

    # === 场景 ===
    current_scene: Optional[SceneState] = None
    scenes: dict[str, SceneState] = Field(default_factory=dict)

    # === 角色 ===
    investigators: dict[str, Investigator] = Field(default_factory=dict)
    npcs: dict[str, NPC] = Field(default_factory=dict)

    # === 线索 ===
    clues: dict[str, Clue] = Field(default_factory=dict)

    # === 待处理的机制请求 ===
    pending_skill_checks: list[SkillCheckRequest] = Field(default_factory=list)
    pending_sanity_checks: list[SanityCheckRequest] = Field(default_factory=list)
    pending_combat_actions: list[CombatAction] = Field(default_factory=list)

    # === 战斗状态 ===
    combat: Optional[CombatState] = None

    # === 输出缓冲 ===
    narrative_output: str = ""          # 守密人生成的叙事
    mechanic_results: list[dict] = Field(default_factory=list)  # 机制检定结果
    broadcast_messages: list[dict] = Field(default_factory=list)  # 待广播消息

    # === 历史 ===
    narrative_log: list[NarrativeEntry] = Field(default_factory=list)
    narrative_summary: str = ""

    # === 守密人记忆（与 GameSession.keeper_memory 同步） ===
    keeper_memory: KeeperMemoryState = Field(default_factory=KeeperMemoryState)

    # === 元信息 ===
    turn_count: int = 0
    error: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True
