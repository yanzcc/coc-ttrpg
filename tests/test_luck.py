"""幸运系统单元测试"""

import random
import pytest
from src.rules.luck import spend_luck, group_luck_check, recover_luck


class TestSpendLuck:
    """幸运消耗测试"""

    def test_successful_spend(self):
        result = spend_luck(original_roll=55, target=50, current_luck=30)
        assert result is not None
        assert result.points_spent == 5
        assert result.modified_roll == 50
        assert result.remaining_luck == 25
        assert result.success is True

    def test_already_succeeded(self):
        """已经成功时返回None"""
        result = spend_luck(original_roll=40, target=50, current_luck=30)
        assert result is None

    def test_not_enough_luck(self):
        """幸运不够时返回None"""
        result = spend_luck(original_roll=80, target=50, current_luck=10)
        assert result is None  # 需要30点，只有10点

    def test_exact_luck(self):
        """恰好够用"""
        result = spend_luck(original_roll=60, target=50, current_luck=10)
        assert result is not None
        assert result.points_spent == 10
        assert result.remaining_luck == 0


class TestGroupLuck:
    """团体幸运测试"""

    def test_lowest_luck_rolls(self):
        """幸运值最低的调查员掷骰"""
        rng = random.Random(42)
        result = group_luck_check([
            {"name": "A", "luck": 60},
            {"name": "B", "luck": 30},
            {"name": "C", "luck": 45},
        ], rng=rng)
        assert result.roller_name == "B"
        assert result.luck_value == 30

    def test_empty_list_raises(self):
        with pytest.raises(ValueError):
            group_luck_check([])

    def test_success_condition(self):
        rng = random.Random(42)
        result = group_luck_check([
            {"name": "A", "luck": 50},
        ], rng=rng)
        assert result.succeeded == (result.roll_value <= result.luck_value)


class TestRecoverLuck:
    """幸运恢复测试"""

    def test_recovery_possible(self):
        """掷骰 > 当前幸运时可以恢复"""
        rng = random.Random(42)
        new_luck, recovered = recover_luck(
            current_luck=20, initial_luck=60, rng=rng,
        )
        # 不管是否恢复，新值都不应超过初始值
        assert new_luck <= 60

    def test_cannot_exceed_initial(self):
        """恢复后不超过初始幸运值"""
        # 构造一定恢复且恢复量大的情况
        class RecoverRng:
            call_count = 0
            def randint(self, a, b):
                self.call_count += 1
                if b == 9 and self.call_count <= 2:
                    return 9  # d100 -> 高值（>当前幸运，恢复成功）
                return 10 if b >= 10 else b  # 恢复1d10取最大

        new_luck, recovered = recover_luck(
            current_luck=55, initial_luck=60, rng=RecoverRng(),
        )
        assert new_luck <= 60
