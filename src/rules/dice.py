"""骰子系统

实现CoC 7版所有骰子机制：d100、奖励骰/惩罚骰、各种伤害骰。
所有随机数通过random模块生成，可通过seed控制以便测试。
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class DiceResult:
    """骰子结果"""
    rolls: list[int]       # 每个骰子的结果
    total: int             # 总和
    expression: str        # 原始表达式（如"2d6+1"）
    detail: str            # 详细描述（如"[3, 5]+1=9"）


def roll_dice(expression: str, rng: Optional[random.Random] = None) -> DiceResult:
    """掷骰子

    支持的表达式格式：
    - "d100" / "1d100" — 百分骰
    - "2d6" — 多个骰子
    - "1d6+2" — 骰子+修正值
    - "2d6+1d4" — 多组骰子相加
    - "3" — 固定值

    Args:
        expression: 骰子表达式
        rng: 可选的随机数生成器（用于测试）

    Returns:
        DiceResult 包含所有骰子详情
    """
    if rng is None:
        rng = random.Random()

    expression = expression.strip().lower()
    all_rolls: list[int] = []
    total = 0
    parts = []

    # 解析表达式：拆分为 +/- 的各项
    tokens = re.findall(r'[+-]?[^+-]+', expression)

    for token in tokens:
        token = token.strip()
        sign = 1
        if token.startswith('-'):
            sign = -1
            token = token[1:].strip()
        elif token.startswith('+'):
            token = token[1:].strip()

        match = re.match(r'^(\d*)d(\d+)$', token)
        if match:
            count = int(match.group(1)) if match.group(1) else 1
            sides = int(match.group(2))
            rolls = [rng.randint(1, sides) for _ in range(count)]
            all_rolls.extend(rolls)
            subtotal = sum(rolls) * sign
            total += subtotal
            parts.append(f"{'- ' if sign < 0 else ''}{rolls}")
        else:
            # 固定值
            val = int(token) * sign
            total += val
            parts.append(str(val))

    detail = " + ".join(parts) + f" = {total}"
    return DiceResult(rolls=all_rolls, total=total, expression=expression, detail=detail)


@dataclass
class D100Result:
    """d100检定结果"""
    units_die: int         # 个位骰 (0-9)
    tens_die: int          # 十位骰 (00-90)
    result: int            # 最终结果 (1-100)
    bonus_dice: list[int]  # 奖励骰的十位值
    penalty_dice: list[int]  # 惩罚骰的十位值
    all_options: list[int]   # 所有可能的结果值


def roll_d100(
    bonus: int = 0,
    penalty: int = 0,
    rng: Optional[random.Random] = None
) -> D100Result:
    """掷百分骰

    CoC 7版规则：
    - 掷两个d10：十位骰(00-90)和个位骰(0-9)
    - 00+0 = 100（而非0）
    - 奖励骰：额外掷十位骰，选最低
    - 惩罚骰：额外掷十位骰，选最高
    - 奖励和惩罚相消

    Args:
        bonus: 奖励骰数量
        penalty: 惩罚骰数量
        rng: 可选的随机数生成器

    Returns:
        D100Result
    """
    if rng is None:
        rng = random.Random()

    # 奖励和惩罚相消
    net = bonus - penalty
    extra_bonus = max(0, net)
    extra_penalty = max(0, -net)

    # 掷个位骰 (0-9)
    units = rng.randint(0, 9)

    # 掷十位骰 (0-9，代表00-90)
    tens = rng.randint(0, 9)

    # 额外的十位骰
    bonus_tens = [rng.randint(0, 9) for _ in range(extra_bonus)]
    penalty_tens = [rng.randint(0, 9) for _ in range(extra_penalty)]

    # 计算所有可能的结果
    all_tens = [tens] + bonus_tens + penalty_tens
    all_options = []
    for t in all_tens:
        val = t * 10 + units
        if val == 0:
            val = 100
        all_options.append(val)

    # 选择最终结果
    if extra_bonus > 0:
        # 奖励骰：选最低值（但要注意00+0=100的特殊情况）
        result = min(all_options)
    elif extra_penalty > 0:
        # 惩罚骰：选最高值
        result = max(all_options)
    else:
        val = tens * 10 + units
        result = 100 if val == 0 else val

    return D100Result(
        units_die=units,
        tens_die=tens * 10,
        result=result,
        bonus_dice=[t * 10 for t in bonus_tens],
        penalty_dice=[t * 10 for t in penalty_tens],
        all_options=all_options,
    )


def parse_damage_expression(expr: str) -> str:
    """解析伤害表达式，处理伤害加值

    如 "1d6+db" 中db会被替换为实际的伤害加值。
    这个函数只做格式化，实际掷骰用roll_dice。
    """
    return expr.strip()
