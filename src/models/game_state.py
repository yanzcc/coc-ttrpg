"""游戏状态数据模型

定义游戏会话的全局状态，包括阶段、场景、所有调查员等。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class GamePhase(str, Enum):
    """游戏阶段"""
    LOBBY = "大厅"           # 等待玩家加入
    EXPLORATION = "探索"     # 自由探索
    SKILL_CHECK = "技能鉴定"  # 正在进行技能检定
    COMBAT = "战斗"          # 战斗轮
    SANITY_EVENT = "理智事件"  # 理智检定/疯狂事件
    NARRATIVE = "叙事"       # 守密人叙事中
    WAITING_FOR_PLAYER = "等待玩家"  # 等待玩家行动
    PAUSED = "暂停"          # 游戏暂停
    ENDED = "结束"           # 游戏结束


class NPC(BaseModel):
    """非玩家角色"""
    id: str
    name: str
    description: str = ""
    is_alive: bool = True
    is_present: bool = False  # 是否在当前场景中
    attitude: str = "中立"    # 对调查员的态度
    stats: dict[str, int] = Field(default_factory=dict)  # 简化的属性
    secret: str = ""          # 守密人可见的秘密信息
    dialogue_notes: str = ""  # 对话风格提示


class Clue(BaseModel):
    """线索"""
    id: str
    name: str
    description: str
    is_discovered: bool = False
    discovered_by: Optional[str] = None  # 发现者的调查员ID
    discovered_at: Optional[datetime] = None
    location_id: Optional[str] = None
    leads_to: list[str] = Field(default_factory=list)  # 关联的线索/场景ID


class SceneState(BaseModel):
    """当前场景状态"""
    id: str
    name: str
    description: str
    location_type: str = ""   # 如"室内"、"户外"、"地下"
    npcs_present: list[str] = Field(default_factory=list)  # NPC ID列表
    clues_available: list[str] = Field(default_factory=list)  # 可发现的线索ID
    clues_discovered: list[str] = Field(default_factory=list)  # 已发现的线索ID
    exits: dict[str, str] = Field(default_factory=dict)  # {方向: 场景ID}
    atmosphere: str = ""      # 氛围描述（供守密人参考）
    events: list[str] = Field(default_factory=list)  # 场景触发的事件


class CombatParticipant(BaseModel):
    """战斗参与者"""
    id: str                   # 调查员ID或NPC ID
    is_player: bool
    name: str
    dex: int                  # 用于先攻排序
    has_acted: bool = False
    is_surprised: bool = False
    dodge_used: bool = False  # 本轮是否已使用闪避


class CombatState(BaseModel):
    """战斗状态"""
    round_number: int = 1
    participants: list[CombatParticipant] = Field(default_factory=list)
    current_turn_index: int = 0
    is_surprise_round: bool = False

    @property
    def current_participant(self) -> Optional[CombatParticipant]:
        if 0 <= self.current_turn_index < len(self.participants):
            return self.participants[self.current_turn_index]
        return None

    @property
    def all_acted(self) -> bool:
        return all(p.has_acted for p in self.participants)

    def sort_by_dex(self):
        """按DEX降序排列先攻顺序"""
        self.participants.sort(key=lambda p: p.dex, reverse=True)


class PendingSkillCheck(BaseModel):
    """待处理的技能检定"""
    investigator_id: str
    skill_name: str
    difficulty: str = "普通"   # 普通/困难/极难
    opposed_by: Optional[str] = None  # 对抗检定的对手
    can_push: bool = True      # 是否允许孤注一掷
    bonus_dice: int = 0        # 奖励骰数量
    penalty_dice: int = 0      # 惩罚骰数量
    context: str = ""          # 检定的上下文描述


class NarrativeEntry(BaseModel):
    """叙事记录条目"""
    timestamp: datetime = Field(default_factory=datetime.now)
    source: str                # "守密人"、"系统"、或玩家ID
    content: str
    entry_type: str = "narration"  # narration/action/dice_roll/system
    metadata: dict = Field(default_factory=dict)


class PlayerAction(BaseModel):
    """玩家行动"""
    player_id: str
    investigator_id: str
    action_text: str
    timestamp: datetime = Field(default_factory=datetime.now)
    action_type: Optional[str] = None  # 由路由器分类后填充


class KeeperMemoryState(BaseModel):
    """守密人侧长期记忆：事实、分NPC记忆、地点定稿（持久化在 GameSession 中）。"""

    established_facts: list[str] = Field(
        default_factory=list,
        description="已确立的剧情事实、已给出线索、不可自相矛盾",
    )
    npc_memories: dict[str, list[str]] = Field(
        default_factory=dict,
        description="NPC id -> 该角色所知/本对话中说过的事（短句列表）",
    )
    location_canon: dict[str, str] = Field(
        default_factory=dict,
        description="地点名称 -> 首次定稿的环境描写，后续须一致",
    )

    def to_prompt_block(self) -> str:
        """注入守密人系统上下文的记忆段落。"""
        lines: list[str] = []
        if self.established_facts:
            lines.append("\n# 已确立事实与已公布线索（必须遵守，勿矛盾）")
            for f in self.established_facts[-28:]:
                lines.append(f"- {f}")
        if self.location_canon:
            lines.append("\n# 地点定稿（后续描写须与此一致，勿随意改建筑/方位）")
            for name, desc in list(self.location_canon.items())[-12:]:
                short = desc if len(desc) <= 400 else desc[:400] + "…"
                lines.append(f"- {name}：{short}")
        if self.npc_memories:
            lines.append("\n# 分NPC记忆（扮演各NPC时仅使用该NPC条目；勿编造其未经历的事）")
            for npc_id, bullets in self.npc_memories.items():
                if not bullets:
                    continue
                lines.append(f"- ID「{npc_id}」")
                for b in bullets[-10:]:
                    lines.append(f"  · {b}")
        return "\n".join(lines)


class TokenUsage(BaseModel):
    """Token用量统计"""
    total_input: int = 0
    total_output: int = 0
    cached_input: int = 0
    by_agent: dict[str, dict[str, int]] = Field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.total_input + self.total_output

    @property
    def estimated_cost_usd(self) -> float:
        """估算成本（基于Claude Sonnet定价）"""
        input_cost = (self.total_input - self.cached_input) * 3.0 / 1_000_000
        cached_cost = self.cached_input * 0.3 / 1_000_000
        output_cost = self.total_output * 15.0 / 1_000_000
        return input_cost + cached_cost + output_cost

    def record(self, agent_name: str, input_tokens: int, output_tokens: int,
               cached_tokens: int = 0):
        """记录一次API调用的token用量"""
        self.total_input += input_tokens
        self.total_output += output_tokens
        self.cached_input += cached_tokens
        if agent_name not in self.by_agent:
            self.by_agent[agent_name] = {"input": 0, "output": 0, "cached": 0}
        self.by_agent[agent_name]["input"] += input_tokens
        self.by_agent[agent_name]["output"] += output_tokens
        self.by_agent[agent_name]["cached"] += cached_tokens


class GameSession(BaseModel):
    """游戏会话完整状态"""
    id: str
    name: str = "未命名会话"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # 游戏阶段
    phase: GamePhase = GamePhase.LOBBY
    module_id: Optional[str] = None

    # 场景
    current_scene: Optional[SceneState] = None
    scenes: dict[str, SceneState] = Field(default_factory=dict)

    # 角色
    investigator_ids: list[str] = Field(default_factory=list)
    npcs: dict[str, NPC] = Field(default_factory=dict)

    # 线索
    clues: dict[str, Clue] = Field(default_factory=dict)

    # 战斗
    combat: Optional[CombatState] = None

    # 待处理
    pending_check: Optional[PendingSkillCheck] = None
    pending_actions: dict[str, PlayerAction] = Field(default_factory=dict)

    # 叙事历史
    narrative_log: list[NarrativeEntry] = Field(default_factory=list)
    narrative_summary: str = ""  # 压缩的历史摘要

    # 守密人记忆（避免乱编线索、统一地点、分NPC记忆）
    keeper_memory: KeeperMemoryState = Field(default_factory=KeeperMemoryState)

    # Token用量
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    token_budget: int = 500_000

    @property
    def budget_used_pct(self) -> float:
        if self.token_budget <= 0:
            return 0
        return self.token_usage.total / self.token_budget * 100
