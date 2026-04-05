"""骰子系统单元测试"""

import random
import pytest
from src.rules.dice import roll_dice, roll_d100


class TestRollDice:
    """骰子表达式测试"""

    def test_fixed_value(self):
        result = roll_dice("3")
        assert result.total == 3

    def test_single_d6(self):
        rng = random.Random(42)
        result = roll_dice("1d6", rng=rng)
        assert 1 <= result.total <= 6

    def test_multiple_dice(self):
        rng = random.Random(42)
        result = roll_dice("3d6", rng=rng)
        assert 3 <= result.total <= 18
        assert len(result.rolls) == 3

    def test_dice_with_modifier(self):
        rng = random.Random(42)
        result = roll_dice("1d6+2", rng=rng)
        # 1d6的范围是1-6，加2后是3-8
        assert 3 <= result.total <= 8

    def test_d100(self):
        rng = random.Random(42)
        result = roll_dice("1d100", rng=rng)
        assert 1 <= result.total <= 100

    def test_deterministic_with_seed(self):
        """相同seed应产生相同结果"""
        r1 = roll_dice("2d6", rng=random.Random(123))
        r2 = roll_dice("2d6", rng=random.Random(123))
        assert r1.total == r2.total
        assert r1.rolls == r2.rolls


class TestRollD100:
    """百分骰测试"""

    def test_basic_range(self):
        """结果应在1-100范围内"""
        rng = random.Random(42)
        for _ in range(100):
            result = roll_d100(rng=rng)
            assert 1 <= result.result <= 100

    def test_no_bonus_no_penalty(self):
        rng = random.Random(42)
        result = roll_d100(rng=rng)
        assert len(result.bonus_dice) == 0
        assert len(result.penalty_dice) == 0

    def test_bonus_die(self):
        """奖励骰应该选择较低的结果"""
        rng = random.Random(42)
        result = roll_d100(bonus=1, rng=rng)
        assert len(result.all_options) == 2
        assert result.result == min(result.all_options)

    def test_penalty_die(self):
        """惩罚骰应该选择较高的结果"""
        rng = random.Random(42)
        result = roll_d100(penalty=1, rng=rng)
        assert len(result.all_options) == 2
        assert result.result == max(result.all_options)

    def test_bonus_penalty_cancel(self):
        """奖励和惩罚相消"""
        rng = random.Random(42)
        result = roll_d100(bonus=2, penalty=1, rng=rng)
        # 净效果：1个奖励骰
        assert len(result.bonus_dice) == 1
        assert len(result.penalty_dice) == 0

    def test_00_and_0_equals_100(self):
        """00+0应该等于100"""
        # 构造一个总是掷出0的rng
        class ZeroRng:
            def randint(self, a, b):
                return 0

        result = roll_d100(rng=ZeroRng())
        assert result.result == 100
