"""调查员角色卡数据模型

基于克苏鲁的呼唤第7版规则，定义调查员的属性、技能、状态等。
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Era(str, Enum):
    """游戏时代"""
    CLASSIC_1920S = "1920s"
    MODERN = "现代"
    GASLIGHT = "煤气灯"
    DARK_AGES = "黑暗时代"


def parse_era(raw: str | None) -> Era:
    """将 API / 前端传入的时代字符串解析为 Era。

    兼容枚举值本身（如 ``1920s``、``现代``）以及常用 slug（与技能表 ``get_skills_for_era`` 一致）：
    ``modern``、``gaslight``、``dark_ages`` 等。
    """
    if raw is None or not str(raw).strip():
        return Era.CLASSIC_1920S
    s = str(raw).strip()
    try:
        return Era(s)
    except ValueError:
        pass
    low = s.lower().replace("-", "_")
    slug: dict[str, Era] = {
        "modern": Era.MODERN,
        "gaslight": Era.GASLIGHT,
        "darkages": Era.DARK_AGES,
        "dark_ages": Era.DARK_AGES,
    }
    if low in slug:
        return slug[low]
    raise ValueError(
        f"无效的时代: {raw!r}；请使用 1920s、modern（现代）、gaslight（煤气灯）"
        f"、dark_ages（黑暗时代）或对应中文枚举值"
    )


class Gender(str, Enum):
    MALE = "男"
    FEMALE = "女"
    OTHER = "其他"


class Characteristics(BaseModel):
    """基础属性（3-18范围，乘以5得到百分比值）"""
    STR: int = Field(ge=1, le=99, description="力量")
    CON: int = Field(ge=1, le=99, description="体质")
    SIZ: int = Field(ge=1, le=99, description="体型")
    DEX: int = Field(ge=1, le=99, description="敏捷")
    APP: int = Field(ge=1, le=99, description="外貌")
    INT: int = Field(ge=1, le=99, description="智力")
    POW: int = Field(ge=1, le=99, description="意志")
    EDU: int = Field(ge=1, le=99, description="教育")

    @property
    def damage_bonus(self) -> str:
        """伤害加值，基于STR+SIZ"""
        total = self.STR + self.SIZ
        if total <= 64:
            return "-2"
        elif total <= 84:
            return "-1"
        elif total <= 124:
            return "0"
        elif total <= 164:
            return "+1d4"
        elif total <= 204:
            return "+1d6"
        else:
            # 每+80 加一个d6
            extra = (total - 204) // 80
            return f"+{2 + extra}d6"

    @property
    def build(self) -> int:
        """体格值"""
        total = self.STR + self.SIZ
        if total <= 64:
            return -2
        elif total <= 84:
            return -1
        elif total <= 124:
            return 0
        elif total <= 164:
            return 1
        elif total <= 204:
            return 2
        else:
            return 2 + (total - 204) // 80

    @property
    def movement_rate(self) -> int:
        """移动速率"""
        if self.DEX < self.SIZ and self.STR < self.SIZ:
            return 7
        elif self.DEX > self.SIZ and self.STR > self.SIZ:
            return 9
        else:
            return 8


class DerivedStats(BaseModel):
    """衍生属性"""
    hp: int = Field(description="生命值")
    hp_max: int = Field(description="生命值上限")
    mp: int = Field(description="魔法值")
    mp_max: int = Field(description="魔法值上限")
    san: int = Field(description="理智值")
    san_max: int = Field(description="理智值上限（99-克苏鲁神话技能）")
    luck: int = Field(description="幸运值")
    mov: int = Field(description="移动速率")

    @classmethod
    def from_characteristics(cls, chars: Characteristics, luck_roll: int) -> DerivedStats:
        """从基础属性计算衍生属性"""
        hp_max = (chars.CON + chars.SIZ) // 10
        mp_max = chars.POW // 5
        return cls(
            hp=hp_max,
            hp_max=hp_max,
            mp=mp_max,
            mp_max=mp_max,
            san=chars.POW,
            san_max=99,
            luck=luck_roll,
            mov=chars.movement_rate,
        )


class SkillValue(BaseModel):
    """技能值"""
    base: int = Field(description="基础值")
    current: int = Field(description="当前值（含成长）")
    experience_check: bool = Field(default=False, description="是否有经验标记")

    @property
    def half(self) -> int:
        """困难成功阈值"""
        return self.current // 2

    @property
    def fifth(self) -> int:
        """极难成功阈值"""
        return self.current // 5


class CombatStatus(str, Enum):
    """战斗状态"""
    NORMAL = "正常"
    MAJOR_WOUND = "重伤"
    UNCONSCIOUS = "昏迷"
    DYING = "濒死"
    DEAD = "死亡"


class InsanityType(str, Enum):
    """疯狂类型"""
    NONE = "无"
    TEMPORARY = "临时疯狂"
    INDEFINITE = "不定期疯狂"
    PERMANENT = "永久疯狂"


class InsanityStatus(BaseModel):
    """疯狂状态"""
    type: InsanityType = InsanityType.NONE
    description: str = ""
    duration_rounds: Optional[int] = None  # 临时疯狂持续轮数
    phobia: Optional[str] = None
    mania: Optional[str] = None


class InventoryItem(BaseModel):
    """物品"""
    name: str
    description: str = ""
    quantity: int = 1
    is_weapon: bool = False
    damage: Optional[str] = None  # 如 "1d6+2"
    skill_name: Optional[str] = None  # 对应武器技能
    uses: Optional[int] = None  # 弹药等有限使用次数
    range: Optional[str] = None  # 射程


class Investigator(BaseModel):
    """调查员角色卡"""
    id: str = Field(description="唯一标识符")
    player_id: str = Field(description="所属玩家ID")
    name: str = Field(description="姓名")
    age: int = Field(ge=15, le=90, description="年龄")
    gender: Gender = Field(description="性别")
    occupation: str = Field(description="职业")
    birthplace: str = Field(default="", description="出生地")
    residence: str = Field(default="", description="居住地")
    era: Era = Field(default=Era.CLASSIC_1920S, description="游戏时代")

    # 属性
    characteristics: Characteristics
    derived: DerivedStats
    skills: dict[str, SkillValue] = Field(default_factory=dict, description="技能表")

    # 状态
    combat_status: CombatStatus = CombatStatus.NORMAL
    insanity: InsanityStatus = Field(default_factory=InsanityStatus)
    mythos_hardened: bool = Field(default=False, description="是否对克苏鲁神话免疫")

    # 物品
    inventory: list[InventoryItem] = Field(default_factory=list)
    cash: float = Field(default=0, description="现金")
    assets: str = Field(default="", description="资产描述")
    spending_level: str = Field(default="", description="消费水平")

    # 背景
    personal_description: str = Field(default="", description="个人描述")
    ideology: str = Field(default="", description="思想/信念")
    significant_people: str = Field(default="", description="重要之人")
    meaningful_locations: str = Field(default="", description="意义非凡之地")
    treasured_possessions: str = Field(default="", description="珍视之物")
    traits: str = Field(default="", description="特质")
    injuries_scars: str = Field(default="", description="伤疤和创伤")
    encounters_with_entities: str = Field(default="", description="与异界存在的遭遇")

    @property
    def is_alive(self) -> bool:
        return self.combat_status != CombatStatus.DEAD

    @property
    def is_conscious(self) -> bool:
        return self.combat_status in (CombatStatus.NORMAL, CombatStatus.MAJOR_WOUND)

    @property
    def cthulhu_mythos(self) -> int:
        """克苏鲁神话技能值"""
        if "克苏鲁神话" in self.skills:
            return self.skills["克苏鲁神话"].current
        return 0
