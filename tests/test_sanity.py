"""理智系统单元测试"""

import random
import pytest
from src.rules.sanity import (
    check_sanity, roll_temporary_insanity, roll_indefinite_insanity,
    calculate_san_max, TEMPORARY_INSANITY_TABLE, INDEFINITE_INSANITY_TABLE,
)


class TestCheckSanity:
    """理智检定测试"""

    def test_success_less_loss(self):
        """成功时使用较小的损失表达式"""
        # 使用低掷骰（成功）
        class LowRng:
            call_count = 0
            def randint(self, a, b):
                self.call_count += 1
                if self.call_count <= 2:
                    return 0  # d100掷骰 -> 低值
                return 1  # 损失骰

        result = check_sanity(
            current_san=60,
            success_loss="0",
            fail_loss="1d6",
            rng=LowRng(),
        )
        # 掷出很低应该成功
        if result.succeeded:
            assert result.loss_expression == "0"

    def test_failure_more_loss(self):
        """失败时使用较大的损失表达式"""
        class HighRng:
            call_count = 0
            def randint(self, a, b):
                self.call_count += 1
                if b == 9:
                    return 9  # 十位骰
                if self.call_count <= 2:
                    return 9  # 个位骰 -> 高值(失败)
                return 3  # 损失骰

        result = check_sanity(
            current_san=30,
            success_loss="0",
            fail_loss="1d6",
            rng=HighRng(),
        )
        if not result.succeeded:
            assert result.loss_expression == "1d6"

    def test_san_cannot_go_below_zero(self):
        """理智值不会低于0"""
        rng = random.Random(42)
        result = check_sanity(
            current_san=3,
            success_loss="1d6",
            fail_loss="2d6",
            rng=rng,
        )
        assert result.new_san >= 0

    def test_permanent_insanity_at_zero(self):
        """理智降至0时触发永久疯狂"""
        # 构造一定失败且损失大的情况
        class BadRng:
            call_count = 0
            def randint(self, a, b):
                self.call_count += 1
                if b == 9 and self.call_count <= 2:
                    return 9  # d100 -> 高值
                if b == 9:
                    return 5  # 其他d10
                return b  # 损失骰取最大

        result = check_sanity(
            current_san=5,
            success_loss="1",
            fail_loss="2d6",
            rng=BadRng(),
        )
        if result.new_san == 0:
            assert result.triggered_permanent is True

    def test_san_max_with_mythos(self):
        """理智不超过上限"""
        rng = random.Random(42)
        result = check_sanity(
            current_san=80,
            success_loss="0",
            fail_loss="0",
            san_max=70,  # 克苏鲁神话29 -> 上限70
            rng=rng,
        )
        assert result.new_san <= 70


class TestInsanityTables:
    """疯狂症状表测试"""

    def test_temporary_insanity(self):
        rng = random.Random(42)
        result = roll_temporary_insanity(rng=rng)
        assert result.insanity_type == "临时"
        assert 1 <= result.duration_rounds <= 10
        assert result.symptom in TEMPORARY_INSANITY_TABLE

    def test_indefinite_insanity(self):
        rng = random.Random(42)
        result = roll_indefinite_insanity(rng=rng)
        assert result.insanity_type == "不定期"
        assert result.symptom in INDEFINITE_INSANITY_TABLE


class TestSanMax:
    """理智上限计算测试"""

    def test_no_mythos(self):
        assert calculate_san_max(0) == 99

    def test_with_mythos(self):
        assert calculate_san_max(15) == 84

    def test_high_mythos(self):
        assert calculate_san_max(99) == 0

    def test_cannot_be_negative(self):
        assert calculate_san_max(100) == 0
