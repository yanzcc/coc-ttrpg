"""幸运系统

实现CoC 7版的幸运机制：
- 幸运消耗（修改骰点）
- 团体幸运
- 幸运恢复
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from .dice import roll_d100


@dataclass
class LuckSpendResult:
    """幸运消耗结果"""
    original_roll: int       # 原始掷骰值
    points_spent: int        # 消耗的幸运点数
    modified_roll: int       # 修改后的掷骰值
    remaining_luck: int      # 剩余幸运值
    success: bool            # 修改后是否成功


def spend_luck(
    original_roll: int,
    target: int,
    current_luck: int,
    is_fumble: bool = False,
) -> Optional[LuckSpendResult]:
    """消耗幸运修改掷骰结果

    CoC 7版规则：
    - 玩家可以在技能检定失败后消耗幸运点
    - 每消耗1点幸运，掷骰结果降低1
    - 不能用于战斗掷骰和理智检定（这个限制在调用层面控制）
    - 大失败不能通过幸运修改

    Args:
        original_roll: 原始掷骰值
        target: 目标值（需要掷出<=此值才成功）
        current_luck: 当前幸运值
        is_fumble: 是否为大失败

    Returns:
        LuckSpendResult 如果可以消耗，否则None
    """
    # 大失败不能通过幸运修改
    if is_fumble:
        return None

    # 已经成功了，不需要消耗
    if original_roll <= target:
        return None

    points_needed = original_roll - target
    if points_needed > current_luck:
        return None  # 幸运不够

    return LuckSpendResult(
        original_roll=original_roll,
        points_spent=points_needed,
        modified_roll=target,
        remaining_luck=current_luck - points_needed,
        success=True,
    )


@dataclass
class GroupLuckResult:
    """团体幸运检定结果"""
    roller_name: str
    roll_value: int
    luck_value: int
    succeeded: bool


def group_luck_check(
    investigators: list[dict],
    rng: Optional[random.Random] = None,
) -> GroupLuckResult:
    """团体幸运检定

    CoC 7版规则：
    - 由幸运值最低的调查员掷骰
    - 掷d100 <= 该调查员的幸运值为成功

    Args:
        investigators: [{name, luck}, ...]
        rng: 随机数生成器

    Returns:
        GroupLuckResult
    """
    if rng is None:
        rng = random.Random()

    if not investigators:
        raise ValueError("没有调查员参与团体幸运检定")

    # 找幸运值最低的
    lowest = min(investigators, key=lambda i: i["luck"])
    roll = roll_d100(rng=rng)

    return GroupLuckResult(
        roller_name=lowest["name"],
        roll_value=roll.result,
        luck_value=lowest["luck"],
        succeeded=roll.result <= lowest["luck"],
    )


def recover_luck(
    current_luck: int,
    initial_luck: int,
    rng: Optional[random.Random] = None,
) -> tuple[int, bool]:
    """幸运恢复（幕间休息时）

    CoC 7版规则：
    - 掷d100，如果 > 当前幸运值，则幸运值增加1d10
    - 不能超过初始幸运值（角色创建时的值）

    Args:
        current_luck: 当前幸运值
        initial_luck: 初始幸运值
        rng: 随机数生成器

    Returns:
        (新幸运值, 是否恢复成功)
    """
    if rng is None:
        rng = random.Random()

    roll = roll_d100(rng=rng)
    if roll.result > current_luck:
        recovery = rng.randint(1, 10)
        new_luck = min(current_luck + recovery, initial_luck)
        return new_luck, True
    else:
        return current_luck, False
