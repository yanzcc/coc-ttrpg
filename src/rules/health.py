"""生命值管理系统

实现CoC 7版的生命值机制：
- 受伤与伤害应用
- 重伤判定与后果
- 濒死状态与CON检定
- 急救与医学治疗
- 自然恢复
- 死亡判定
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .dice import roll_d100, roll_dice
from .skill_check import check_skill, SuccessLevel, Difficulty


class WoundType(str, Enum):
    """伤害类型"""
    NORMAL = "普通"
    MAJOR = "重伤"         # 单次伤害 >= HP上限/2


class HealingType(str, Enum):
    """治疗类型"""
    FIRST_AID = "急救"
    MEDICINE = "医学"
    NATURAL = "自然恢复"


@dataclass
class DamageResult:
    """伤害应用结果"""
    damage: int                    # 实际造成的伤害
    wound_type: WoundType          # 伤害类型
    hp_before: int                 # 受伤前HP
    hp_after: int                  # 受伤后HP
    is_dying: bool                 # 是否进入濒死
    is_dead: bool                  # 是否直接死亡
    is_unconscious: bool           # 是否昏迷
    triggered_major_wound: bool    # 是否触发重伤
    details: str = ""


@dataclass
class HealingResult:
    """治疗结果"""
    healing_type: HealingType
    healer_roll: Optional[int] = None
    healer_success: Optional[SuccessLevel] = None
    hp_restored: int = 0
    hp_before: int = 0
    hp_after: int = 0
    stabilized: bool = False       # 是否止住了濒死出血
    succeeded: bool = False
    details: str = ""


@dataclass
class DyingCheckResult:
    """濒死检定结果（CON检定）"""
    con_value: int
    roll_value: int
    succeeded: bool                # 成功则暂时稳定
    rounds_remaining: Optional[int] = None  # 距离死亡的轮数
    details: str = ""


def apply_damage(
    damage: int,
    current_hp: int,
    max_hp: int,
    already_major_wound: bool = False,
) -> DamageResult:
    """应用伤害

    CoC 7版规则：
    - HP降至0：濒死状态，每轮需CON检定，失败则死亡
    - HP降至负数且绝对值 >= max_hp：立即死亡
    - 单次伤害 >= max_hp/2：重伤
      - 重伤需CON检定，失败则昏迷
      - 已有重伤的角色不需要再次检定

    Args:
        damage: 伤害值
        current_hp: 当前HP
        max_hp: HP上限
        already_major_wound: 是否已处于重伤状态

    Returns:
        DamageResult
    """
    if damage <= 0:
        return DamageResult(
            damage=0, wound_type=WoundType.NORMAL,
            hp_before=current_hp, hp_after=current_hp,
            is_dying=False, is_dead=False, is_unconscious=False,
            triggered_major_wound=False, details="无伤害",
        )

    hp_after = current_hp - damage
    is_major = damage >= max_hp // 2
    wound_type = WoundType.MAJOR if is_major else WoundType.NORMAL

    # 死亡判定：HP降至负数且绝对值 >= max_hp
    is_dead = hp_after < 0 and abs(hp_after) >= max_hp

    # 濒死判定：HP <= 0 且未直接死亡
    is_dying = hp_after <= 0 and not is_dead

    # 昏迷：HP <= 0 自动昏迷
    is_unconscious = hp_after <= 0

    # HP不低于 -(max_hp - 1)，因为更低就直接死亡了
    if not is_dead:
        hp_after = max(hp_after, -(max_hp - 1))

    details_parts = [f"受到{damage}点伤害"]
    if is_major:
        details_parts.append("重伤！")
    details_parts.append(f"HP: {current_hp} -> {hp_after}")
    if is_dead:
        details_parts.append("角色死亡")
    elif is_dying:
        details_parts.append("角色濒死，需要立即急救")
    elif is_unconscious:
        details_parts.append("角色昏迷")

    return DamageResult(
        damage=damage,
        wound_type=wound_type,
        hp_before=current_hp,
        hp_after=hp_after,
        is_dying=is_dying,
        is_dead=is_dead,
        is_unconscious=is_unconscious,
        triggered_major_wound=is_major and not already_major_wound,
        details="；".join(details_parts),
    )


def major_wound_con_check(
    con_value: int,
    rng: Optional[random.Random] = None,
) -> tuple[bool, int]:
    """重伤后的CON检定

    CoC 7版规则：
    - 受到重伤时需进行CON检定
    - 失败则昏迷，持续1d10小时
    - 大失败可能有额外后果（由守密人裁定）

    Returns:
        (是否成功, 掷骰值)
    """
    result = check_skill("体质", con_value, rng=rng)
    return result.succeeded, result.roll.result


def dying_round_check(
    con_value: int,
    penalty_dice: int = 0,
    rng: Optional[random.Random] = None,
) -> DyingCheckResult:
    """濒死轮检定

    CoC 7版规则：
    - 每轮战斗结束（或非战斗时每小时）进行CON检定
    - 成功则暂时稳定（不再流血），但仍处于濒死
    - 失败则HP再减1
    - HP降至负的max_hp时死亡

    Args:
        con_value: 体质值
        penalty_dice: 惩罚骰（受伤严重时可能有）
        rng: 随机数生成器

    Returns:
        DyingCheckResult
    """
    result = check_skill("体质", con_value, penalty_dice=penalty_dice, rng=rng)

    if result.succeeded:
        return DyingCheckResult(
            con_value=con_value,
            roll_value=result.roll.result,
            succeeded=True,
            details=f"CON检定成功（掷出{result.roll.result}，需要<={con_value}），暂时稳定",
        )
    else:
        return DyingCheckResult(
            con_value=con_value,
            roll_value=result.roll.result,
            succeeded=False,
            details=f"CON检定失败（掷出{result.roll.result}，需要<={con_value}），继续流血，HP-1",
        )


def apply_first_aid(
    first_aid_skill: int,
    patient_hp: int,
    patient_max_hp: int,
    patient_is_dying: bool = False,
    rng: Optional[random.Random] = None,
) -> HealingResult:
    """急救

    CoC 7版规则：
    - 急救技能检定
    - 成功恢复1点HP
    - 对濒死角色：成功则稳定伤势（HP恢复到1）
    - 每种伤情只能尝试急救一次
    - 大成功不额外恢复（急救上限就是1点）

    Args:
        first_aid_skill: 急救技能值
        patient_hp: 患者当前HP
        patient_max_hp: 患者HP上限
        patient_is_dying: 患者是否濒死
        rng: 随机数生成器

    Returns:
        HealingResult
    """
    result = check_skill("急救", first_aid_skill, rng=rng)

    if result.succeeded:
        if patient_is_dying:
            # 濒死：稳定到1HP
            new_hp = 1
            return HealingResult(
                healing_type=HealingType.FIRST_AID,
                healer_roll=result.roll.result,
                healer_success=result.success_level,
                hp_restored=new_hp - patient_hp,
                hp_before=patient_hp,
                hp_after=new_hp,
                stabilized=True,
                succeeded=True,
                details=f"急救成功！伤势已稳定，HP恢复到{new_hp}",
            )
        else:
            # 非濒死：恢复1点HP
            new_hp = min(patient_hp + 1, patient_max_hp)
            return HealingResult(
                healing_type=HealingType.FIRST_AID,
                healer_roll=result.roll.result,
                healer_success=result.success_level,
                hp_restored=new_hp - patient_hp,
                hp_before=patient_hp,
                hp_after=new_hp,
                stabilized=False,
                succeeded=True,
                details=f"急救成功，恢复1点HP（{patient_hp} -> {new_hp}）",
            )
    else:
        return HealingResult(
            healing_type=HealingType.FIRST_AID,
            healer_roll=result.roll.result,
            healer_success=result.success_level,
            hp_before=patient_hp,
            hp_after=patient_hp,
            succeeded=False,
            details=f"急救失败（掷出{result.roll.result}，需要<={first_aid_skill}）",
        )


def apply_medicine(
    medicine_skill: int,
    patient_hp: int,
    patient_max_hp: int,
    patient_is_dying: bool = False,
    rng: Optional[random.Random] = None,
) -> HealingResult:
    """医学治疗

    CoC 7版规则：
    - 医学技能检定
    - 成功恢复1d3点HP
    - 对濒死角色：成功则稳定伤势并恢复到1HP
    - 大成功额外恢复（守密人裁定，这里按+1处理）
    - 需要医疗器材，耗时约1小时

    Args:
        medicine_skill: 医学技能值
        patient_hp: 患者当前HP
        patient_max_hp: 患者HP上限
        patient_is_dying: 患者是否濒死
        rng: 随机数生成器

    Returns:
        HealingResult
    """
    if rng is None:
        rng = random.Random()

    result = check_skill("医学", medicine_skill, rng=rng)

    if result.succeeded:
        if patient_is_dying:
            new_hp = 1
            return HealingResult(
                healing_type=HealingType.MEDICINE,
                healer_roll=result.roll.result,
                healer_success=result.success_level,
                hp_restored=new_hp - patient_hp,
                hp_before=patient_hp,
                hp_after=new_hp,
                stabilized=True,
                succeeded=True,
                details=f"医学治疗成功！伤势已稳定，HP恢复到{new_hp}",
            )
        else:
            heal_roll = roll_dice("1d3", rng=rng)
            hp_healed = heal_roll.total
            if result.success_level == SuccessLevel.CRITICAL:
                hp_healed += 1  # 大成功额外+1
            new_hp = min(patient_hp + hp_healed, patient_max_hp)
            actual_healed = new_hp - patient_hp
            return HealingResult(
                healing_type=HealingType.MEDICINE,
                healer_roll=result.roll.result,
                healer_success=result.success_level,
                hp_restored=actual_healed,
                hp_before=patient_hp,
                hp_after=new_hp,
                succeeded=True,
                details=f"医学治疗成功，恢复{actual_healed}点HP（{patient_hp} -> {new_hp}）",
            )
    else:
        return HealingResult(
            healing_type=HealingType.MEDICINE,
            healer_roll=result.roll.result,
            healer_success=result.success_level,
            hp_before=patient_hp,
            hp_after=patient_hp,
            succeeded=False,
            details=f"医学治疗失败（掷出{result.roll.result}，需要<={medicine_skill}）",
        )


def natural_recovery(
    current_hp: int,
    max_hp: int,
    has_major_wound: bool = False,
    rng: Optional[random.Random] = None,
) -> HealingResult:
    """自然恢复（每游戏周）

    CoC 7版规则：
    - 无重伤：每周恢复1d3 HP
    - 有重伤：每周只恢复1 HP
    - 不超过HP上限

    Returns:
        HealingResult
    """
    if rng is None:
        rng = random.Random()

    if current_hp >= max_hp:
        return HealingResult(
            healing_type=HealingType.NATURAL,
            hp_before=current_hp,
            hp_after=current_hp,
            succeeded=True,
            details="HP已满，无需恢复",
        )

    if has_major_wound:
        hp_healed = 1
    else:
        heal_roll = roll_dice("1d3", rng=rng)
        hp_healed = heal_roll.total

    new_hp = min(current_hp + hp_healed, max_hp)
    actual = new_hp - current_hp

    return HealingResult(
        healing_type=HealingType.NATURAL,
        hp_restored=actual,
        hp_before=current_hp,
        hp_after=new_hp,
        succeeded=True,
        details=f"自然恢复{actual}点HP（{current_hp} -> {new_hp}）"
              + ("（重伤状态，恢复减缓）" if has_major_wound else ""),
    )


def check_instant_death(hp_after_damage: int, max_hp: int) -> bool:
    """检查是否立即死亡

    CoC 7版规则：HP降至负数，且绝对值 >= max_hp
    """
    return hp_after_damage < 0 and abs(hp_after_damage) >= max_hp
