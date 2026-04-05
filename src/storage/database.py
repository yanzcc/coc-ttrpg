"""数据库配置

异步SQLite数据库连接和表定义。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import (
    Column, DateTime, Float, Integer, JSON, String, Text,
    create_engine, event,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from ..config import get_settings


def get_data_dir() -> Path:
    """数据目录（来自 config/app.yaml paths.data_dir）。"""
    return get_settings().resolved_data_dir()


def get_database_url() -> str:
    """连接串：环境变量 DATABASE_URL > yaml database.url > 默认 SQLite。"""
    return get_settings().effective_database_url()


class Base(DeclarativeBase):
    pass


class SessionTable(Base):
    """游戏会话表"""
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    name = Column(String, default="未命名会话")
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    phase = Column(String, default="大厅")
    module_id = Column(String, nullable=True)
    state_json = Column(JSON, default=dict)  # 完整的GameSession序列化


class InvestigatorTable(Base):
    """调查员表"""
    __tablename__ = "investigators"

    id = Column(String, primary_key=True)
    session_id = Column(String, index=True)
    player_id = Column(String, index=True)
    name = Column(String)
    data_json = Column(JSON)  # 完整的Investigator序列化


class NarrativeLogTable(Base):
    """叙事日志表"""
    __tablename__ = "narrative_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, index=True)
    timestamp = Column(DateTime)
    source = Column(String)        # "守密人" / "系统" / 玩家ID
    content = Column(Text)
    entry_type = Column(String)    # narration / action / dice_roll / system
    metadata_json = Column(JSON, default=dict)


class ModuleTable(Base):
    """故事模组表"""
    __tablename__ = "modules"

    id = Column(String, primary_key=True)
    title = Column(String)
    author = Column(String, default="")
    data_json = Column(JSON)  # 完整的StoryModule序列化


class TokenUsageTable(Base):
    """Token用量记录表"""
    __tablename__ = "token_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, index=True)
    timestamp = Column(DateTime)
    agent_name = Column(String)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cached_tokens = Column(Integer, default=0)
    estimated_cost = Column(Float, default=0.0)


# 全局引擎和会话工厂
_engine = None
_session_factory = None


async def init_db(database_url: str | None = None) -> None:
    """初始化数据库，创建所有表"""
    global _engine, _session_factory

    url = database_url or get_database_url()

    # 确保数据目录存在
    if "sqlite" in url:
        db_path = url.split("///")[-1]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    _engine = create_async_engine(url, echo=False)
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """获取数据库会话"""
    if _session_factory is None:
        await init_db()
    return _session_factory()


async def close_db() -> None:
    """关闭数据库连接"""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
