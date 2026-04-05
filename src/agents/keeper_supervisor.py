"""KP 监督路由：用轻量模型（默认 Claude Haiku）判断本轮走旁白还是 NPC 专线。"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

import anthropic

from ..config import get_settings
from ..middleware.token_tracker import TokenTracker
from ..models.game_state import GameSession, NarrativeEntry, NPC
from .base import BaseAgent

logger = logging.getLogger(__name__)

# claude-3-5-haiku-20241022 等旧 ID 在不少租户已 404；按序尝试直至成功
_KEEPER_SUPERVISOR_MODEL_FALLBACKS: tuple[str, ...] = (
    "claude-haiku-4-5-20251001",
    "claude-haiku-4-5",
    "claude-3-haiku-20240307",
)

KEEPER_SUPERVISOR_SYSTEM_PROMPT = """你是克苏鲁 TRPG 的「总守密人」下属的路由模块，只做分类，不写叙事。

根据【在场 NPC】【最近叙事摘要】【玩家行动】判断本轮应由谁回应：

1) narration（旁白）
   - 调查环境、移动、搜查、观察场面、战斗意图、对多人同时发生的行为
   - 没有明确、唯一的对话对象，或明显不是在接某个 NPC 的话

2) npc_dialogue（NPC 专线）
   - 玩家明显在对某个在场的 NPC 说话、提问、接话茬
   - 只有能唯一对应到「在场 NPC 列表」中某一人时才选此项

**只输出一个 JSON 对象**（不要 markdown 围栏、不要解释），格式严格如下：
{"delegate":"narration"|"npc_dialogue","npc_name":null|"名字"}

规则：
- delegate 为 npc_dialogue 时，npc_name 必须是用户消息里「在场 NPC」列表中的**完全一致**的名字；无法唯一确定则 delegate 必须为 narration 且 npc_name 为 null。
- delegate 为 narration 时 npc_name 必须为 null。
"""


@dataclass
class SupervisorRouteOutcome:
    """Haiku 路由结果。

    trust_supervisor=True：应直接采用（npc 为 None 表示旁白；非 None 表示该 NPC 专线）。
    trust_supervisor=False：解析失败或无法匹配 NPC，调用方应回退规则路由。
    """

    trust_supervisor: bool
    npc: Optional[NPC] = None


def _extract_json_object(text: str) -> Optional[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _format_present_npcs(session: GameSession) -> str:
    names: list[str] = []
    for nid, npc in session.npcs.items():
        if not npc.name or not npc.is_alive:
            continue
        if session.current_scene and session.current_scene.npcs_present:
            if nid not in session.current_scene.npcs_present:
                continue
        names.append(npc.name)
    return "、".join(names) if names else "（无）"


def _format_recent(recent: Optional[list[NarrativeEntry]], limit: int = 8) -> str:
    if not recent:
        return "（无）"
    lines: list[str] = []
    for e in recent[-limit:]:
        src = e.source or "?"
        typ = e.entry_type or ""
        body = e.content[:200] + ("…" if len(e.content) > 200 else "")
        lines.append(f"- [{typ}]{src}: {body}")
    return "\n".join(lines)


def _resolve_npc_by_name(session: GameSession, name: str) -> Optional[NPC]:
    if not name or not str(name).strip():
        return None
    name = str(name).strip()
    candidates: list[NPC] = []
    for nid, npc in session.npcs.items():
        if not npc.name or not npc.is_alive:
            continue
        if session.current_scene and session.current_scene.npcs_present:
            if nid not in session.current_scene.npcs_present:
                continue
        candidates.append(npc)
    for npc in candidates:
        if npc.name == name:
            return npc
    for npc in candidates:
        if name in npc.name or npc.name in name:
            return npc
    return None


class KeeperSupervisorAgent(BaseAgent):
    """Haiku 等轻量模型：输出 JSON 路由。"""

    def __init__(self, token_tracker: Optional[TokenTracker] = None) -> None:
        _s = get_settings().agents
        model = os.getenv("KEEPER_SUPERVISOR_MODEL") or _s.keeper_supervisor_model
        max_toks = _s.keeper_supervisor_max_tokens
        super().__init__(
            name="KP监督",
            system_prompt=KEEPER_SUPERVISOR_SYSTEM_PROMPT,
            token_tracker=token_tracker,
            model=model,
            max_tokens=max_toks,
        )

    async def classify_route(
        self,
        action_text: str,
        session: GameSession,
        recent_narrative: Optional[list[NarrativeEntry]] = None,
    ) -> SupervisorRouteOutcome:
        user = (
            f"【在场 NPC】\n{_format_present_npcs(session)}\n\n"
            f"【最近叙事】\n{_format_recent(recent_narrative)}\n\n"
            f"【玩家行动】\n{action_text.strip()}"
        )
        messages = [{"role": "user", "content": user}]
        candidates: list[str] = []
        for m in (self.model, *_KEEPER_SUPERVISOR_MODEL_FALLBACKS):
            if m and m not in candidates:
                candidates.append(m)

        saved_model = self.model
        text = ""
        try:
            last_nf: Optional[anthropic.NotFoundError] = None
            for mid in candidates:
                self.model = mid
                try:
                    text, _usage = await self.invoke(messages, temperature=0.2)
                    if mid != saved_model:
                        logger.info("KP 监督已切换到可用模型: %s", mid)
                    break
                except anthropic.NotFoundError as e:
                    last_nf = e
                    logger.warning("KP 监督模型不可用（404）: %s", mid)
                    continue
            else:
                if last_nf:
                    raise last_nf
                raise RuntimeError("KP 监督：无可用模型候选")
        except anthropic.NotFoundError:
            logger.warning(
                "KP 监督所有 Haiku 候选均 404，将回退规则路由",
                exc_info=False,
            )
            return SupervisorRouteOutcome(trust_supervisor=False)
        except Exception:
            logger.exception("KP 监督(Haiku) 调用失败，将回退规则路由")
            return SupervisorRouteOutcome(trust_supervisor=False)
        finally:
            self.model = saved_model

        data = _extract_json_object(text)
        if not data or not isinstance(data, dict):
            logger.warning("KP 监督返回无法解析的 JSON，回退规则：%s", text[:200])
            return SupervisorRouteOutcome(trust_supervisor=False)

        del_ = data.get("delegate")
        if del_ not in ("narration", "npc_dialogue"):
            return SupervisorRouteOutcome(trust_supervisor=False)

        if del_ == "narration":
            if data.get("npc_name") not in (None, "", "null"):
                return SupervisorRouteOutcome(trust_supervisor=False)
            return SupervisorRouteOutcome(trust_supervisor=True, npc=None)

        name = data.get("npc_name")
        npc = _resolve_npc_by_name(session, str(name)) if name not in (None, "", "null") else None
        if npc is None:
            logger.info("KP 监督指定 npc_dialogue 但无法匹配在场 NPC，回退规则")
            return SupervisorRouteOutcome(trust_supervisor=False)
        return SupervisorRouteOutcome(trust_supervisor=True, npc=npc)
