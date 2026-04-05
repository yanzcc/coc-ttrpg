"""生命值管理系统单元测试"""

import random
import pytest
from src.rules.health import (
    apply_damage, apply_first_aid, apply_medicine,
    natural_recovery, dying_round_check, major_wound_con_check,
    check_instant_death, WoundType,
)
from src.rules.skill_check import SuccessLevel


class TestApplyDamage:
    """伤害应用测试"""

    def test_normal_damage(self):
        """普通伤害：HP减少，不触发重伤"""
        result = apply_damage(damage=3, current_hp=12, max_hp=12)
        assert result.hp_after == 9
        assert result.wound_type == WoundType.NORMAL
        assert result.triggered_major_wound is False
        assert result.is_dying is False
        assert result.is_dead is False

    def test_major_wound(self):
        """重伤：单次伤害 >= HP上限/2"""
        result = apply_damage(damage=7, current_hp=12, max_hp=12)
        assert result.wound_type == WoundType.MAJOR
        assert result.triggered_major_wound is True
        assert result.hp_after == 5

    def test_major_wound_not_retriggered(self):
        """已有重伤时不再触发"""
        result = apply_damage(damage=7, current_hp=10, max_hp=12, already_major_wound=True)
        assert result.wound_type == WoundType.MAJOR
        assert result.triggered_major_wound is False

    def test_exactly_half_hp_is_major(self):
        """恰好为HP上限/2也算重伤"""
        result = apply_damage(damage=6, current_hp=12, max_hp=12)
        assert result.wound_type == WoundType.MAJOR

    def test_hp_to_zero_is_dying(self):
        """HP降至0进入濒死"""
        result = apply_damage(damage=5, current_hp=5, max_hp=12)
        assert result.hp_after == 0
        assert result.is_dying is True
        assert result.is_dead is False

    def test_hp_below_zero_dying(self):
        """HP降至负数但未达死亡阈值"""
        result = apply_damage(damage=8, current_hp=5, max_hp=12)
        assert result.hp_after == -3
        assert result.is_dying is True
        assert result.is_dead is False

    def test_instant_death(self):
        """HP降至负max_hp或更低：立即死亡"""
        result = apply_damage(damage=20, current_hp=8, max_hp=12)
        # hp_after = 8 - 20 = -12, abs(-12) >= 12 -> 死亡
        assert result.is_dead is True
        assert result.is_dying is False

    def test_zero_damage(self):
        """0伤害不改变状态"""
        result = apply_damage(damage=0, current_hp=10, max_hp=12)
        assert result.hp_after == 10
        assert result.damage == 0

    def test_negative_damage_ignored(self):
        """负数伤害被忽略"""
        result = apply_damage(damage=-5, current_hp=10, max_hp=12)
        assert result.hp_after == 10

    def test_unconscious_at_zero(self):
        """HP<=0时昏迷"""
        result = apply_damage(damage=10, current_hp=10, max_hp=12)
        assert result.is_unconscious is True


class SuccessRng:
    """构造d100掷出低值（成功）的rng

    roll_d100调用randint(0,9)两次：个位骰和十位骰。
    个位=1, 十位=0 -> 结果为01（大成功）。
    """
    def randint(self, a, b):
        if b == 9:
            return 1  # 十位0*10+个位1=01
        return 1  # 其他骰子


class FailRng:
    """构造d100掷出高值（失败）的rng"""
    def randint(self, a, b):
        if b == 9:
            return 9  # 十位9*10+个位9=99
        return b  # 其他骰子取最大


class TestFirstAid:
    """急救测试"""

    def test_success_restores_1hp(self):
        """急救成功恢复1点HP"""
        result = apply_first_aid(
            first_aid_skill=60,
            patient_hp=8,
            patient_max_hp=12,
            rng=SuccessRng(),
        )
        assert result.succeeded is True
        assert result.hp_after == 9
        assert result.hp_restored == 1

    def test_failure_no_healing(self):
        """急救失败不恢复HP"""
        result = apply_first_aid(
            first_aid_skill=30,
            patient_hp=8,
            patient_max_hp=12,
            rng=FailRng(),
        )
        assert result.succeeded is False
        assert result.hp_after == 8

    def test_dying_patient_stabilized(self):
        """急救濒死患者：成功则稳定到1HP"""
        result = apply_first_aid(
            first_aid_skill=60,
            patient_hp=-2,
            patient_max_hp=12,
            patient_is_dying=True,
            rng=SuccessRng(),
        )
        assert result.succeeded is True
        assert result.stabilized is True
        assert result.hp_after == 1

    def test_no_overheal(self):
        """急救不超过HP上限"""
        result = apply_first_aid(
            first_aid_skill=60,
            patient_hp=12,
            patient_max_hp=12,
            rng=SuccessRng(),
        )
        assert result.hp_after == 12


class TestMedicine:
    """医学治疗测试"""

    def test_success_restores_1d3(self):
        """医学成功恢复1d3 HP"""
        result = apply_medicine(
            medicine_skill=60,
            patient_hp=8,
            patient_max_hp=12,
            rng=SuccessRng(),
        )
        assert result.succeeded is True
        assert result.hp_restored >= 1

    def test_dying_stabilized(self):
        """医学治疗濒死患者"""
        result = apply_medicine(
            medicine_skill=60,
            patient_hp=-3,
            patient_max_hp=12,
            patient_is_dying=True,
            rng=SuccessRng(),
        )
        assert result.stabilized is True
        assert result.hp_after == 1


class TestDyingRoundCheck:
    """濒死轮检定测试"""

    def test_success_stabilizes(self):
        """CON检定成功暂时稳定"""
        result = dying_round_check(con_value=60, rng=SuccessRng())
        assert result.succeeded is True

    def test_failure_continues_bleeding(self):
        """CON检定失败继续流血"""
        result = dying_round_check(con_value=30, rng=FailRng())
        assert result.succeeded is False


class TestNaturalRecovery:
    """自然恢复测试"""

    def test_normal_recovery_1d3(self):
        """无重伤：每周恢复1d3"""
        rng = random.Random(42)
        result = natural_recovery(current_hp=8, max_hp=12, rng=rng)
        assert result.succeeded is True
        assert 1 <= result.hp_restored <= 3
        assert result.hp_after > 8

    def test_major_wound_recovery_1(self):
        """有重伤：每周只恢复1"""
        rng = random.Random(42)
        result = natural_recovery(
            current_hp=5, max_hp=12, has_major_wound=True, rng=rng,
        )
        assert result.hp_restored == 1
        assert result.hp_after == 6

    def test_no_overheal(self):
        """不超过HP上限"""
        rng = random.Random(42)
        result = natural_recovery(current_hp=11, max_hp=12, rng=rng)
        assert result.hp_after <= 12

    def test_full_hp_no_change(self):
        """已满HP无变化"""
        result = natural_recovery(current_hp=12, max_hp=12)
        assert result.hp_after == 12
        assert result.hp_restored == 0


class TestInstantDeath:
    """即死判定测试"""

    def test_instant_death(self):
        assert check_instant_death(-12, 12) is True
        assert check_instant_death(-15, 12) is True

    def test_not_instant_death(self):
        assert check_instant_death(-11, 12) is False
        assert check_instant_death(0, 12) is False
        assert check_instant_death(5, 12) is False

    def test_boundary(self):
        """恰好为负max_hp也算即死"""
        assert check_instant_death(-10, 10) is True
        assert check_instant_death(-9, 10) is False
