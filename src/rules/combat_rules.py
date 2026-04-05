"""战斗规则系统

实现CoC 7版的战斗机制：
- DEX先攻排序
- 攻击解析（格斗/射击）
- 闪避和反击
- 伤害计算
- 重伤判定
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from .dice import roll_dice, roll_d100
from .skill_check import SuccessLevel, _determine_success


@dataclass
class AttackResult:
    """攻击结果"""
    attacker_name: str
    defender_name: str
    attack_skill: str
    attack_value: int
    roll_value: int
    success_level: SuccessLevel
    damage: int = 0
    damage_detail: str = ""
    is_critical: bool = False
    is_fumble: bool = False
    defender_response: Optional[str] = None  # "闪避" / "反击" / None
    defender_roll: Optional[int] = None
    defender_success: Optional[SuccessLevel] = None
    hit_location: str = ""
    is_major_wound: bool = False
    details: str = ""


@dataclass
class CombatRoundSummary:
    """战斗轮摘要"""
    round_number: int
    actions: list[AttackResult] = field(default_factory=list)
    narrative: str = ""


# 常见武器数据：{名称: (伤害表达式, 射程, 每轮攻击次数, 弹药, 故障值)}
MELEE_WEAPONS: dict[str, dict] = {
    "拳头": {"damage": "1d3", "skill": "格斗（斗殴）"},
    "踢": {"damage": "1d4", "skill": "格斗（斗殴）"},
    "头锤": {"damage": "1d4", "skill": "格斗（斗殴）"},
    "小刀": {"damage": "1d4", "skill": "格斗（斗殴）"},
    "大刀/剑": {"damage": "1d8", "skill": "格斗（剑）"},
    "斧头": {"damage": "1d8+1", "skill": "格斗（斧）"},
    "棍棒": {"damage": "1d6", "skill": "格斗（斗殴）"},
    "矛": {"damage": "1d8+1", "skill": "格斗（矛）"},
}

RANGED_WEAPONS: dict[str, dict] = {
    ".32手枪": {
        "damage": "1d8", "skill": "射击（手枪）",
        "range": "15码", "attacks_per_round": 1, "ammo": 6, "malfunction": 100,
    },
    ".45手枪": {
        "damage": "1d10+2", "skill": "射击（手枪）",
        "range": "15码", "attacks_per_round": 1, "ammo": 7, "malfunction": 100,
    },
    ".38手枪": {
        "damage": "1d10", "skill": "射击（手枪）",
        "range": "15码", "attacks_per_round": 1, "ammo": 6, "malfunction": 100,
    },
    "猎枪（双管）": {
        "damage": "2d6+2", "skill": "射击（步枪/霰弹枪）",
        "range": "10/20/50码", "attacks_per_round": 1, "ammo": 2, "malfunction": 100,
    },
    "步枪": {
        "damage": "2d6+4", "skill": "射击（步枪/霰弹枪）",
        "range": "90码", "attacks_per_round": 0.5, "ammo": 5, "malfunction": 100,
    },
}


@dataclass
class FumbleEffect:
    """大失败附加效果"""
    description: str           # 效果描述
    self_damage: int = 0       # 自伤伤害
    drop_weapon: bool = False  # 是否掉落武器
    lose_next_turn: bool = False  # 是否失去下一行动
    weapon_malfunction: bool = False  # 武器故障（射击）


def roll_fumble_effect(is_melee: bool, rng: Optional[random.Random] = None) -> FumbleEffect:
    """掷大失败效果表。

    CoC 7版简化：
    - 近战大失败：摔倒/失去平衡/武器脱手/误伤自己
    - 射击大失败：武器故障/弹药卡壳/误伤友方
    """
    if rng is None:
        rng = random.Random()
    roll = rng.randint(1, 6)

    if is_melee:
        effects = {
            1: FumbleEffect("武器脱手，飞出数米远", drop_weapon=True),
            2: FumbleEffect("失去平衡摔倒，下轮无法行动", lose_next_turn=True),
            3: FumbleEffect("用力过猛扭伤自己", self_damage=rng.randint(1, 3)),
            4: FumbleEffect("武器卡在障碍物上，需要一轮拔出", lose_next_turn=True),
            5: FumbleEffect("大力挥空，撞上坚硬物体", self_damage=rng.randint(1, 4)),
            6: FumbleEffect("滑倒，武器脱手", drop_weapon=True, lose_next_turn=True),
        }
    else:
        effects = {
            1: FumbleEffect("武器故障，需要一轮修复", weapon_malfunction=True, lose_next_turn=True),
            2: FumbleEffect("弹药卡壳", weapon_malfunction=True),
            3: FumbleEffect("后坐力导致手腕扭伤", self_damage=rng.randint(1, 2)),
            4: FumbleEffect("瞄准时走火，暴露位置", lose_next_turn=True),
            5: FumbleEffect("扳机卡住，武器需要维修", weapon_malfunction=True, lose_next_turn=True),
            6: FumbleEffect("弹匣/弹仓脱落", weapon_malfunction=True, lose_next_turn=True),
        }
    return effects[roll]


def resolve_attack(
    attack_skill_value: int,
    damage_expression: str,
    damage_bonus: str = "0",
    is_melee: bool = True,
    bonus_dice: int = 0,
    penalty_dice: int = 0,
    rng: Optional[random.Random] = None,
) -> tuple[SuccessLevel, int, str, Optional[FumbleEffect]]:
    """解析攻击

    Returns:
        (成功等级, 伤害值, 伤害详情, 大失败效果或None)
    """
    if rng is None:
        rng = random.Random()

    roll = roll_d100(bonus=bonus_dice, penalty=penalty_dice, rng=rng)
    success = _determine_success(roll.result, attack_skill_value)

    # --- 大失败：零伤害 + 掷附加效果 ---
    if success == SuccessLevel.FUMBLE:
        fumble = roll_fumble_effect(is_melee, rng)
        detail = f"攻击掷骰{roll.result}，大失败！{fumble.description}"
        if fumble.self_damage > 0:
            detail += f"（自伤{fumble.self_damage}点）"
        return success, 0, detail, fumble

    if success == SuccessLevel.FAILURE:
        return success, 0, f"攻击掷骰{roll.result}，失败", None

    # 计算伤害
    damage_result = roll_dice(damage_expression, rng=rng)
    total_damage = damage_result.total

    # 近战加伤害加值
    if is_melee and damage_bonus != "0":
        if damage_bonus in ("-2", "-1"):
            total_damage = max(0, total_damage + int(damage_bonus))
        else:
            bonus_result = roll_dice(damage_bonus, rng=rng)
            total_damage += bonus_result.total

    # --- 大成功：伤害取最大值 + 额外伤害骰（CoC 7版规则） ---
    if success == SuccessLevel.CRITICAL:
        extra_dmg = roll_dice(damage_expression, rng=rng)
        total_damage = max(total_damage, damage_result.total + extra_dmg.total)
        detail = f"攻击掷骰{roll.result}，大成功！伤害{total_damage}点（含额外伤害骰）"
        return success, max(0, total_damage), detail, None

    # 普通 / 困难 / 极难成功
    bonus_info = ""
    if roll.bonus_dice:
        bonus_info = f"，奖励骰{roll.all_options}"
    elif roll.penalty_dice:
        bonus_info = f"，惩罚骰{roll.all_options}"
    detail = f"攻击掷骰{roll.result}{bonus_info}，伤害{total_damage}点"
    return success, max(0, total_damage), detail, None


def check_major_wound(damage: int, max_hp: int) -> bool:
    """检查是否为重伤

    CoC 7版规则：单次伤害 >= HP上限的一半
    """
    return damage >= max_hp // 2


def calculate_initiative_order(participants: list[dict]) -> list[dict]:
    """计算先攻顺序

    CoC 7版规则：按DEX降序排列

    Args:
        participants: [{id, name, dex, is_surprised}, ...]

    Returns:
        排序后的参与者列表
    """
    return sorted(participants, key=lambda p: p["dex"], reverse=True)


def resolve_dodge(
    dodge_skill: int,
    attack_success: SuccessLevel,
    dodge_count: int = 0,
    rng: Optional[random.Random] = None,
) -> tuple[bool, int, SuccessLevel]:
    """解析闪避

    Args:
        dodge_skill: 闪避技能值
        attack_success: 攻击方的成功等级
        dodge_count: 本轮已闪避次数（第二次及以后闪避技能值减半）
        rng: 随机数生成器

    Returns:
        (是否闪避成功, 掷骰值, 闪避成功等级)
    """
    if rng is None:
        rng = random.Random()

    # 多次闪避递减：第二次及以后闪避技能值减半
    effective_skill = dodge_skill // 2 if dodge_count >= 1 else dodge_skill

    roll = roll_d100(rng=rng)
    dodge_level = _determine_success(roll.result, effective_skill)

    # 闪避成功：闪避等级 >= 攻击等级
    dodged = dodge_level >= attack_success

    return dodged, roll.result, dodge_level


def resolve_fighting_back(
    defender_skill: int,
    attack_success: SuccessLevel,
    damage_expression: str,
    damage_bonus: str = "0",
    rng: Optional[random.Random] = None,
) -> tuple[bool, int, SuccessLevel, int]:
    """解析反击（格斗回击）

    只有近战攻击可以反击。
    反击成功时，反击方对攻击方造成伤害。

    Returns:
        (是否反击成功, 掷骰值, 反击成功等级, 反击伤害)
    """
    if rng is None:
        rng = random.Random()

    roll = roll_d100(rng=rng)
    counter_level = _determine_success(roll.result, defender_skill)

    if counter_level > attack_success:
        # 反击成功：对攻击方造成伤害
        dmg_result = roll_dice(damage_expression, rng=rng)
        total = dmg_result.total
        if damage_bonus != "0":
            if damage_bonus in ("-2", "-1"):
                total = max(0, total + int(damage_bonus))
            else:
                bonus = roll_dice(damage_bonus, rng=rng)
                total += bonus.total
        return True, roll.result, counter_level, max(0, total)
    else:
        return False, roll.result, counter_level, 0
