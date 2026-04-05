"""CoC 7版规则引擎

纯Python实现，不涉及LLM调用。所有骰子和机制计算都是确定性且可审计的。
"""

from .dice import roll_dice, roll_d100, DiceResult, D100Result
from .skill_check import (
    check_skill, opposed_check,
    SuccessLevel, Difficulty,
    SkillCheckResult, OpposedCheckResult,
)
from .sanity import (
    check_sanity, roll_temporary_insanity, roll_indefinite_insanity,
    calculate_san_max, SanityCheckResult,
)
from .combat_rules import (
    resolve_attack, resolve_dodge, resolve_fighting_back,
    check_major_wound, calculate_initiative_order,
)
from .luck import spend_luck, group_luck_check, recover_luck
from .health import (
    apply_damage, apply_first_aid, apply_medicine,
    natural_recovery, dying_round_check, major_wound_con_check,
    check_instant_death, DamageResult, HealingResult, DyingCheckResult,
)
from .skill_list import get_skills_for_era, get_skill_base, OCCUPATIONS
from .character_creation import (
    roll_characteristics, apply_age_modifiers,
    education_improvement_check, roll_luck,
    generate_investigator_stats,
)

__all__ = [
    "roll_dice", "roll_d100", "DiceResult", "D100Result",
    "check_skill", "opposed_check", "SuccessLevel", "Difficulty",
    "SkillCheckResult", "OpposedCheckResult",
    "check_sanity", "roll_temporary_insanity", "roll_indefinite_insanity",
    "calculate_san_max", "SanityCheckResult",
    "resolve_attack", "resolve_dodge", "resolve_fighting_back",
    "check_major_wound", "calculate_initiative_order",
    "spend_luck", "group_luck_check", "recover_luck",
    "apply_damage", "apply_first_aid", "apply_medicine",
    "natural_recovery", "dying_round_check", "major_wound_con_check",
    "check_instant_death", "DamageResult", "HealingResult", "DyingCheckResult",
    "get_skills_for_era", "get_skill_base", "OCCUPATIONS",
    "roll_characteristics", "apply_age_modifiers",
    "education_improvement_check", "roll_luck",
    "generate_investigator_stats",
]
