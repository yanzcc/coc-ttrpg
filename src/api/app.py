"""FastAPI应用工厂

创建和配置Web应用。
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import get_settings
from ..storage.database import init_db, close_db

# 加载环境变量
load_dotenv(override=True)

# 路径
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    await init_db()
    yield
    await close_db()


def create_app() -> FastAPI:
    """创建FastAPI应用"""
    meta = get_settings().api
    app = FastAPI(
        title=meta.title,
        description=meta.description,
        version=meta.version,
        lifespan=lifespan,
    )

    # 静态文件
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # 注册路由
    from .routes import game, character, websocket, usage
    app.include_router(game.router, prefix="/api/game", tags=["游戏会话"])
    app.include_router(character.router, prefix="/api/character", tags=["角色管理"])
    app.include_router(websocket.router, tags=["WebSocket"])
    app.include_router(usage.router, prefix="/api/usage", tags=["Token用量"])
    # 注：模组相关端点已集成在 game.router 中：
    #   POST /api/game/{session_id}/load-module
    #   POST /api/game/modules/generate
    #   GET  /api/game/modules/samples
    #   GET  /api/game/modules/{module_id}

    # 页面路由
    from .routes import pages
    app.include_router(pages.router, tags=["页面"])

    return app


# Jinja2模板引擎（供路由使用）
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
