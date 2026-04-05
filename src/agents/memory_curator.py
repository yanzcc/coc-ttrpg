"""从守密人叙事中抽取可记忆条目，写入会话状态。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from .base import BaseAgent
from ..config import get_settings
from ..middleware.token_tracker import TokenTracker
from ..models.game_state import GameSession, KeeperMemoryState

logger = logging.getLogger(__name__)

_CURATOR_SYSTEM = """你是跑团记录员。根据【本轮守密人叙事】提取应长期记住的信息，只输出一个JSON对象，不要其它文字。

规则：
1. new_facts：本轮**明确成立**的剧情事实、已告诉调查员的线索、已确认的发现（短句，每条一行意）。不要猜测。
2. npc_memory_by_name：对象，键为NPC**全名**（须与已知列表一致），值为字符串数组——该NPC**本轮所说或所承认**的可记住内容。
3. location_canon：对象，键为**地点名**，值为**一句**环境定稿描写（若叙事首次较详细描写某地点外观则提取；已存在则不要改）。

若无值得记录的内容，三项都为空对象/空数组。

JSON 模板：
{"new_facts":[],"npc_memory_by_name":{},"location_canon":{}}
"""


async def merge_narration_into_session_memory(
    narration_clean: str,
    session: GameSession,
    token_tracker: Optional[TokenTracker] = None,
) -> None:
    """解析叙事并合并到 session.keeper_memory（就地修改）。"""
    if not narration_clean or len(narration_clean) < 12:
        return

    agent = BaseAgent(
        name="记忆整理",
        system_prompt=_CURATOR_SYSTEM,
        token_tracker=token_tracker,
        max_tokens=get_settings().agents.memory_curator,
    )
    npc_names = [n.name for n in session.npcs.values() if n.name]
    known = "、".join(npc_names) if npc_names else "（暂无登记NPC）"
    user = (
        f"已知NPC全名：{known}\n"
        f"当前场景：{session.current_scene.name if session.current_scene else '未知'}\n\n"
        f"【本轮叙事】\n{narration_clean[:6000]}"
    )
    try:
        text, _u = await agent.invoke(
            [{"role": "user", "content": user}],
            temperature=0.1,
        )
        data = _parse_json_obj(text)
    except Exception:
        logger.exception("记忆提取失败")
        return

    km: KeeperMemoryState = session.keeper_memory

    for fact in data.get("new_facts") or []:
        if isinstance(fact, str):
            f = fact.strip()
            if f and f not in km.established_facts:
                km.established_facts.append(f)
    km.established_facts = km.established_facts[-45:]

    name_to_id = {n.name: nid for nid, n in session.npcs.items() if n.name}
    for name, lines in (data.get("npc_memory_by_name") or {}).items():
        if not isinstance(name, str) or name not in name_to_id:
            continue
        nid = name_to_id[name]
        if not isinstance(lines, list):
            continue
        km.npc_memories.setdefault(nid, [])
        for line in lines:
            if isinstance(line, str):
                s = line.strip()
                if s and s not in km.npc_memories[nid]:
                    km.npc_memories[nid].append(s)
        km.npc_memories[nid] = km.npc_memories[nid][-14:]

    for loc, desc in (data.get("location_canon") or {}).items():
        if isinstance(loc, str) and isinstance(desc, str):
            loc_k = loc.strip()
            d = desc.strip()
            if loc_k and d and loc_k not in km.location_canon:
                km.location_canon[loc_k] = d[:600]


def _parse_json_obj(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        return json.loads(m.group())
    return {}
