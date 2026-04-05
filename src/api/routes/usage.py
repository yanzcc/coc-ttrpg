"""Token用量监控API路由"""

from __future__ import annotations

from fastapi import APIRouter

from ...middleware.game_loop import get_game_loop, _game_loops
from ...storage.repositories import TokenUsageRepository

router = APIRouter()
usage_repo = TokenUsageRepository()


@router.get("/{session_id}")
async def get_usage(session_id: str):
    """获取指定会话的Token用量摘要

    优先从内存中的GameLoop获取实时数据，
    回退到数据库中的历史数据。
    """
    if session_id in _game_loops:
        return _game_loops[session_id].get_usage_summary()
    return await usage_repo.get_session_summary(session_id)
