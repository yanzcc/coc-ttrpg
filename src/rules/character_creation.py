"""角色创建规则

实现CoC 7版的角色属性生成和年龄修正系统。
"""

from __future__ import annotations

import random
from typing import Optional

from .dice import roll_dice
from ..models.character import Characteristics, DerivedStats, Era


# 年龄段定义：(最小年龄, 最大年龄, STR/CON/DEX总减少, APP减少, MOV减少, 教育增强次数)
_AGE_BRACKETS: list[tuple[int, int, int, int, int, int]] = [
    (15, 19, 0, 0, 0, 0),    # 特殊处理
    (20, 39, 0, 0, 0, 1),
    (40, 49, 5, 5, 1, 2),
    (50, 59, 10, 10, 2, 3),
    (60, 69, 20, 15, 3, 4),
    (70, 79, 40, 20, 4, 4),
    (80, 89, 80, 25, 5, 4),
]


def _clamp(value: int, low: int = 1, high: int = 99) -> int:
    """将属性值限制在合法范围内"""
    return max(low, min(high, value))


def _distribute_reduction(
    str_val: int, con_val: int, dex_val: int, total_reduction: int
) -> tuple[int, int, int]:
    """将STR/CON/DEX的总减少量尽量均匀分配到三个属性上。

    每个属性最低减到1。分配策略：轮流每次减1，直到减完或所有属性已到下限。
    """
    vals = [str_val, con_val, dex_val]
    remaining = total_reduction

    # 先尝试均匀分配
    base_each = remaining // 3
    extra = remaining % 3

    reductions = [base_each, base_each, base_each]
    # 把余数分配给前extra个属性
    for i in range(extra):
        reductions[i] += 1

    # 检查是否有属性减过头（低于1），如果有则重新分配
    overflow = 0
    for i in range(3):
        max_reducible = vals[i] - 1  # 最多减到1
        if reductions[i] > max_reducible:
            overflow += reductions[i] - max_reducible
            reductions[i] = max_reducible

    # 把溢出部分分配给还有空间的属性
    while overflow > 0:
        distributed = False
        for i in range(3):
            if overflow <= 0:
                break
            max_reducible = vals[i] - 1 - reductions[i]
            if max_reducible > 0:
                take = min(overflow, max_reducible)
                reductions[i] += take
                overflow -= take
                distributed = True
        if not distributed:
            break  # 所有属性都已到下限，无法再减

    return (
        _clamp(vals[0] - reductions[0]),
        _clamp(vals[1] - reductions[1]),
        _clamp(vals[2] - reductions[2]),
    )


def roll_characteristics(rng: Optional[random.Random] = None) -> Characteristics:
    """掷骰生成基础属性

    CoC 7版规则：
    - STR: 3D6 × 5
    - CON: 3D6 × 5
    - SIZ: (2D6+6) × 5
    - DEX: 3D6 × 5
    - APP: 3D6 × 5
    - INT: (2D6+6) × 5
    - POW: 3D6 × 5
    - EDU: (2D6+6) × 5
    """
    if rng is None:
        rng = random.Random()

    def _3d6x5() -> int:
        return roll_dice("3d6", rng=rng).total * 5

    def _2d6p6x5() -> int:
        return roll_dice("2d6+6", rng=rng).total * 5

    return Characteristics(
        STR=_3d6x5(),
        CON=_3d6x5(),
        SIZ=_2d6p6x5(),
        DEX=_3d6x5(),
        APP=_3d6x5(),
        INT=_2d6p6x5(),
        POW=_3d6x5(),
        EDU=_2d6p6x5(),
    )


