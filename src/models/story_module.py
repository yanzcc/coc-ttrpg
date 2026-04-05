"""故事模组数据模型

定义模组的标准格式，支持自动生成和导入。
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Difficulty(str, Enum):
    """模组难度"""
    EASY = "简单"
    NORMAL = "普通"
    HARD = "困难"
    DEADLY = "致命"


class ModuleMetadata(BaseModel):
    """模组元数据"""
    title: str
    author: str = ""
    era: str = "1920s"
    player_count_min: int = 1
    player_count_max: int = 6
    estimated_sessions: int = 1  # 预计游戏次数
    difficulty: Difficulty = Difficulty.NORMAL
    summary: str = ""
    tags: list[str] = Field(default_factory=list)


class ModuleNPC(BaseModel):
    """模组中的NPC定义"""
    id: str
    name: str
    age: int = 30
    occupation: str = ""
    description: str = ""
    personality: str = ""
    motivation: str = ""
    secret: str = ""
    dialogue_style: str = ""
    # 简化属性
    stats: dict[str, int] = Field(default_factory=dict)
    skills: dict[str, int] = Field(default_factory=dict)
    # 与调查员的关系
    initial_attitude: str = "中立"


class ModuleLocation(BaseModel):
    """模组中的地点定义"""
    id: str
    name: str
    description: str = ""
    atmosphere: str = ""  # 氛围描述
    clue_ids: list[str] = Field(default_factory=list)  # 此处可发现的线索
    npc_ids: list[str] = Field(default_factory=list)    # 此处的NPC
    connections: dict[str, str] = Field(default_factory=dict)  # {方向: 地点ID}
    events: list[str] = Field(default_factory=list)  # 可能触发的事件描述
    is_starting_location: bool = False


class ModuleClue(BaseModel):
    """模组中的线索定义"""
    id: str
    name: str
    description: str = ""
    core: bool = False        # 是否为核心线索（必须被发现）
    location_id: str = ""
    discovery_method: str = "" # 如何发现（"侦查"、"图书馆使用"等）
    discovery_difficulty: str = "普通"
    leads_to: list[str] = Field(default_factory=list)  # 关联线索/场景ID
    handout_text: Optional[str] = None  # 玩家可见的文档内容


class SceneTransition(BaseModel):
    """场景转换条件"""
    target_scene_id: str
    condition: str = ""  # 触发条件描述
    required_clues: list[str] = Field(default_factory=list)  # 需要发现的线索ID
    auto_trigger: bool = False  # 是否自动触发


class ModuleScene(BaseModel):
    """模组中的场景定义"""
    id: str
    title: str
    description: str = ""     # 守密人阅读的场景描述
    read_aloud: str = ""      # 朗读文本（直接念给玩家听的）
    location_id: str = ""
    npc_ids: list[str] = Field(default_factory=list)
    clue_ids: list[str] = Field(default_factory=list)
    likely_skill_checks: list[str] = Field(default_factory=list)  # 可能的技能检定
    transitions: list[SceneTransition] = Field(default_factory=list)
    is_opening: bool = False   # 是否为开场场景
    is_climax: bool = False    # 是否为高潮场景
    is_ending: bool = False    # 是否为结局场景


class TimelineEvent(BaseModel):
    """时间线事件（调查员不干预时发生）"""
    id: str
    description: str
    trigger_condition: str = ""  # 如"第二天晚上"、"调查员离开后"
    consequences: str = ""       # 事件后果


class EndingCondition(BaseModel):
    """模组结局触发条件（不绑定特定场景）"""
    id: str
    description: str                    # 守密人可读的条件描述
    type: str = "normal"                # normal / bad / secret
    required_clues: list[str] = Field(default_factory=list)   # 需要发现的线索ID
    required_scene: str = ""            # 需要到达的场景ID（可选，空表示任意场景）
    trigger_hint: str = ""              # 给守密人的触发提示（如"当调查员决定离开小镇时"）


class StoryModule(BaseModel):
    """完整的故事模组"""
    metadata: ModuleMetadata
    npcs: list[ModuleNPC] = Field(default_factory=list)
    locations: list[ModuleLocation] = Field(default_factory=list)
    scenes: list[ModuleScene] = Field(default_factory=list)
    clues: list[ModuleClue] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    ending_conditions: list[EndingCondition] = Field(default_factory=list)

    def get_opening_scene(self) -> Optional[ModuleScene]:
        """获取开场场景"""
        for scene in self.scenes:
            if scene.is_opening:
                return scene
        return self.scenes[0] if self.scenes else None

    def get_scene(self, scene_id: str) -> Optional[ModuleScene]:
        for scene in self.scenes:
            if scene.id == scene_id:
                return scene
        return None

    def get_npc(self, npc_id: str) -> Optional[ModuleNPC]:
        for npc in self.npcs:
            if npc.id == npc_id:
                return npc
        return None

    def get_location(self, location_id: str) -> Optional[ModuleLocation]:
        for loc in self.locations:
            if loc.id == location_id:
                return loc
        return None

    def get_core_clues(self) -> list[ModuleClue]:
        """获取所有核心线索"""
        return [c for c in self.clues if c.core]
