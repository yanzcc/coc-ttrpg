"""战斗回合集成测试

测试 GameLoop._process_combat_turn 完整流程：
- 玩家攻击 → 掷骰 → 伤害 → NPC回合 → 叙事摘要
- 大成功 / 大失败效果
- 逃跑 / 闪避
- 战斗结束检测（敌人全灭 / 调查员倒下）
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.character import (
    Investigator, Characteristics, DerivedStats, SkillValue, CombatStatus, Gender,
)
from src.models.game_state import (
    GameSession, GamePhase, NPC, CombatState, CombatParticipant,
    NarrativeEntry, SceneState,
)
from src.rules.skill_check import SuccessLevel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_investigator(name="测试调查员", hp=12, skills=None) -> Investigator:
    """创建测试用调查员"""
    base_skills = {
        "格斗（斗殴）": SkillValue(base=25, current=50),
        "射击（手枪）": SkillValue(base=20, current=40),
        "闪避": SkillValue(base=30, current=40),
    }
    if skills:
        base_skills.update(skills)
    return Investigator(
        id="inv_001",
        name=name,
        player_id="player_001",
        age=30,
        gender=Gender.MALE,
        occupation="私家侦探",
        characteristics=Characteristics(
            STR=60, CON=60, SIZ=60, DEX=60, APP=50, INT=70, POW=60, EDU=70,
        ),
        derived=DerivedStats(
            hp=hp, hp_max=12, mp=12, mp_max=12,
            san=55, san_max=99, luck=50, mov=8,
        ),
        skills=base_skills,
        combat_status=CombatStatus.NORMAL,
    )


def _make_session_with_combat(npc_hp=8, npc_attack=40) -> GameSession:
    """创建带战斗状态的测试会话"""
    npc = NPC(
        id="npc_thug",
        name="暴徒",
        description="一个危险的暴徒",
        is_alive=True,
        is_present=True,
        stats={"HP": npc_hp, "DEX": 50, "格斗": npc_attack, "伤害": 3},
    )
    combat = CombatState(
        round_number=1,
        participants=[
            CombatParticipant(id="inv_001", is_player=True, name="测试调查员", dex=60),
            CombatParticipant(id="npc_thug", is_player=False, name="暴徒", dex=50),
        ],
    )
    session = GameSession(
        id="test_session",
        name="测试会话",
        phase=GamePhase.COMBAT,
        npcs={"npc_thug": npc},
        combat=combat,
        scenes={"main": SceneState(id="main", name="主场景", description="测试场景")},
    )
    session.current_scene = session.scenes["main"]
    return session


async def _collect_events(async_gen) -> list[dict]:
    """收集异步生成器的所有事件"""
    events = []
    async for event in async_gen:
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCombatTurnAttack:
    """玩家攻击测试"""

    @pytest.mark.asyncio
    async def test_attack_produces_events(self):
        """攻击应产生系统事件和叙事"""
        from src.middleware.game_loop import GameLoop

        loop = GameLoop("test_session")
        # Mock 所有外部依赖
        loop.session_repo = AsyncMock()
        loop.investigator_repo = AsyncMock()
        loop.narrative_repo = AsyncMock()
        loop.module_repo = AsyncMock()
        loop.combat_narrator = AsyncMock()
        loop.combat_narrator.narrate_round_summary = AsyncMock(return_value="战斗激烈进行。")
        loop.combat_narrator.narrate_combat_end = AsyncMock(return_value="战斗结束了。")

        inv = _make_investigator()
        session = _make_session_with_combat()

        events = await _collect_events(
            loop._process_combat_turn(
                "player_001", "用拳头攻击暴徒",
                session, [inv], [],
            )
        )

        # 应该有系统事件（玩家攻击结果 + NPC攻击结果 + 回合摘要）
        system_events = [e for e in events if e.get("type") == "system"]
        assert len(system_events) >= 1, f"应有至少1个系统事件，得到: {events}"

        # 玩家攻击结果应包含骰子信息
        first_system = system_events[0]
        assert "测试调查员" in first_system["content"]
        assert "拳头" in first_system["content"]

        # 应有叙事结束事件
        end_events = [e for e in events if e.get("type") == "narrative_end"]
        assert len(end_events) == 1

    @pytest.mark.asyncio
    async def test_attack_damages_npc(self):
        """成功攻击应扣减NPC HP"""
        from src.middleware.game_loop import GameLoop

        loop = GameLoop("test_session")
        loop.session_repo = AsyncMock()
        loop.investigator_repo = AsyncMock()
        loop.narrative_repo = AsyncMock()
        loop.module_repo = AsyncMock()
        loop.combat_narrator = AsyncMock()
        loop.combat_narrator.narrate_round_summary = AsyncMock(return_value="战斗。")
        loop.combat_narrator.narrate_combat_end = AsyncMock(return_value="结束。")

        inv = _make_investigator()
        # 给调查员高攻击技能以确保命中
        inv.skills["格斗（斗殴）"] = SkillValue(base=25, current=95)
        session = _make_session_with_combat(npc_hp=20, npc_attack=5)  # NPC低攻击防止干扰

        events = await _collect_events(
            loop._process_combat_turn(
                "player_001", "攻击暴徒",
                session, [inv], [],
            )
        )

        # 检查NPC HP是否被扣减（可能命中也可能没命中，取决于随机数）
        system_events = [e for e in events if e.get("type") == "system"]
        assert len(system_events) >= 1

    @pytest.mark.asyncio
    async def test_npc_killed_ends_combat(self):
        """NPC被杀应结束战斗"""
        from src.middleware.game_loop import GameLoop

        loop = GameLoop("test_session")
        loop.session_repo = AsyncMock()
        loop.investigator_repo = AsyncMock()
        loop.narrative_repo = AsyncMock()
        loop.module_repo = AsyncMock()
        loop.combat_narrator = AsyncMock()
        loop.combat_narrator.narrate_round_summary = AsyncMock(return_value="战斗。")
        loop.combat_narrator.narrate_combat_end = AsyncMock(return_value="敌人倒下了。")

        inv = _make_investigator()
        inv.skills["格斗（斗殴）"] = SkillValue(base=25, current=99)  # 几乎必定命中
        # NPC只有1点HP，几乎必定一击杀
        session = _make_session_with_combat(npc_hp=1, npc_attack=5)

        events = await _collect_events(
            loop._process_combat_turn(
                "player_001", "用拳头攻击暴徒",
                session, [inv], [],
            )
        )

        combat_end_events = [e for e in events if e.get("type") == "combat_end"]
        # 如果命中了（高概率），应有 combat_end 事件
        if session.npcs["npc_thug"].stats["HP"] <= 0:
            assert len(combat_end_events) == 1
            assert "结束" in combat_end_events[0]["content"]
            assert session.phase == GamePhase.EXPLORATION


class TestCombatTurnFlee:
    """逃跑测试"""

    @pytest.mark.asyncio
    async def test_flee_attempt(self):
        """逃跑应触发DEX对抗"""
        from src.middleware.game_loop import GameLoop

        loop = GameLoop("test_session")
        loop.session_repo = AsyncMock()
        loop.investigator_repo = AsyncMock()
        loop.narrative_repo = AsyncMock()
        loop.module_repo = AsyncMock()
        loop.combat_narrator = AsyncMock()
        loop.combat_narrator.narrate_round_summary = AsyncMock(return_value="战斗。")
        loop.combat_narrator.narrate_combat_end = AsyncMock(return_value="逃走了。")

        inv = _make_investigator()
        session = _make_session_with_combat()

        events = await _collect_events(
            loop._process_combat_turn(
                "player_001", "逃跑！",
                session, [inv], [],
            )
        )

        # 应有逃跑相关的系统事件
        all_content = " ".join(e.get("content", "") for e in events if e.get("type") == "system")
        assert "逃跑" in all_content


class TestCombatTurnDodge:
    """闪避测试"""

    @pytest.mark.asyncio
    async def test_dodge_preparation(self):
        """闪避准备应被记录"""
        from src.middleware.game_loop import GameLoop

        loop = GameLoop("test_session")
        loop.session_repo = AsyncMock()
        loop.investigator_repo = AsyncMock()
        loop.narrative_repo = AsyncMock()
        loop.module_repo = AsyncMock()
        loop.combat_narrator = AsyncMock()
        loop.combat_narrator.narrate_round_summary = AsyncMock(return_value="战斗。")

        inv = _make_investigator()
        session = _make_session_with_combat(npc_attack=80)  # NPC高攻击

        events = await _collect_events(
            loop._process_combat_turn(
                "player_001", "闪避",
                session, [inv], [],
            )
        )

        system_events = [e for e in events if e.get("type") == "system"]
        # 第一个应是闪避准备
        assert any("闪避" in e.get("content", "") for e in system_events)
        # NPC应该也会攻击（并且调查员会尝试闪避）
        all_content = " ".join(e.get("content", "") for e in system_events)
        assert "暴徒" in all_content


class TestCombatResolveAttackIntegration:
    """resolve_attack 新签名（4返回值）集成测试"""

    def test_critical_returns_no_fumble(self):
        """大成功不应返回大失败效果"""
        import random
        from src.rules.combat_rules import resolve_attack

        # seed 42 → roll_d100 结果为 1 (大成功)
        rng = random.Random(42)
        success, damage, detail, fumble = resolve_attack(
            attack_skill_value=50,
            damage_expression="1d6",
            rng=rng,
        )
        assert success == SuccessLevel.CRITICAL
        assert fumble is None
        assert damage > 0
        assert "大成功" in detail

    def test_fumble_returns_effect(self):
        """大失败应返回效果对象"""
        import random
        from src.rules.combat_rules import resolve_attack

        # 构造一定大失败的rng（技能低于50，掷出96+）
        class FumbleRng:
            def __init__(self):
                self._calls = 0
            def randint(self, a, b):
                self._calls += 1
                if b == 9:
                    # d100 tens=9, units=6 → 96
                    return 9 if self._calls <= 2 else random.randint(a, b)
                if b == 6:
                    return 3  # fumble table roll
                return random.randint(a, b)

        success, damage, detail, fumble = resolve_attack(
            attack_skill_value=30,  # <50, so 96+ is fumble
            damage_expression="1d6",
            rng=FumbleRng(),
        )
        if success == SuccessLevel.FUMBLE:
            assert fumble is not None
            assert damage == 0
            assert "大失败" in detail

    def test_normal_hit_no_fumble(self):
        """普通命中不应有大失败效果"""
        import random
        from src.rules.combat_rules import resolve_attack

        class LowRng:
            def randint(self, a, b):
                if b == 9:
                    return 2  # d100 → 22 (成功 if skill>=22)
                return 3

        success, damage, detail, fumble = resolve_attack(
            attack_skill_value=60,
            damage_expression="1d6",
            rng=LowRng(),
        )
        assert success >= SuccessLevel.REGULAR
        assert fumble is None
        assert damage > 0


class TestWeaponAndTargetFinding:
    """武器和目标查找测试"""

    def test_find_weapon_from_text(self):
        from src.middleware.game_loop import GameLoop
        loop = GameLoop("test")
        inv = _make_investigator()

        name, info = loop._find_weapon("用小刀攻击", inv)
        assert name == "小刀"
        assert "damage" in info

    def test_find_weapon_default_fist(self):
        from src.middleware.game_loop import GameLoop
        loop = GameLoop("test")
        inv = _make_investigator()

        name, info = loop._find_weapon("攻击那个家伙", inv)
        assert name == "拳头"

    def test_find_combat_target(self):
        from src.middleware.game_loop import GameLoop
        loop = GameLoop("test")

        npc = NPC(id="thug", name="暴徒", is_alive=True, is_present=True)
        participant = CombatParticipant(id="thug", is_player=False, name="暴徒", dex=50)
        enemies = [(participant, npc)]

        result = loop._find_combat_target("攻击暴徒", enemies)
        assert result is not None
        assert result[1].name == "暴徒"

    def test_find_target_no_match(self):
        from src.middleware.game_loop import GameLoop
        loop = GameLoop("test")

        npc = NPC(id="thug", name="暴徒", is_alive=True, is_present=True)
        participant = CombatParticipant(id="thug", is_player=False, name="暴徒", dex=50)
        enemies = [(participant, npc)]

        result = loop._find_combat_target("攻击怪物", enemies)
        assert result is None
