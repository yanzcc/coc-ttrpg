"""守密人路由：判断玩家是否在直接对 NPC 对话。

判断逻辑（按优先级）：
1. 显式对话：玩家文本包含对话关键词 + NPC名字
2. 问句对话：玩家输入是问句，且有在场NPC最近说过话
3. 上下文延续：上一轮NPC说过话，且玩家输入不含明确行动词
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple, List

from ..models.game_state import GameSession, NPC

if TYPE_CHECKING:
    from ..models.game_state import NarrativeEntry


# 玩家文本中明确的对话意图
_DIALOGUE_HINTS = (
    "问", "询问", "对", "和", "与", "告诉", "跟", "找", "答", "回答", "说道",
    "开口", "搭话", "质问", "追问", "说",
)

# 问句特征词（中文问句几乎都包含这些）
_QUESTION_HINTS = (
    "吗", "吗？", "？", "什么", "怎么", "为什么", "哪", "哪里", "哪些",
    "几", "多少", "谁", "是否", "有没有", "能不能", "可不可以",
    "知道", "了解", "记得", "听说",
)

# 玩家文本中明确的行动意图（出现这些词则优先走场景守密人）
_ACTION_HINTS = (
    "检查", "调查", "搜索", "观察", "查看", "前往", "走向", "离开", "打开",
    "攻击", "战斗", "逃跑", "闪避", "使用", "拿起", "翻找", "进入", "出去",
    "爬", "跳", "跑", "躲", "藏", "偷", "撬", "推", "拉", "踢",
    "射击", "开枪", "施放", "阅读", "研究", "破解", "修理",
    "开车", "驾驶", "游泳", "攀爬",
)


def detect_npc_dialogue_target(
    action_text: str,
    session: GameSession,
    recent_narrative: Optional[List["NarrativeEntry"]] = None,
) -> Optional[Tuple[str, NPC]]:
    """若玩家明显在与某在场 NPC 对话，返回 (npc_id, NPC)。"""
    if not action_text.strip() or not session.npcs:
        return None
    t = action_text.strip()

    # --- 路径1：显式对话（文本中直接提到NPC + 对话意图） ---
    if any(h in t for h in _DIALOGUE_HINTS):
        match = _find_npc_in_text(t, session)
        if match:
            return match

    # 如果玩家输入包含明确的行动词，走场景守密人
    if any(h in t for h in _ACTION_HINTS):
        return None

    # --- 路径2：问句检测 —— 玩家在提问，且最近有NPC在场说话 ---
    is_question = any(h in t for h in _QUESTION_HINTS)
    if is_question and recent_narrative:
        last_npc = _find_last_speaking_npc(recent_narrative, session)
        if last_npc:
            return last_npc

    # --- 路径3：上下文对话延续 —— 短输入 + 最近NPC说话 ---
    if recent_narrative:
        last_npc = _find_last_speaking_npc(recent_narrative, session)
        if last_npc:
            return last_npc

    return None


def _find_npc_in_text(
    text: str, session: GameSession,
) -> Optional[Tuple[str, NPC]]:
    """在文本中查找匹配的在场NPC名字。"""
    best: tuple[str, NPC] | None = None
    best_len = 0
    for nid, npc in session.npcs.items():
        if not npc.name or not npc.is_alive:
            continue
        if npc.name not in text:
            continue
        if session.current_scene and session.current_scene.npcs_present:
            if nid not in session.current_scene.npcs_present:
                continue
        if len(npc.name) > best_len:
            best = (nid, npc)
            best_len = len(npc.name)
    return best


def _find_last_speaking_npc(
    recent: List["NarrativeEntry"],
    session: GameSession,
) -> Optional[Tuple[str, NPC]]:
    """从近期叙事中找到最后发言的NPC。

    从后往前扫描，跳过玩家行动和系统消息。
    即使中间夹了"守密人"条目也继续扫描（因为保存顺序可能交错）。
    """
    checked = 0
    for entry in reversed(recent):
        if checked >= 8:
            break
        # 跳过玩家行动
        if entry.entry_type == "action":
            continue
        # 跳过系统/骰子消息
        if entry.entry_type in ("system", "dice_roll"):
            checked += 1
            continue

        # 检查source是否是某个NPC的名字
        for nid, npc in session.npcs.items():
            if not npc.name or not npc.is_alive:
                continue
            if entry.source == npc.name:
                if session.current_scene and session.current_scene.npcs_present:
                    if nid not in session.current_scene.npcs_present:
                        continue
                return (nid, npc)

        # 也检查叙事内容中是否包含NPC的「」对话（场景守密人违规写的NPC台词）
        if entry.source == "守密人" and "「" in entry.content:
            for nid, npc in session.npcs.items():
                if not npc.name or not npc.is_alive:
                    continue
                if npc.name in entry.content:
                    return (nid, npc)

        checked += 1

    return None
