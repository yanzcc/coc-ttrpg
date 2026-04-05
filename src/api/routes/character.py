"""角色管理API路由"""

from __future__ import annotations

import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...models.character import (
    Investigator, Characteristics, DerivedStats, SkillValue, Gender,
    InventoryItem, parse_era,
)
from ...rules.skill_list import (
    get_skills_for_era, OCCUPATIONS, SKILL_CATEGORIES,
    get_module_adjusted_skills,
)
from ...rules.weapon_presets import get_preset_weapons_grouped
from ...rules.dice import roll_dice
from ...storage.repositories import InvestigatorRepository
from ...agents.character_mgr import CharacterManagerAgent, _parse_skill_points_formula

router = APIRouter()
investigator_repo = InvestigatorRepository()
character_agent = CharacterManagerAgent()


class QuickCreateRequest(BaseModel):
    """快速创建角色请求"""
    session_id: str
    player_id: str
    name: str
    age: int = 30
    gender: str = "男"
    occupation: str = "私家侦探"
    era: str = "1920s"


class SkillData(BaseModel):
    """单个技能数据"""
    base: int = 0
    current: int = 0
    experienced: bool = False


class FullCreateRequest(BaseModel):
    """完整创建角色请求（含手动分配技能点）"""
    id: Optional[str] = None  # 编辑已有角色时传入ID
    session_id: str = ""
    player_id: str
    name: str
    age: int = 30
    gender: str = "男"
    occupation: str = "私家侦探"
    era: str = "1920s"
    birthplace: str = ""
    residence: str = ""
    characteristics: Optional[Characteristics] = None
    derived: Optional[dict] = None
    skills: Optional[dict[str, SkillData | int]] = None
    weapons: Optional[list[dict]] = None
    inventory: Optional[list[dict]] = None
    cash: Optional[str] = None
    assets: Optional[str] = None
    background: Optional[dict] = None


def _inventory_from_full_create_request(req: FullCreateRequest) -> list[InventoryItem]:
    """从创建/保存请求解析武器与杂物（半自动分支也必须调用，否则会丢物品）。"""
    inventory: list[InventoryItem] = []
    if req.weapons:
        for w in req.weapons:
            if w.get("name", "").strip():
                inventory.append(InventoryItem(
                    name=w["name"],
                    is_weapon=True,
                    damage=w.get("damage", "") or None,
                    skill_name=w.get("skill", "") or None,
                    range=w.get("range", "") or None,
                    uses=int(w["ammo"]) if str(w.get("ammo", "")).isdigit() else None,
                ))
    if req.inventory:
        for item in req.inventory:
            if isinstance(item, dict) and item.get("name", "").strip():
                inventory.append(InventoryItem(
                    name=item.get("name", ""),
                    quantity=int(item.get("quantity", 1) or 1),
                    description=(item.get("description") or "") or "",
                ))
    return inventory


class SkillUpdateRequest(BaseModel):
    """技能点更新请求"""
    session_id: str
    skills: dict[str, int]  # 技能名 -> 新的current值


@router.post("/quick-create")
async def quick_create(req: QuickCreateRequest):
    """快速创建调查员（随机属性，自动分配技能点）"""
    try:
        era = parse_era(req.era)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    inv = character_agent.create_investigator(
        player_id=req.player_id,
        name=req.name,
        age=req.age,
        gender=Gender(req.gender),
        occupation=req.occupation,
        era=era,
    )

    if not inv.inventory:
        inv.inventory = [
            InventoryItem(name="衣物与个人用品", quantity=1),
            InventoryItem(name="笔记本与书写工具", quantity=1),
            InventoryItem(name="手电筒", quantity=1),
        ]

    await investigator_repo.save(inv, req.session_id)
    return inv.model_dump(mode="json")