def apply_age_modifiers(
    chars: Characteristics, age: int
) -> tuple[Characteristics, str]:
    """应用年龄修正

    CoC 7版规则：
    - 15-19岁：力量和体型合计减5，教育减5，幸运骰掷两次取高
    - 20-39岁：无修正（可进行一次教育增强检定）
    - 40-49岁：STR/CON/DEX任选减5，APP减5，MOV减1，教育增强检定两次
    - 50-59岁：STR/CON/DEX任选减10（分配到多个属性），APP减10，MOV减2，教育增强检定三次
    - 60-69岁：STR/CON/DEX任选减20，APP减15，MOV减3，教育增强检定四次
    - 70-79岁：STR/CON/DEX任选减40，APP减20，MOV减4，教育增强检定四次
    - 80-89岁：STR/CON/DEX任选减80，APP减25，MOV减5，教育增强检定四次

    注意：属性最低不能低于1。
    减少STR/CON/DEX时，系统自动均匀分配到三个属性。

    Returns:
        (修正后的属性, 修正说明)
    """
    if age < 15 or age > 89:
        raise ValueError(f"年龄必须在15-89之间，当前为{age}")

    notes: list[str] = []
    str_val = chars.STR
    con_val = chars.CON
    siz_val = chars.SIZ
    dex_val = chars.DEX
    app_val = chars.APP
    edu_val = chars.EDU

    if 15 <= age <= 19:
        # 力量和体型合计减5
        # 均匀分配：STR减3, SIZ减2（或反过来，这里简单处理）
        str_reduce = 3
        siz_reduce = 2
        str_val = _clamp(str_val - str_reduce)
        siz_val = _clamp(siz_val - siz_reduce)
        # 教育减5
        edu_val = _clamp(edu_val - 5)
        notes.append(f"年龄{age}岁（15-19）：STR-{str_reduce}，SIZ-{siz_reduce}，EDU-5，幸运掷两次取高")

    elif 20 <= age <= 39:
        notes.append(f"年龄{age}岁（20-39）：无属性修正，可进行1次教育增强检定")

    else:
        # 40岁以上的统一处理
        for min_age, max_age, phys_reduce, app_reduce, mov_reduce, edu_checks in _AGE_BRACKETS:
            if min_age <= age <= max_age:
                if phys_reduce > 0:
                    old_str, old_con, old_dex = str_val, con_val, dex_val
                    str_val, con_val, dex_val = _distribute_reduction(
                        str_val, con_val, dex_val, phys_reduce
                    )
                    notes.append(
                        f"年龄{age}岁（{min_age}-{max_age}）："
                        f"STR {old_str}->{str_val}，"
                        f"CON {old_con}->{con_val}，"
                        f"DEX {old_dex}->{dex_val}（合计减{phys_reduce}）"
                    )
                if app_reduce > 0:
                    old_app = app_val
                    app_val = _clamp(app_val - app_reduce)
                    notes.append(f"APP {old_app}->{app_val}（减{app_reduce}）")
                if mov_reduce > 0:
                    notes.append(f"MOV减{mov_reduce}（在衍生属性中体现）")
                notes.append(f"可进行{edu_checks}次教育增强检定")
                break

    modified = Characteristics(
        STR=str_val,
        CON=con_val,
        SIZ=siz_val,
        DEX=dex_val,
        APP=app_val,
        INT=chars.INT,
        POW=chars.POW,
        EDU=edu_val,
    )
    return modified, "；".join(notes)


def education_improvement_check(
    current_edu: int,
    rng: Optional[random.Random] = None,
) -> int:
    """教育增强检定

    掷1d100，如果结果 > 当前EDU值，则EDU增加1d10（不超过99）。

    Returns:
        新的EDU值
    """
    if rng is None:
        rng = random.Random()

    check_roll = roll_dice("1d100", rng=rng).total
    if check_roll > current_edu:
        improvement = roll_dice("1d10", rng=rng).total
        return min(99, current_edu + improvement)
    return current_edu


def roll_luck(rng: Optional[random.Random] = None) -> int:
    """掷幸运值

    3D6 × 5
    """
    if rng is None:
        rng = random.Random()
    return roll_dice("3d6", rng=rng).total * 5


def generate_investigator_stats(
    age: int = 30,
    rng: Optional[random.Random] = None,
) -> tuple[Characteristics, int, str]:
    """生成完整的调查员属性

    组合掷骰、年龄修正、教育增强。

    Returns:
        (最终属性, 幸运值, 修正说明)
    """
    if rng is None:
        rng = random.Random()

    # 1. 掷基础属性
    chars = roll_characteristics(rng=rng)

    # 2. 应用年龄修正
    chars, notes = apply_age_modifiers(chars, age)

    # 3. 确定教育增强次数
    if 15 <= age <= 19:
        edu_checks = 0
    elif 20 <= age <= 39:
        edu_checks = 1
    elif 40 <= age <= 49:
        edu_checks = 2
    elif 50 <= age <= 59:
        edu_checks = 3
    else:
        edu_checks = 4  # 60-89

    # 4. 执行教育增强检定
    edu_val = chars.EDU
    improvements = 0
    for _ in range(edu_checks):
        new_edu = education_improvement_check(edu_val, rng=rng)
        if new_edu > edu_val:
            improvements += 1
        edu_val = new_edu

    if improvements > 0:
        chars = chars.model_copy(update={"EDU": edu_val})
        notes += f"；教育增强{improvements}次，EDU最终为{edu_val}"

    # 5. 掷幸运值（15-19岁掷两次取高）
    luck = roll_luck(rng=rng)
    if 15 <= age <= 19:
        luck2 = roll_luck(rng=rng)
        luck = max(luck, luck2)

    return chars, luck, notes
