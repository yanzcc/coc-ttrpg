"""理智系统

实现CoC 7版的理智检定机制：
- SAN检定
- 理智损失
- 临时疯狂 / 不定期疯狂 / 永久疯狂
- 克苏鲁神话与理智上限的关系
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from .dice import roll_d100, roll_dice


@dataclass
class SanityCheckResult:
    """理智检定结果"""
    current_san: int          # 检定前的理智值
    roll_value: int           # d100掷骰结果
    succeeded: bool           # 是否成功
    loss_expression: str      # 损失表达式（成功或失败）
    san_lost: int             # 实际损失量
    new_san: int              # 检定后的理智值
    triggered_temporary: bool  # 是否触发临时疯狂
    triggered_indefinite: bool  # 是否触发不定期疯狂
    triggered_permanent: bool  # 是否触发永久疯狂
    details: str = ""         # 额外说明


@dataclass
class InsanityResult:
    """疯狂结果"""
    insanity_type: str        # "临时" / "不定期" / "永久"
    duration_rounds: Optional[int] = None  # 临时疯狂持续轮数
    symptom: str = ""         # 症状描述


# 临时疯狂症状表（d10）
TEMPORARY_INSANITY_TABLE = [
    "失忆——调查员回过神来，发现自己身处陌生之地，不知道自己是谁",
    "假性残疾——调查员变得失明、失聪或失去某肢体的感觉",
    "暴力倾向——调查员陷入暴怒，无差别攻击周围一切",
    "偏执妄想——调查员认为所有人都在密谋对付自己",
    "重大恐惧症——调查员对触发疯狂的事物产生极度恐惧",
    "重大躁狂症——调查员变得极度亢奋，做出危险的冲动行为",
    "幻觉——调查员看到/听到不存在的东西",
    "奇异行为——调查员出现回声语言、反复性动作或其他怪异行为",
    "昏厥——调查员当场晕倒",
    "逃跑——调查员惊恐地逃离现场，尽可能远离恐惧源",
]

# 不定期疯狂症状表（d10）
INDEFINITE_INSANITY_TABLE = [
    "失忆或精神分裂",
    "严重恐惧症（由守密人决定具体类型）",
    "严重躁狂症（由守密人决定具体类型）",
    "幻觉与妄想",
    "偏执状态",
    "强迫行为或仪式",
    "解离性身份障碍",
    "饮食障碍",
    "焦虑症或恐慌症",
    "依赖某种物质或行为",
]


def check_sanity(
    current_san: int,
    success_loss: str,
    fail_loss: str,
    san_max: int = 99,
    san_lost_this_hour: int = 0,
    int_value: int = 50,
    rng: Optional[random.Random] = None,
) -> SanityCheckResult:
    """执行理智检定

    CoC 7版规则：
    - 掷d100，<=当前SAN为成功
    - 成功损失success_loss，失败损失fail_loss
    - 单次损失>=5点 且 INT检定失败 -> 临时疯狂（1d10轮）
    - 一小时内累计损失>=当前SAN的1/5 -> 不定期疯狂
    - SAN降至0 -> 永久疯狂

    Args:
        current_san: 当前理智值
        success_loss: 成功时的损失表达式（如"0"、"1"、"1d3"）
        fail_loss: 失败时的损失表达式（如"1d6"、"2d6"）
        san_max: 理智上限（99-克苏鲁神话技能）
        san_lost_this_hour: 本小时内已损失的理智值
        int_value: 调查员的INT值（用于判定临时疯狂）
        rng: 随机数生成器

    Returns:
        SanityCheckResult
    """
    if rng is None:
        rng = random.Random()

    # 掷检定骰
    roll = roll_d100(rng=rng)
    succeeded = roll.result <= current_san

    # 计算损失
    if succeeded:
        loss_expr = success_loss
    else:
        loss_expr = fail_loss

    # 掷损失骰
    loss_result = roll_dice(loss_expr, rng=rng)
    san_lost = max(0, loss_result.total)

    # 新理智值（不低于0）
    new_san = max(0, min(current_san - san_lost, san_max))
    actual_lost = current_san - new_san

    # 检查各种疯狂触发条件
    triggered_temporary = False
    triggered_indefinite = False
    triggered_permanent = False

    # 永久疯狂：SAN降至0
    if new_san == 0:
        triggered_permanent = True

    # 不定期疯狂：一小时内累计损失 >= 当前SAN/5
    elif (san_lost_this_hour + actual_lost) >= current_san // 5:
        triggered_indefinite = True

    # 临时疯狂：单次损失>=5 且 INT检定失败
    elif actual_lost >= 5:
        int_roll = roll_d100(rng=rng)
        if int_roll.result > int_value:
            triggered_temporary = True

    details_parts = []
    if succeeded:
        details_parts.append(f"理智检定成功（掷出{roll.result}，需要<={current_san}）")
    else:
        details_parts.append(f"理智检定失败（掷出{roll.result}，需要<={current_san}）")
    details_parts.append(f"理智损失：{loss_expr} = {actual_lost}点")
    details_parts.append(f"理智值：{current_san} -> {new_san}")

    return SanityCheckResult(
        current_san=current_san,
        roll_value=roll.result,
        succeeded=succeeded,
        loss_expression=loss_expr,
        san_lost=actual_lost,
        new_san=new_san,
        triggered_temporary=triggered_temporary,
        triggered_indefinite=triggered_indefinite,
        triggered_permanent=triggered_permanent,
        details="；".join(details_parts),
    )


def roll_temporary_insanity(rng: Optional[random.Random] = None) -> InsanityResult:
    """掷临时疯狂症状

    持续1d10轮（战斗中）或1d10小时（非战斗中）
    """
    if rng is None:
        rng = random.Random()

    symptom_index = rng.randint(0, 9)
    duration = rng.randint(1, 10)

    return InsanityResult(
        insanity_type="临时",
        duration_rounds=duration,
        symptom=TEMPORARY_INSANITY_TABLE[symptom_index],
    )


def roll_indefinite_insanity(rng: Optional[random.Random] = None) -> InsanityResult:
    """掷不定期疯狂症状

    需要1d6个月的治疗，或在游戏中通过角色扮演恢复
    """
    if rng is None:
        rng = random.Random()

    symptom_index = rng.randint(0, 9)

    return InsanityResult(
        insanity_type="不定期",
        symptom=INDEFINITE_INSANITY_TABLE[symptom_index],
    )


def recover_sanity_therapy(
    current_san: int,
    san_max: int,
    rng: Optional[random.Random] = None,
) -> tuple[int, int]:
    """精神分析治疗恢复理智

    每月一次，治疗师进行精神分析技能检定成功后调用。
    恢复1d3点理智值。

    Returns:
        (新理智值, 恢复量)
    """
    if rng is None:
        rng = random.Random()

    recovery = rng.randint(1, 3)
    new_san = min(current_san + recovery, san_max)
    actual_recovery = new_san - current_san
    return new_san, actual_recovery


def recover_sanity_self(
    current_san: int,
    san_max: int,
    amount: int = 0,
    rng: Optional[random.Random] = None,
) -> tuple[int, int]:
    """自我恢复理智（完成冒险目标等）

    由守密人裁定恢复量（通常1d6）。

    Returns:
        (新理智值, 恢复量)
    """
    if rng is None:
        rng = random.Random()

    if amount <= 0:
        amount = rng.randint(1, 6)

    new_san = min(current_san + amount, san_max)
    actual_recovery = new_san - current_san
    return new_san, actual_recovery


def calculate_san_max(cthulhu_mythos: int) -> int:
    """计算理智上限

    理智上限 = 99 - 克苏鲁神话技能值
    """
    return max(0, 99 - cthulhu_mythos)
