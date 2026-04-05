"""页面路由

服务端渲染的HTML页面。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from ..app import templates

router = APIRouter()


@router.get("/")
async def index(request: Request):
    """首页——游戏大厅"""
    return templates.TemplateResponse(request, name="index.html")


@router.get("/game/{session_id}")
async def game_page(request: Request, session_id: str):
    """游戏界面"""
    return templates.TemplateResponse(request, name="game.html", context={
        "session_id": session_id,
    })


@router.get("/character/create/{session_id}")
async def character_create_page(request: Request, session_id: str):
    """角色创建页面"""
    return templates.TemplateResponse(request, name="character_create.html", context={
        "session_id": session_id,
        "edit_id": "",
    })


@router.get("/character/edit/{investigator_id}")
async def character_edit_page(request: Request, investigator_id: str):
    """角色编辑页面（加载已有角色）"""
    return templates.TemplateResponse(request, name="character_create.html", context={
        "session_id": "",
        "edit_id": investigator_id,
    })


@router.get("/usage")
async def usage_page(request: Request):
    """Token用量监控页面"""
    return templates.TemplateResponse(request, name="usage.html")


@router.get("/module-browser")
async def module_browser_page(request: Request):
    """模组浏览页面"""
    return templates.TemplateResponse(request, name="module_browser.html")


@router.get("/module-generate")
async def module_generate_page(request: Request):
    """模组生成页面"""
    return templates.TemplateResponse(request, name="module_generate.html")
