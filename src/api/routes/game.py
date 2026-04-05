"""游戏会话API路由"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...config import get_settings
from ...models.game_state import (
    GameSession, GamePhase, NPC, SceneState, Clue,
)
from ...models.story_module import StoryModule
from ...storage.repositories import SessionRepository, ModuleRepository
from ...agents.story_gen import StoryGeneratorAgent
from ...modules.loader import ModuleLoader, get_sample_modules_dir
from ...modules.samples import list_sample_modules, get_sample_module_path
from ...middleware.game_loop import get_game_loop

router = APIRouter()
logger = logging.getLogger(__name__)
session_repo = SessionRepository()
module_repo = ModuleRepository()


def populate_session_from_module(session: GameSession, module: StoryModule) -> None:
    """将模组数据注入会话运行时状态：NPC、场景、线索、当前场景。

    仅在加载模组时调用一次。后续游戏中 session 上的运行时数据
    由 game_loop / memory_curator 持续更新。
    """
    # ---- NPC ----
    for mnpc in module.npcs:
        session.npcs[mnpc.id] = NPC(
            id=mnpc.id,
            name=mnpc.name,
            description=(
                f"{mnpc.occupation}，{mnpc.age}岁。{mnpc.description}"
                if mnpc.occupation else mnpc.description
            ),
            is_alive=True,
            is_present=False,  # 后面由开场场景决定
            attitude=mnpc.initial_attitude or "中立",
            stats=dict(mnpc.stats),
            secret=mnpc.secret,
            dialogue_notes=(
                mnpc.dialogue_style
                + (f"  性格：{mnpc.personality}" if mnpc.personality else "")
                + (f"  动机：{mnpc.motivation}" if mnpc.motivation else "")
            ),
        )

    # ---- 线索 ----
    for mclue in module.clues:
        session.clues[mclue.id] = Clue(
            id=mclue.id,
            name=mclue.name,
            description=mclue.description,
            is_discovered=False,
            location_id=mclue.location_id or None,
            leads_to=list(mclue.leads_to),
        )

    # ---- 场景 ----
    for mscene in module.scenes:
        loc = module.get_location(mscene.location_id) if mscene.location_id else None
        scene_state = SceneState(
            id=mscene.id,
            name=mscene.title,
            description=mscene.description or (loc.description if loc else ""),
            location_type="",
            npcs_present=list(mscene.npc_ids),
            clues_available=list(mscene.clue_ids),
            clues_discovered=[],
            exits={},
            atmosphere=loc.atmosphere if loc else "",
            events=[],
        )
        if loc and loc.connections:
            scene_state.exits = dict(loc.connections)
        session.scenes[mscene.id] = scene_state

    # ---- 设定开场场景并标记在场 NPC ----
    opening = module.get_opening_scene()
    if opening and opening.id in session.scenes:
        session.current_scene = session.scenes[opening.id]
        for npc_id in opening.npc_ids:
            if npc_id in session.npcs:
                session.npcs[npc_id].is_present = True


# ---- 请求/响应模型 ----

class CreateSessionRequest(BaseModel):
    name: str = "未命名会话"
    module_id: str | None = None


class CreateSessionResponse(BaseModel):
    id: str
    name: str


class LoadModuleRequest(BaseModel):
    """为会话加载模组的请求"""
    module_id: str | None = None
    sample_name: str | None = None


class GenerateModuleRequest(BaseModel):
    """生成新模组的请求"""
    seed_prompt: str
    era: str = "1920s"
    player_count: int = 3
    difficulty: str = "普通"


# ---- 会话端点 ----

@router.post("/create", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest):
    """创建新游戏会话"""
    session = GameSession(
        id=str(uuid.uuid4())[:8],
        name=req.name,
        module_id=req.module_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        token_budget=get_settings().session.default_token_budget,
    )
    await session_repo.create(session)
    return CreateSessionResponse(id=session.id, name=session.name)


@router.get("/list")
async def list_sessions():
    """列出所有游戏会话"""
    return await session_repo.list_all()


@router.get("/{session_id}")
async def get_session(session_id: str):
    """获取游戏会话详情"""
    session = await session_repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session.model_dump(mode="json")


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """删除游戏会话"""
    await session_repo.delete(session_id)
    return {"status": "ok"}


@router.post("/{session_id}/load-module")
async def load_module_for_session(session_id: str, req: LoadModuleRequest):
    """为会话加载模组

    可以通过 module_id 加载已保存的模组，或通过 sample_name 加载内置示例模组。
    """
    session = await session_repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    if req.module_id:
        # 从数据库加载已保存的模组
        module = await module_repo.get(req.module_id)
        if not module:
            raise HTTPException(status_code=404, detail="模组不存在")
        session.module_id = req.module_id
    elif req.sample_name:
        # 加载内置示例模组
        try:
            sample_path = get_sample_module_path(req.sample_name)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"示例模组 '{req.sample_name}' 不存在")
        with open(sample_path, "r", encoding="utf-8") as f:
            module_data = json.load(f)
        from ...models.story_module import StoryModule
        module = StoryModule.model_validate(module_data)
        # 保存到数据库并关联会话
        module_id = f"sample_{req.sample_name}"
        await module_repo.save(module, module_id)
        session.module_id = module_id
    else:
        raise HTTPException(status_code=400, detail="请提供 module_id 或 sample_name")

    # 将模组NPC/场景/线索注入运行时会话
    populate_session_from_module(session, module)

    session.updated_at = datetime.now()
    await session_repo.update(session)
    return {
        "status": "ok",
        "module_id": session.module_id,
        "module_title": module.metadata.title,
    }


# ---- 模组端点 ----

@router.post("/modules/generate")
async def generate_module(req: GenerateModuleRequest):
    """调用StoryGeneratorAgent生成新模组

    根据种子提示词、时代、玩家人数和难度生成完整的CoC模组。
    生成后自动保存到数据库。
    """
    agent = StoryGeneratorAgent()
    try:
        module = await agent.generate_module(
            seed_prompt=req.seed_prompt,
            era=req.era,
            player_count=req.player_count,
            difficulty=req.difficulty,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"模组生成失败：{str(e)}")

    # 保存到数据库
    module_id = str(uuid.uuid4())[:8]
    await module_repo.save(module, module_id)

    return {
        "status": "ok",
        "module_id": module_id,
        "module": module.model_dump(mode="json"),
    }


@router.get("/modules/samples")
async def list_sample_modules_endpoint():
    """列出内置示例模组"""
    samples = list_sample_modules()
    result = []
    for name in samples:
        try:
            path = get_sample_module_path(name)
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            meta = data.get("metadata", {})
            result.append({
                "name": name,
                "title": meta.get("title", name),
                "author": meta.get("author", ""),
                "summary": meta.get("summary", ""),
                "era": meta.get("era", ""),
                "difficulty": meta.get("difficulty", ""),
            })
        except Exception:
            result.append({"name": name, "title": name})
    return result


@router.get("/modules/{module_id}")
async def get_module(module_id: str):
    """获取模组详情"""
    module = await module_repo.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail="模组不存在")
    return module.model_dump(mode="json")


@router.post("/{session_id}/opening")
async def trigger_opening_narration(session_id: str):
    """游戏页加载后调用：叙事日志为空时由 LLM 根据模组导入/开场场景生成首轮守密人发言。"""
    session = await session_repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    from .websocket import _handle_game_event, push_session_character_sheets

    game_loop = get_game_loop(session_id)

    async def run_opening() -> None:
        try:
            async for event in game_loop.process_opening_narration():
                await _handle_game_event(session_id, event)
        except Exception:
            logger.exception("开场叙事后台任务失败")
        finally:
            await push_session_character_sheets(session_id)

    asyncio.create_task(run_opening())
    return {"status": "ok"}
