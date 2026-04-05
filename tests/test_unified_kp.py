"""UnifiedKP 与 keeper_router 路由一致。"""

from datetime import datetime

import pytest

from src.agents.hierarchical_keeper import UnifiedKP
from src.agents.keeper_router import detect_npc_dialogue_target
from src.models.game_state import GameSession, NarrativeEntry, SceneState, NPC


def _fixture():
    npc = NPC(id="n1", name="店主老王", description="", is_alive=True)
    scene = SceneState(id="s1", name="店", description="", npcs_present=["n1"])
    session = GameSession(id="s", name="t", current_scene=scene, npcs={"n1": npc})
    ts = datetime.now()
    recent = [
        NarrativeEntry(timestamp=ts, source="p", content="嗨", entry_type="action"),
        NarrativeEntry(
            timestamp=ts, source="店主老王", content="「嗯？」", entry_type="narration",
        ),
    ]
    return session, recent


@pytest.mark.asyncio
async def test_route_matches_detect_npc_tuple_second():
    session, recent = _fixture()
    kp = UnifiedKP(token_tracker=None)
    action = "没有。"
    hit = detect_npc_dialogue_target(action, session, recent)
    routed = await kp.route_player_action(action, session, recent)
    assert hit is not None and routed is not None
    assert routed.id == hit[0]
    assert routed.name == hit[1].name
