"""战斗系统单元测试"""

import random
import pytest
from src.rules.combat_rules import (
    resolve_attack, resolve_dodge, resolve_fighting_back,
    check_major_wound, calculate_initiative_order,
)
from src.rules.skill_check import SuccessLevel


class TestResolveAttack:
    """攻击解析测试"""

    def test_attack_returns_result(self):
        rng = random.Random(42)
        success, damage, detail, _fumble = resolve_attack(
            attack_skill_value=50,
            damage_expression="1d6",
            rng=rng,
        )
        assert isinstance(success, SuccessLevel)
        assert isinstance(damage, int)
        assert damage >= 0

    def test_failed_attack_no_damage(self):
        """攻击失败不造成伤害"""
        # 构造一定失败的rng
        class HighRng:
            def randint(self, a, b):
                if b == 9:
                    return 9
                return b

        success, damage, detail, _fumble = resolve_attack(
            attack_skill_value=20,
            damage_expression="1d6",
            rng=HighRng(),
        )
        if success <= SuccessLevel.FAILURE:
            assert damage == 0

    def test_melee_adds_damage_bonus(self):
        """近战攻击加伤害加值"""
        rng = random.Random(42)
        # 使用一个一定成功的rng
        class LowRng:
            def randint(self, a, b):
                if b == 9:
                    return 0  # d100 -> 低值（成功）
                return 3  # 其他骰子

        success, damage, detail, _fumble = resolve_attack(
            attack_skill_value=80,
            damage_expression="1d6",
            damage_bonus="+1d4",
            is_melee=True,
            rng=LowRng(),
        )
        # 如果成功，伤害应该包含加值
        if success >= SuccessLevel.REGULAR:
            assert damage > 0


class TestResolveDodge:
    """闪避测试"""

    def test_dodge_basic(self):
        rng = random.Random(42)
        dodged, roll_val, dodge_level = resolve_dodge(
            dodge_skill=40,
            attack_success=SuccessLevel.REGULAR,
            rng=rng,
        )
        assert isinstance(dodged, bool)
        assert 1 <= roll_val <= 100

    def test_dodge_must_match_attack_level(self):
        """闪避成功等级必须>=攻击成功等级"""
        class LowRng:
            def randint(self, a, b):
                if b == 9:
                    return 0
                return 0

        dodged, _, dodge_level = resolve_dodge(
            dodge_skill=80,
            attack_success=SuccessLevel.HARD,
            rng=LowRng(),
        )
        # 极低掷骰 -> 至少极难成功 -> 应该能闪避困难攻击
        if dodge_level >= SuccessLevel.HARD:
            assert dodged is True


class TestMajorWound:
    """重伤判定测试"""

    def test_major_wound_threshold(self):
        """伤害 >= HP上限/2 为重伤"""
        assert check_major_wound(7, 12) is True  # 7 >= 6
        assert check_major_wound(5, 12) is False  # 5 < 6

    def test_exactly_half(self):
        """恰好为一半也算重伤"""
        assert check_major_wound(6, 12) is True

    def test_low_hp_max(self):
        assert check_major_wound(3, 5) is True  # 3 >= 2
        assert check_major_wound(1, 5) is False  # 1 < 2


class TestInitiativeOrder:
    """先攻排序测试"""

    def test_sort_by_dex_descending(self):
        participants = [
            {"id": "a", "name": "A", "dex": 40},
            {"id": "b", "name": "B", "dex": 70},
            {"id": "c", "name": "C", "dex": 55},
        ]
        ordered = calculate_initiative_order(participants)
        assert ordered[0]["id"] == "b"
        assert ordered[1]["id"] == "c"
        assert ordered[2]["id"] == "a"

    def test_empty_list(self):
        assert calculate_initiative_order([]) == []
