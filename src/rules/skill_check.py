"""技能检定系统

实现CoC 7版的技能检定机制：
- 普通/困难/极难成功
- 大失败和大成功
- 孤注一掷（Pushed Roll）
- 对抗检定
- 奖励骰/惩罚骰
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

from .dice import D100Result, roll_d100


class SuccessLevel(IntEnum):
    """成功等级（数值越高越好）"""
    FUMBLE = 0       # 大失败
    FAILURE = 1      # 失败
    REGULAR = 2      # 普通成功
    HARD = 3         # 困难成功
    EXTREME = 4      # 极难成功
    CRITICAL = 5     # 大成功


class Difficulty(IntEnum):
    """难度等级"""
    REGULAR = 1      # 普通：技能值
    HARD = 2         # 困难：技能值/2
    EXTREME = 3      # 极难：技能值/5


@dataclass
class SkillCheckResult:
    """技能检定结果"""
    skill_name: str
    skill_value: int         # 技能值
    difficulty: Difficulty
    target: int              # 实际目标值（考虑难度后）
    roll: D100Result         # 骰子结果
    success_level: SuccessLevel
    is_pushed: bool = False  # 是否为孤注一掷
    can_push: bool = True    # 是否还能孤注一掷

    @property
    def succeeded(self) -> bool:
        return self.success_level >= SuccessLevel.REGULAR

    @property
    def is_fumble(self) -> bool:
        return self.success_level == SuccessLevel.FUMBLE

    @property
    def is_critical(self) -> bool:
        return self.success_level == SuccessLevel.CRITICAL


def _determine_success(roll_value: int, skill_value: int) -> SuccessLevel:
    """判定成功等级

    CoC 7版规则：
    - 01 始终为大成功
    - 技能值 < 50时，96-100为大失败
    - 技能值 >= 50时，100为大失败
    - <= 技能值/5 为极难成功
    - <= 技能值/2 为困难成功
    - <= 技能值 为普通成功
    """
    if roll_value == 1:
        return SuccessLevel.CRITICAL

    # 大失败判定
    if skill_value < 50 and roll_value >= 96:
        return SuccessLevel.FUMBLE
    elif skill_value >= 50 and roll_value == 100:
        return SuccessLevel.FUMBLE

    # 成功等级判定
    if roll_value <= skill_value // 5:
        return SuccessLevel.EXTREME
    elif roll_value <= skill_value // 2:
        return SuccessLevel.HARD
    elif roll_value <= skill_value:
        return SuccessLevel.REGULAR
    else:
        return SuccessLevel.FAILURE


def check_skill(
    skill_name: str,
    skill_value: int,
    difficulty: Difficulty = Difficulty.REGULAR,
    bonus_dice: int = 0,
    penalty_dice: int = 0,
    is_pushed: bool = False,
    rng: Optional[random.Random] = None,
) -> SkillCheckResult:
    """执行技能检定

    Args:
        skill_name: 技能名称
        skill_value: 技能当前值
        difficulty: 难度等级
        bonus_dice: 奖励骰数量
        penalty_dice: 惩罚骰数量
        is_pushed: 是否为孤注一掷
        rng: 随机数生成器

    Returns:
        SkillCheckResult
    """
    roll = roll_d100(bonus=bonus_dice, penalty=penalty_dice, rng=rng)
    raw_level = _determine_success(roll.result, skill_value)

    # 根据难度调整：必须达到相应等级才算成功
    if difficulty == Difficulty.HARD:
        target = skill_value // 2
        if raw_level >= SuccessLevel.HARD:
            success_level = raw_level
        elif raw_level == SuccessLevel.FUMBLE:
            success_level = SuccessLevel.FUMBLE
        else:
            success_level = SuccessLevel.FAILURE
    elif difficulty == Difficulty.EXTREME:
        target = skill_value // 5
        if raw_level >= SuccessLevel.EXTREME:
            success_level = raw_level
        elif raw_level == SuccessLevel.FUMBLE:
            success_level = SuccessLevel.FUMBLE
        else:
            success_level = SuccessLevel.FAILURE
    else:
        target = skill_value
        success_level = raw_level

    return SkillCheckResult(
        skill_name=skill_name,
        skill_value=skill_value,
        difficulty=difficulty,
        target=target,
        roll=roll,
        success_level=success_level,
        is_pushed=is_pushed,
        can_push=not is_pushed and success_level != SuccessLevel.FUMBLE,
    )


@dataclass
class OpposedCheckResult:
    """对抗检定结果"""
    attacker: SkillCheckResult
    defender: SkillCheckResult
    winner: str  # "attacker" / "defender" / "tie"
    margin: int  # 成功等级差

    @property
    def attacker_wins(self) -> bool:
        return self.winner == "attacker"

    @property
    def defender_wins(self) -> bool:
        return self.winner == "defender"


def opposed_check(
    attacker_skill: str,
    attacker_value: int,
    defender_skill: str,
    defender_value: int,
    attacker_bonus: int = 0,
    attacker_penalty: int = 0,
    defender_bonus: int = 0,
    defender_penalty: int = 0,
    rng: Optional[random.Random] = None,
) -> OpposedCheckResult:
    """对抗检定

    CoC 7版规则：
    - 双方各掷一次，比较成功等级
    - 成功等级高的获胜
    - 相同等级时，技能值高的获胜
    - 都失败则平局（通常视为维持现状）

    Args:
        各参数含义见参数名

    Returns:
        OpposedCheckResult
    """
    atk = check_skill(attacker_skill, attacker_value,
                       bonus_dice=attacker_bonus, penalty_dice=attacker_penalty, rng=rng)
    dfn = check_skill(defender_skill, defender_value,
                       bonus_dice=defender_bonus, penalty_dice=defender_penalty, rng=rng)

    margin = int(atk.success_level) - int(dfn.success_level)

    if atk.success_level > dfn.success_level:
        winner = "attacker"
    elif dfn.success_level > atk.success_level:
        winner = "defender"
    elif atk.success_level == SuccessLevel.FAILURE:
        # 双方都失败 -> 平局
        winner = "tie"
    else:
        # 同等级成功 -> 技能值高的获胜
        if attacker_value > defender_value:
            winner = "attacker"
        elif defender_value > attacker_value:
            winner = "defender"
        else:
            winner = "tie"

    return OpposedCheckResult(
        attacker=atk,
        defender=dfn,
        winner=winner,
        margin=margin,
    )
