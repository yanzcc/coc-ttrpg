"""数据访问层

封装对数据库的CRUD操作。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import select, delete

from .database import (
    get_session, SessionTable, InvestigatorTable,
    NarrativeLogTable, ModuleTable, TokenUsageTable,
)
from ..models.character import Investigator
from ..models.game_state import GameSession, NarrativeEntry
from ..models.story_module import StoryModule


class SessionRepository:
    """游戏会话数据仓库"""

    async def create(self, session: GameSession) -> None:
        async with await get_session() as db:
            row = SessionTable(
                id=session.id,
                name=session.name,
                created_at=session.created_at,
                updated_at=session.updated_at,
                phase=session.phase.value,
                module_id=session.module_id,
                state_json=session.model_dump(mode="json"),
            )
            db.add(row)
            await db.commit()

    async def get(self, session_id: str) -> Optional[GameSession]:
        async with await get_session() as db:
            result = await db.execute(
                select(SessionTable).where(SessionTable.id == session_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return GameSession.model_validate(row.state_json)

    async def update(self, session: GameSession) -> None:
        async with await get_session() as db:
            result = await db.execute(
                select(SessionTable).where(SessionTable.id == session.id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.updated_at = datetime.now()
                row.phase = session.phase.value
                row.state_json = session.model_dump(mode="json")
                await db.commit()

    async def list_all(self) -> list[dict]:
        async with await get_session() as db:
            result = await db.execute(
                select(SessionTable.id, SessionTable.name,
                       SessionTable.phase, SessionTable.updated_at)
            )
            return [
                {"id": r.id, "name": r.name, "phase": r.phase, "updated_at": str(r.updated_at)}
                for r in result.all()
            ]

    async def delete(self, session_id: str) -> None:
        async with await get_session() as db:
            await db.execute(
                delete(SessionTable).where(SessionTable.id == session_id)
            )
            await db.commit()


class InvestigatorRepository:
    """调查员数据仓库"""

    async def save(self, investigator: Investigator, session_id: str) -> None:
        async with await get_session() as db:
            result = await db.execute(
                select(InvestigatorTable).where(InvestigatorTable.id == investigator.id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.data_json = investigator.model_dump(mode="json")
                row.name = investigator.name
                row.player_id = investigator.player_id
                # 列表查询依赖本列；assign / 带会话创建必须写回，否则调查员不会出现在会话中
                if session_id:
                    row.session_id = session_id
            else:
                row = InvestigatorTable(
                    id=investigator.id,
                    session_id=session_id or "",
                    player_id=investigator.player_id,
                    name=investigator.name,
                    data_json=investigator.model_dump(mode="json"),
                )
                db.add(row)
            await db.commit()

    async def get(self, investigator_id: str) -> Optional[Investigator]:
        async with await get_session() as db:
            result = await db.execute(
                select(InvestigatorTable).where(InvestigatorTable.id == investigator_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return Investigator.model_validate(row.data_json)

    async def list_by_session(self, session_id: str) -> list[Investigator]:
        async with await get_session() as db:
            result = await db.execute(
                select(InvestigatorTable).where(InvestigatorTable.session_id == session_id)
            )
            return [Investigator.model_validate(r.data_json) for r in result.scalars().all()]

    async def list_by_player(self, player_id: str) -> list[Investigator]:
        """列出玩家的所有调查员（跨会话）"""
        async with await get_session() as db:
            result = await db.execute(
                select(InvestigatorTable).where(InvestigatorTable.player_id == player_id)
            )
            return [Investigator.model_validate(r.data_json) for r in result.scalars().all()]

    async def list_all(self) -> list[dict]:
        """列出所有调查员的摘要信息"""
        async with await get_session() as db:
            result = await db.execute(
                select(InvestigatorTable.id, InvestigatorTable.player_id,
                       InvestigatorTable.name, InvestigatorTable.session_id)
            )
            return [
                {"id": r.id, "player_id": r.player_id,
                 "name": r.name, "session_id": r.session_id}
                for r in result.all()
            ]

    async def delete(self, investigator_id: str) -> None:
        async with await get_session() as db:
            await db.execute(
                delete(InvestigatorTable).where(InvestigatorTable.id == investigator_id)
            )
            await db.commit()


class NarrativeRepository:
    """叙事日志数据仓库"""

    async def append(self, session_id: str, entry: NarrativeEntry) -> None:
        async with await get_session() as db:
            row = NarrativeLogTable(
                session_id=session_id,
                timestamp=entry.timestamp,
                source=entry.source,
                content=entry.content,
                entry_type=entry.entry_type,
                metadata_json=entry.metadata,
            )
            db.add(row)
            await db.commit()

    async def get_recent(self, session_id: str, limit: int = 20) -> list[NarrativeEntry]:
        async with await get_session() as db:
            result = await db.execute(
                select(NarrativeLogTable)
                .where(NarrativeLogTable.session_id == session_id)
                .order_by(NarrativeLogTable.id.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
            entries = []
            for r in reversed(rows):
                entries.append(NarrativeEntry(
                    timestamp=r.timestamp,
                    source=r.source,
                    content=r.content,
                    entry_type=r.entry_type,
                    metadata=r.metadata_json or {},
                ))
            return entries

    async def count(self, session_id: str) -> int:
        async with await get_session() as db:
            from sqlalchemy import func
            result = await db.execute(
                select(func.count()).where(NarrativeLogTable.session_id == session_id)
            )
            return result.scalar()


class ModuleRepository:
    """故事模组数据仓库"""

    async def save(self, module: StoryModule, module_id: str) -> None:
        async with await get_session() as db:
            result = await db.execute(
                select(ModuleTable).where(ModuleTable.id == module_id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.data_json = module.model_dump(mode="json")
            else:
                row = ModuleTable(
                    id=module_id,
                    title=module.metadata.title,
                    author=module.metadata.author,
                    data_json=module.model_dump(mode="json"),
                )
                db.add(row)
            await db.commit()

    async def get(self, module_id: str) -> Optional[StoryModule]:
        async with await get_session() as db:
            result = await db.execute(
                select(ModuleTable).where(ModuleTable.id == module_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return StoryModule.model_validate(row.data_json)

    async def list_all(self) -> list[dict]:
        async with await get_session() as db:
            result = await db.execute(
                select(ModuleTable.id, ModuleTable.title, ModuleTable.author)
            )
            return [{"id": r.id, "title": r.title, "author": r.author} for r in result.all()]


class TokenUsageRepository:
    """Token用量数据仓库"""

    async def record(self, session_id: str, agent_name: str,
                     input_tokens: int, output_tokens: int,
                     cached_tokens: int = 0) -> None:
        # 估算成本
        input_cost = (input_tokens - cached_tokens) * 3.0 / 1_000_000
        cached_cost = cached_tokens * 0.3 / 1_000_000
        output_cost = output_tokens * 15.0 / 1_000_000
        estimated = input_cost + cached_cost + output_cost

        async with await get_session() as db:
            row = TokenUsageTable(
                session_id=session_id,
                timestamp=datetime.now(),
                agent_name=agent_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                estimated_cost=estimated,
            )
            db.add(row)
            await db.commit()

    async def get_session_summary(self, session_id: str) -> dict:
        async with await get_session() as db:
            from sqlalchemy import func
            result = await db.execute(
                select(
                    TokenUsageTable.agent_name,
                    func.sum(TokenUsageTable.input_tokens).label("input"),
                    func.sum(TokenUsageTable.output_tokens).label("output"),
                    func.sum(TokenUsageTable.cached_tokens).label("cached"),
                    func.sum(TokenUsageTable.estimated_cost).label("cost"),
                )
                .where(TokenUsageTable.session_id == session_id)
                .group_by(TokenUsageTable.agent_name)
            )
            by_agent = {}
            total = {"input": 0, "output": 0, "cached": 0, "cost": 0.0}
            for r in result.all():
                by_agent[r.agent_name] = {
                    "input": r.input, "output": r.output,
                    "cached": r.cached, "cost": round(r.cost, 4),
                }
                total["input"] += r.input
                total["output"] += r.output
                total["cached"] += r.cached
                total["cost"] += r.cost
            total["cost"] = round(total["cost"], 4)
            return {"total": total, "by_agent": by_agent}
