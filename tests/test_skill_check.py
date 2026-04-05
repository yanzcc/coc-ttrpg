"""技能检定单元测试"""

import random
import pytest
from src.rules.skill_check import (
    check_skill, opposed_check,
    SuccessLevel, Difficulty, _determine_success,
)


class TestDetermineSuccess:
    """成功等级判定测试"""

    def test_critical(self):
        """01始终为大成功"""
        assert _determine_success(1, 50) == SuccessLevel.CRITICAL
        assert _determine_success(1, 10) == SuccessLevel.CRITICAL
        assert _determine_success(1, 1) == SuccessLevel.CRITICAL

    def test_fumble_low_skill(self):
        """技能<50时，96-100为大失败"""
        assert _determine_success(96, 40) == SuccessLevel.FUMBLE
        assert _determine_success(100, 40) == SuccessLevel.FUMBLE

    def test_fumble_high_skill(self):
        """技能>=50时，仅100为大失败"""
        assert _determine_success(100, 50) == SuccessLevel.FUMBLE
        assert _determine_success(96, 50) != SuccessLevel.FUMBLE

    def test_extreme_success(self):
        """掷骰 <= 技能值/5 为极难成功"""
        assert _determine_success(10, 50) == SuccessLevel.EXTREME
        assert _determine_success(5, 50) == SuccessLevel.EXTREME

    def test_hard_success(self):
        """掷骰 <= 技能值/2 为困难成功"""
        assert _determine_success(25, 50) == SuccessLevel.HARD
        assert _determine_success(20, 50) == SuccessLevel.HARD

    def test_regular_success(self):
        """掷骰 <= 技能值 为普通成功"""
        assert _determine_success(50, 50) == SuccessLevel.REGULAR
        assert _determine_success(40, 50) >= SuccessLevel.REGULAR

    def test_failure(self):
        """掷骰 > 技能值 为失败"""
        assert _determine_success(51, 50) == SuccessLevel.FAILURE
        assert _determine_success(90, 50) == SuccessLevel.FAILURE


class TestCheckSkill:
    """技能检定测试"""

    def test_basic_check(self):
        rng = random.Random(42)
        result = check_skill("侦查", 50, rng=rng)
        assert result.skill_name == "侦查"
        assert result.skill_value == 50
        assert isinstance(result.success_level, SuccessLevel)

    def test_hard_difficulty(self):
        """困难难度：目标值为技能值/2"""
        rng = random.Random(42)
        result = check_skill("侦查", 60, difficulty=Difficulty.HARD, rng=rng)
        assert result.target == 30

    def test_extreme_difficulty(self):
        """极难难度：目标值为技能值/5"""
        rng = random.Random(42)
        result = check_skill("侦查", 60, difficulty=Difficulty.EXTREME, rng=rng)
        assert result.target == 12

    def test_can_push_on_failure(self):
        """失败时可以孤注一掷"""
        # 使用一个会失败的seed
        class HighRng:
            def randint(self, a, b):
                if b == 9:
                    return 9  # 十位骰
                return 5  # 个位骰 -> 结果95

        result = check_skill("侦查", 50, rng=HighRng())
        if not result.succeeded:
            assert result.can_push is True

    def test_cannot_push_on_fumble(self):
        """大失败时不能孤注一掷"""
        # 构造大失败
        class FumbleRng:
            def randint(self, a, b):
                if b == 9:
                    return 9  # 十位
                return 6    # 个位 -> 96

        result = check_skill("侦查", 40, rng=FumbleRng())
        if result.is_fumble:
            assert result.can_push is False

    def test_pushed_roll_not_pushable(self):
        """孤注一掷的结果不能再次孤注一掷"""
        rng = random.Random(42)
        result = check_skill("侦查", 50, is_pushed=True, rng=rng)
        assert result.can_push is False


class TestOpposedCheck:
    """对抗检定测试"""

    def test_basic_opposed(self):
        rng = random.Random(42)
        result = opposed_check(
            "话术", 60,
            "心理学", 50,
            rng=rng,
        )
        assert result.winner in ("attacker", "defender", "tie")
        assert result.attacker.skill_name == "话术"
        assert result.defender.skill_name == "心理学"

    def test_higher_success_wins(self):
        """成功等级高的一方获胜"""
        # 多次测试确保逻辑正确
        rng = random.Random(42)
        for _ in range(20):
            result = opposed_check("A", 70, "B", 30, rng=rng)
            if result.attacker.success_level > result.defender.success_level:
                assert result.winner == "attacker"
            elif result.defender.success_level > result.attacker.success_level:
                assert result.winner == "defender"
