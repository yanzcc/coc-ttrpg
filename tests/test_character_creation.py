"""角色创建规则测试"""

import random
import pytest

from src.rules.character_creation import (
    roll_characteristics,
    apply_age_modifiers,
    education_improvement_check,
    roll_luck,
    generate_investigator_stats,
)
from src.models.character import Characteristics


class TestRollCharacteristics:
    """测试属性掷骰"""

    def test_all_values_in_range(self):
        rng = random.Random(42)
        chars = roll_characteristics(rng=rng)
        # 3D6×5: 最小15, 最大90
        for attr in ["STR", "CON", "DEX", "APP", "POW"]:
            val = getattr(chars, attr)
            assert 15 <= val <= 90, f"{attr}={val} 超出3D6×5范围"
        # (2D6+6)×5: 最小40, 最大90
        for attr in ["SIZ", "INT", "EDU"]:
            val = getattr(chars, attr)
            assert 40 <= val <= 90, f"{attr}={val} 超出(2D6+6)×5范围"

    def test_deterministic_with_seed(self):
        chars1 = roll_characteristics(rng=random.Random(123))
        chars2 = roll_characteristics(rng=random.Random(123))
        assert chars1.STR == chars2.STR
        assert chars1.EDU == chars2.EDU

    def test_values_are_multiples_of_5(self):
        rng = random.Random(99)
        chars = roll_characteristics(rng=rng)
        for attr in ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU"]:
            val = getattr(chars, attr)
            assert val % 5 == 0, f"{attr}={val} 不是5的倍数"


class TestApplyAgeModifiers:
    """测试年龄修正"""

    def _base_chars(self):
        return Characteristics(
            STR=60, CON=60, SIZ=65, DEX=60, APP=60, INT=70, POW=60, EDU=60
        )

    def test_young_age_15_19(self):
        chars, desc = apply_age_modifiers(self._base_chars(), 17)
        # 15-19岁：STR+SIZ合计减5，EDU减5
        total_reduced = (60 - chars.STR) + (60 - chars.CON) + (60 - chars.DEX)
        assert "15-19" in desc or "15" in desc
        assert chars.EDU <= 60  # EDU可能减少

    def test_no_modifier_20_39(self):
        chars, desc = apply_age_modifiers(self._base_chars(), 30)
        # 20-39岁：无修正（可能有EDU增强）
        assert chars.STR == 60
        assert chars.CON == 60
        assert chars.DEX == 60

    def test_middle_age_40_49(self):
        chars, desc = apply_age_modifiers(self._base_chars(), 45)
        # 40-49岁：STR/CON/DEX合计减5，APP减5
        total_lost = (60 - chars.STR) + (60 - chars.CON) + (60 - chars.DEX)
        assert total_lost == 5
        assert chars.APP == 55  # APP减5

    def test_old_age_60_69(self):
        chars, desc = apply_age_modifiers(self._base_chars(), 65)
        # 60-69岁：STR/CON/DEX合计减20
        total_lost = (60 - chars.STR) + (60 - chars.CON) + (60 - chars.DEX)
        assert total_lost == 20
        assert chars.APP == 45  # APP减15

    def test_minimum_attribute_value(self):
        # 低属性值，确保不低于1
        low_chars = Characteristics(
            STR=15, CON=15, SIZ=40, DEX=15, APP=15, INT=40, POW=15, EDU=40
        )
        chars, desc = apply_age_modifiers(low_chars, 80)
        assert chars.STR >= 1
        assert chars.CON >= 1
        assert chars.DEX >= 1
        assert chars.APP >= 1


class TestEducationImprovement:
    """测试教育增强检定"""

    def test_improvement_when_roll_exceeds(self):
        # 用rng使roll_d100返回一个大于当前EDU的值
        rng = random.Random(42)
        original = 50
        new_edu = education_improvement_check(original, rng=rng)
        # 结果应该 >= 原始值
        assert new_edu >= original

    def test_no_improvement_when_roll_below(self):
        # EDU=99时几乎不可能增长
        rng = random.Random(42)
        new_edu = education_improvement_check(99, rng=rng)
        assert new_edu == 99

    def test_edu_capped_at_99(self):
        rng = random.Random(42)
        # 多次尝试，确保不超过99
        edu = 90
        for _ in range(20):
            edu = education_improvement_check(edu, rng=rng)
        assert edu <= 99


class TestRollLuck:
    """测试幸运掷骰"""

    def test_luck_in_range(self):
        rng = random.Random(42)
        luck = roll_luck(rng=rng)
        assert 15 <= luck <= 90  # 3D6×5

    def test_luck_multiple_of_5(self):
        rng = random.Random(42)
        luck = roll_luck(rng=rng)
        assert luck % 5 == 0


class TestGenerateInvestigatorStats:
    """测试完整角色属性生成"""

    def test_complete_generation(self):
        chars, luck, desc = generate_investigator_stats(age=30, rng=random.Random(42))
        assert isinstance(chars, Characteristics)
        assert isinstance(luck, int)
        assert isinstance(desc, str)

    def test_young_investigator(self):
        chars, luck, desc = generate_investigator_stats(age=18, rng=random.Random(42))
        assert "15-19" in desc or "15" in desc or "年龄" in desc

    def test_old_investigator(self):
        chars, luck, desc = generate_investigator_stats(age=70, rng=random.Random(42))
        # 应该有年龄修正描述
        assert len(desc) > 0
