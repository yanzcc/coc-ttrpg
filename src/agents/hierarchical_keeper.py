"""分层守密人：总 KP（协调）与下属 Agent（旁白 / NPC 扮演）。

架构::

    UnifiedKP（总守密人 KP）
    ├── narration   → SceneKeeperAgent   （纯旁白 / 场景叙事）
    ├── npc_actor   → NPCKeeperAgent     （单 NPC 台词与神态）
    └── （可选）KeeperSupervisorAgent（Haiku）→ 判断本轮走 narration 还是 npc_actor

路由顺序（`route_player_action`）：
1. 若启用监督且环境未禁用：调用 Haiku；若返回 `trust_supervisor`，直接采用。
2. 否则回退 `detect_npc_dialogue_target` 规则。

环境变量 `KEEPER_SUPERVISOR_ENABLED=0` 可覆盖 yaml，便于测试或无密钥环境。

`GameLoop` 只应持有 `UnifiedKP`。
"""

from __future__ import annotations

import os
from typing import Optional

from ..config import get_settings
from ..middleware.token_tracker import TokenTracker
from ..models.game_state import GameSession, NarrativeEntry, NPC
from .dual_keepers import NPCKeeperAgent, SceneKeeperAgent
from .keeper_router import detect_npc_dialogue_target
from .keeper_supervisor import KeeperSupervisorAgent


class UnifiedKP:
    """总守密人（KP）：管理下属 Agent 与可选 Haiku 监督路由。"""

    def __init__(self, token_tracker: Optional[TokenTracker] = None) -> None:
        self.token_tracker = token_tracker
        self.narration = SceneKeeperAgent(token_tracker=token_tracker)
        self.npc_actor = NPCKeeperAgent(token_tracker=token_tracker)
        self._supervisor: Optional[KeeperSupervisorAgent] = None

    def _supervisor_if_enabled(self) -> Optional[KeeperSupervisorAgent]:
        if os.getenv("KEEPER_SUPERVISOR_ENABLED", "").lower() in ("0", "false", "no"):
            return None
        if not get_settings().agents.keeper_supervisor_enabled:
            return None
        if self._supervisor is None:
            self._supervisor = KeeperSupervisorAgent(token_tracker=self.token_tracker)
        return self._supervisor

    async def route_player_action(
        self,
        action_text: str,
        session: GameSession,
        recent_narrative: Optional[list[NarrativeEntry]] = None,
    ) -> Optional[NPC]:
        """若应走 NPC 专线，返回目标 `NPC`；否则返回 `None`（旁白）。"""
        sup = self._supervisor_if_enabled()
        if sup is not None:
            outcome = await sup.classify_route(
                action_text, session, recent_narrative,
            )
            if outcome.trust_supervisor:
                return outcome.npc

        hit = detect_npc_dialogue_target(action_text, session, recent_narrative)
        if hit:
            return hit[1]
        return None
