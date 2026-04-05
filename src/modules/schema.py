"""标准模组格式验证器

对StoryModule进行完整性和一致性校验。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models.story_module import StoryModule


class ModuleValidationError(Exception):
    """模组验证失败异常"""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"模组验证失败（{len(errors)}个问题）：\n" + "\n".join(f"  - {e}" for e in errors))


@dataclass
class ValidationResult:
    """验证结果"""
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


def validate_module(module: StoryModule, strict: bool = False) -> ValidationResult:
    """验证StoryModule的完整性和一致性

    检查项目：
    1. 基础完整性：标题非空、至少有场景
    2. ID唯一性：所有NPC/地点/场景/线索的ID不重复
    3. 引用一致性：场景引用的NPC/地点/线索ID必须存在
    4. 核心线索可达性：核心线索至少关联一个地点
    5. 场景连通性：开场场景存在，场景转换目标存在

    Args:
        module: 待验证的模组
        strict: 严格模式下warnings也视为errors

    Returns:
        ValidationResult
    """
    result = ValidationResult()

    # ---- 1. 基础完整性 ----
    if not module.metadata.title.strip():
        result.add_error("模组标题为空")

    if not module.scenes:
        result.add_error("模组没有任何场景")

    if not module.npcs:
        result.add_warning("模组没有任何NPC")

    if not module.locations:
        result.add_warning("模组没有任何地点")

    if not module.clues:
        result.add_warning("模组没有任何线索")

    # ---- 2. ID唯一性 ----
    def _check_unique_ids(items: list, category: str) -> set[str]:
        ids: set[str] = set()
        for item in items:
            if item.id in ids:
                result.add_error(f"{category}中存在重复ID：{item.id}")
            ids.add(item.id)
        return ids

    npc_ids = _check_unique_ids(module.npcs, "NPC")
    location_ids = _check_unique_ids(module.locations, "地点")
    scene_ids = _check_unique_ids(module.scenes, "场景")
    clue_ids = _check_unique_ids(module.clues, "线索")
    timeline_ids = _check_unique_ids(module.timeline, "时间线")

    # 所有合法ID集合（用于交叉引用检查）
    all_ids = npc_ids | location_ids | scene_ids | clue_ids | timeline_ids

    # ---- 3. 引用一致性 ----
    for scene in module.scenes:
        # 场景引用的NPC
        for npc_id in scene.npc_ids:
            if npc_id not in npc_ids:
                result.add_error(f"场景「{scene.title}」引用了不存在的NPC：{npc_id}")
        # 场景引用的地点
        if scene.location_id and scene.location_id not in location_ids:
            result.add_error(f"场景「{scene.title}」引用了不存在的地点：{scene.location_id}")
        # 场景引用的线索
        for cid in scene.clue_ids:
            if cid not in clue_ids:
                result.add_error(f"场景「{scene.title}」引用了不存在的线索：{cid}")
        # 场景转换目标
        for trans in scene.transitions:
            if trans.target_scene_id not in scene_ids:
                result.add_error(
                    f"场景「{scene.title}」的转换目标不存在：{trans.target_scene_id}"
                )
            for req_clue in trans.required_clues:
                if req_clue not in clue_ids:
                    result.add_error(
                        f"场景「{scene.title}」的转换条件引用了不存在的线索：{req_clue}"
                    )

    for location in module.locations:
        for npc_id in location.npc_ids:
            if npc_id not in npc_ids:
                result.add_error(f"地点「{location.name}」引用了不存在的NPC：{npc_id}")
        for cid in location.clue_ids:
            if cid not in clue_ids:
                result.add_error(f"地点「{location.name}」引用了不存在的线索：{cid}")
        for direction, target_loc in location.connections.items():
            if target_loc not in location_ids:
                result.add_error(
                    f"地点「{location.name}」的连接目标不存在：{direction} -> {target_loc}"
                )

    for clue in module.clues:
        if clue.location_id and clue.location_id not in location_ids:
            result.add_error(f"线索「{clue.name}」引用了不存在的地点：{clue.location_id}")
        for lead in clue.leads_to:
            if lead not in all_ids:
                result.add_warning(f"线索「{clue.name}」的leads_to引用了未知ID：{lead}")

    # ---- 4. 核心线索可达性 ----
    core_clues = module.get_core_clues()
    for clue in core_clues:
        if not clue.location_id and not clue.discovery_method:
            result.add_warning(f"核心线索「{clue.name}」没有关联地点和发现方式，可能无法被发现")

    # ---- 5. 场景连通性 ----
    opening_scenes = [s for s in module.scenes if s.is_opening]
    if module.scenes and not opening_scenes:
        result.add_warning("没有标记开场场景（is_opening=True），将使用第一个场景")

    if len(opening_scenes) > 1:
        result.add_warning(f"有{len(opening_scenes)}个开场场景，通常只需要一个")

    # 严格模式下warnings也视为errors
    if strict and result.warnings:
        for w in result.warnings:
            result.add_error(f"[严格模式] {w}")

    return result