@router.post("/full-create")
async def full_create(req: FullCreateRequest):
    """完整创建调查员（支持手动指定属性和技能点分配）

    如果不提供characteristics，则随机生成。
    如果不提供skills，则自动分配技能点。
    前端提交的skills格式：{技能名: {base, current, experienced}} 或 {技能名: 分配点数}
    """
    try:
        era = parse_era(req.era)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    gender = Gender(req.gender)

    if req.characteristics and req.skills:
        # 完全手动模式：使用提供的属性和技能分配
        chars = req.characteristics

        # 处理幸运值
        if req.derived and "luck" in req.derived:
            luck = req.derived["luck"]
        else:
            from ...rules.character_creation import roll_luck
            import random
            luck = roll_luck(rng=random.Random())

        # 衍生属性：优先使用前端提供的，否则自动计算
        if req.derived:
            derived = DerivedStats(
                hp=req.derived.get("hp", (chars.CON + chars.SIZ) // 10),
                hp_max=req.derived.get("hp_max", (chars.CON + chars.SIZ) // 10),
                mp=req.derived.get("mp", chars.POW // 5),
                mp_max=req.derived.get("mp_max", chars.POW // 5),
                san=req.derived.get("san", chars.POW),
                san_max=req.derived.get("san_max", 99),
                luck=luck,
                mov=req.derived.get("mov", chars.movement_rate),
            )
        else:
            derived = DerivedStats.from_characteristics(chars, luck)

        # 解析技能数据
        skills: dict[str, SkillValue] = {}
        for skill_name, skill_data in req.skills.items():
            if isinstance(skill_data, dict) or hasattr(skill_data, "base"):
                # {base, current, experienced} 格式
                sd = skill_data if isinstance(skill_data, dict) else skill_data.model_dump()
                skills[skill_name] = SkillValue(
                    base=sd.get("base", 0),
                    current=sd.get("current", sd.get("base", 0)),
                    experience_check=sd.get("experienced", False),
                )
            else:
                # 兼容旧格式：纯数字代表分配的点数
                era_skills = get_skills_for_era(era.value)
                base_val = era_skills.get(skill_name, 1)
                if skill_name == "闪避":
                    base_val = chars.DEX // 2
                elif skill_name == "母语":
                    base_val = chars.EDU
                skills[skill_name] = SkillValue(
                    base=base_val,
                    current=base_val + int(skill_data),
                )

        inventory = _inventory_from_full_create_request(req)

        # 背景信息
        bg = req.background or {}

        inv = Investigator(
            id=req.id or str(uuid.uuid4()),
            player_id=req.player_id,
            name=req.name,
            age=req.age,
            gender=gender,
            occupation=req.occupation,
            era=era,
            birthplace=req.birthplace,
            residence=req.residence,
            characteristics=chars,
            derived=derived,
            skills=skills,
            inventory=inventory,
            cash=float(req.cash) if req.cash and req.cash.replace(".", "").isdigit() else 0,
            assets=req.assets or "",
            personal_description=bg.get("personal_description", ""),
            ideology=bg.get("ideology", ""),
            significant_people=bg.get("significant_people", ""),
            meaningful_locations=bg.get("meaningful_locations", ""),
            treasured_possessions=bg.get("treasured_possessions", ""),
            traits=bg.get("traits", ""),
        )
    else:
        # 半自动模式：使用Agent创建，再覆盖手动部分
        inv = character_agent.create_investigator(
            player_id=req.player_id,
            name=req.name,
            age=req.age,
            gender=gender,
            occupation=req.occupation,
            era=era,
        )

        # 如果提供了手动技能分配，覆盖自动分配的结果
        if req.skills:
            for skill_name, skill_data in req.skills.items():
                if skill_name in inv.skills:
                    sv = inv.skills[skill_name]
                    if isinstance(skill_data, dict) or hasattr(skill_data, "base"):
                        sd = skill_data if isinstance(skill_data, dict) else skill_data.model_dump()
                        inv.skills[skill_name] = SkillValue(
                            base=sv.base,
                            current=sd.get("current", sv.current),
                            experience_check=sd.get("experienced", sv.experience_check),
                        )
                    else:
                        inv.skills[skill_name] = SkillValue(
                            base=sv.base,
                            current=sv.base + int(skill_data),
                            experience_check=sv.experience_check,
                        )

        # 半自动分支同样写入表单中的武器/物品（此前会整段丢失）
        inv.inventory = _inventory_from_full_create_request(req)

    await investigator_repo.save(inv, req.session_id)
    return inv.model_dump(mode="json")


@router.put("/{investigator_id}/skills")
async def update_skills(investigator_id: str, req: SkillUpdateRequest):
    """更新调查员的技能点分配

    接受技能名到新current值的映射，更新指定技能。
    """
    inv = await investigator_repo.get(investigator_id)
    if not inv:
        raise HTTPException(status_code=404, detail="调查员不存在")

    for skill_name, new_value in req.skills.items():
        if skill_name not in inv.skills:
            raise HTTPException(
                status_code=400,
                detail=f"未知技能：{skill_name}",
            )
        sv = inv.skills[skill_name]
        if new_value < sv.base:
            raise HTTPException(
                status_code=400,
                detail=f"技能 {skill_name} 的值({new_value})不能低于基础值({sv.base})",
            )
        if new_value > 99:
            raise HTTPException(
                status_code=400,
                detail=f"技能 {skill_name} 的值({new_value})不能超过99",
            )
        inv.skills[skill_name] = SkillValue(
            base=sv.base,
            current=new_value,
            experience_check=sv.experience_check,
        )

    await investigator_repo.save(inv, req.session_id)
    return inv.model_dump(mode="json")


@router.get("/skills/{era}")
async def get_era_skills(era: str):
    """获取指定时代的分类技能列表

    返回格式：{categories: [{name, skills: [{name, base}]}], all_skills: {name: base}}
    """
    era_skills = get_skills_for_era(era)

    # 按分类组织技能
    categories = []
    categorized = set()
    for cat_name, skill_names in SKILL_CATEGORIES.items():
        cat_skills = []
        for skill_name in skill_names:
            if skill_name in era_skills:
                cat_skills.append({
                    "name": skill_name,
                    "base": era_skills[skill_name],
                })
                categorized.add(skill_name)
        if cat_skills:
            categories.append({"name": cat_name, "skills": cat_skills})

    # 未分类的技能放入「其他」
    uncategorized = []
    for skill_name, base_val in era_skills.items():
        if skill_name not in categorized:
            uncategorized.append({"name": skill_name, "base": base_val})
    if uncategorized:
        other_cat = next((c for c in categories if c["name"] == "其他"), None)
        if other_cat:
            other_cat["skills"].extend(uncategorized)
        else:
            categories.append({"name": "其他", "skills": uncategorized})

    return {
        "era": era,
        "categories": categories,
        "all_skills": era_skills,
    }


@router.get("/occupations/list")
async def list_occupations():
    """列出所有可选职业

    返回格式：[{name, skills, skill_points, credit_rating}]
    """
    result = []
    for name, info in OCCUPATIONS.items():
        result.append({
            "name": name,
            "skills": info.get("skills", []),
            "skill_points": info.get("skill_points", "EDU×4"),
            "skill_points_alt": info.get("skill_points_alt"),
            "credit_rating": info.get("credit_rating", (0, 99)),
            "tags": info.get("tags", []),
        })
    # 按拼音/名称排序
    result.sort(key=lambda o: o["name"])
    return result


@router.get("/weapons/presets")
async def list_weapon_presets():
    """返回按分类分组的预设武器列表（来源：调查员手册）"""
    return get_preset_weapons_grouped()


@router.get("/list/all")
async def list_all_investigators():
    """列出所有保存的调查员摘要"""
    return await investigator_repo.list_all()


@router.get("/list/player/{player_id}")
async def list_player_investigators(player_id: str):
    """列出某玩家的所有调查员"""
    investigators = await investigator_repo.list_by_player(player_id)
    return [inv.model_dump(mode="json") for inv in investigators]


@router.get("/session/{session_id}")
async def list_investigators(session_id: str):
    """列出会话中的所有调查员"""
    investigators = await investigator_repo.list_by_session(session_id)
    return [inv.model_dump(mode="json") for inv in investigators]


@router.post("/{investigator_id}/assign/{session_id}")
async def assign_to_session(investigator_id: str, session_id: str):
    """将已有调查员分配到游戏会话"""
    inv = await investigator_repo.get(investigator_id)
    if not inv:
        raise HTTPException(status_code=404, detail="调查员不存在")
    await investigator_repo.save(inv, session_id)
    return {"status": "ok", "investigator_id": investigator_id, "session_id": session_id}


@router.post("/{investigator_id}/grow")
async def apply_growth(investigator_id: str):
    """应用经验成长（模组结束后）

    对所有标记了经验的技能进行成长检定：
    投 1d100，若 > 当前技能值，则该技能 +1d10
    """
    import random
    inv = await investigator_repo.get(investigator_id)
    if not inv:
        raise HTTPException(status_code=404, detail="调查员不存在")

    rng = random.Random()
    growth_log = []
    for skill_name, sv in inv.skills.items():
        if sv.experience_check:
            roll = rng.randint(1, 100)
            if roll > sv.current:
                gain = rng.randint(1, 10)
                new_val = min(99, sv.current + gain)
                growth_log.append({
                    "skill": skill_name,
                    "roll": roll,
                    "old": sv.current,
                    "gain": gain,
                    "new": new_val,
                })
                inv.skills[skill_name] = SkillValue(
                    base=sv.base, current=new_val, experience_check=False,
                )
            else:
                growth_log.append({
                    "skill": skill_name,
                    "roll": roll,
                    "old": sv.current,
                    "gain": 0,
                    "new": sv.current,
                    "failed": True,
                })
                inv.skills[skill_name] = SkillValue(
                    base=sv.base, current=sv.current, experience_check=False,
                )

    # 保存（用空session_id保留原session关联）
    # 需要从数据库获取原始session_id
    from ...storage.database import get_session as get_db_session, InvestigatorTable
    from sqlalchemy import select
    async with await get_db_session() as db:
        result = await db.execute(
            select(InvestigatorTable.session_id).where(InvestigatorTable.id == investigator_id)
        )
        row = result.one_or_none()
        sid = row.session_id if row else ""
    await investigator_repo.save(inv, sid)
    return {"growth_log": growth_log, "investigator": inv.model_dump(mode="json")}


@router.delete("/{investigator_id}")
async def delete_investigator(investigator_id: str):
    """删除调查员"""
    await investigator_repo.delete(investigator_id)
    return {"status": "ok"}


@router.get("/{investigator_id}/lock-status")
async def get_lock_status(investigator_id: str):
    """检查调查员是否在活跃游戏中（锁定手动编辑）

    如果调查员所在的会话阶段不是"大厅"或"结束"，则视为锁定。
    """
    from ...storage.database import get_session as get_db_session, InvestigatorTable, SessionTable
    from sqlalchemy import select
    async with await get_db_session() as db:
        result = await db.execute(
            select(InvestigatorTable.session_id).where(InvestigatorTable.id == investigator_id)
        )
        row = result.one_or_none()
        if not row or not row.session_id:
            return {"locked": False, "reason": ""}

        sess_result = await db.execute(
            select(SessionTable.phase).where(SessionTable.id == row.session_id)
        )
        sess_row = sess_result.one_or_none()
        if not sess_row:
            return {"locked": False, "reason": ""}

        locked = sess_row.phase not in ("大厅", "结束", "")
        return {
            "locked": locked,
            "session_id": row.session_id,
            "phase": sess_row.phase,
            "reason": "调查员正在游戏中" if locked else "",
        }


@router.get("/{investigator_id}/suggest-background")
async def suggest_background(investigator_id: str):
    """获取AI生成的角色背景建议"""
    inv = await investigator_repo.get(investigator_id)
    if not inv:
        raise HTTPException(status_code=404, detail="调查员不存在")

    fields = await character_agent.suggest_background(inv)
    return {"investigator_id": investigator_id, **fields}


@router.get("/{investigator_id}")
async def get_investigator(investigator_id: str):
    """获取调查员详情"""
    inv = await investigator_repo.get(investigator_id)
    if not inv:
        raise HTTPException(status_code=404, detail="调查员不存在")
    return inv.model_dump(mode="json")
