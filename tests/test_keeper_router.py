"""守密人 NPC 路由：避免对话后一切输入都进 NPC Agent。"""

from datetime import datetime

import pytest

from src.agents.keeper_router import detect_npc_dialogue_target
from src.models.game_state import GameSession, NarrativeEntry, SceneState, NPC


def _session_with_npc() -> GameSession:
    npc = NPC(
        id="n1",
        name="店主老王",
        description="",
        is_alive=True,
    )
    scene = SceneState(
        id="s1",
        name="店铺",
        description="",
        npcs_present=["n1"],
    )
    return GameSession(
        id="sess1",
        name="t",
        current_scene=scene,
        npcs={"n1": npc},
    )


def _recent_with_npc_line() -> list[NarrativeEntry]:
    ts = datetime.now()
    return [
        NarrativeEntry(
            timestamp=ts,
            source="玩家甲",
            content="你好",
            entry_type="action",
        ),
        NarrativeEntry(
            timestamp=ts,
            source="店主老王",
            content="「要点什么？」",
            entry_type="narration",
        ),
    ]


def test_long_input_after_npc_goes_scene_not_npc():
    """NPC 刚说过话后，长段叙述不应再锁在 NPC 专线。"""
    s = _session_with_npc()
    recent = _recent_with_npc_line()
    text = (
        "我环视店内陈设，观察货架与墙角，留意其他客人的举动，并寻找通往后间或二楼的通道。"
        * 3
    )
    assert len(text) > 72
    assert detect_npc_dialogue_target(text, s, recent) is None


def test_short_reply_after_npc_still_npc():
    s = _session_with_npc()
    recent = _recent_with_npc_line()
    assert detect_npc_dialogue_target("没有，我什么也没看见。", s, recent) is not None


def test_scene_pivot_after_npc_goes_scene():
    s = _session_with_npc()
    recent = _recent_with_npc_line()
    assert detect_npc_dialogue_target("谢谢，我去楼上看看。", s, recent) is None


def test_explicit_dialogue_with_name():
    s = _session_with_npc()
    recent = _recent_with_npc_line()
    r = detect_npc_dialogue_target("我问店主老王昨天有没有陌生人来过。", s, recent)
    assert r is not None
    assert r[1].name == "店主老王"


def test_question_to_npc():
    s = _session_with_npc()
    recent = _recent_with_npc_line()
    r = detect_npc_dialogue_target("你昨晚几点关门的？", s, recent)
    assert r is not None


def test_short_you_meiyou_question_still_npc():
    """短句里的「有没有」仍视为向 NPC 发问。"""
    s = _session_with_npc()
    recent = _recent_with_npc_line()
    r = detect_npc_dialogue_target("你这儿有没有卖蜡烛？", s, recent)
    assert r is not None
