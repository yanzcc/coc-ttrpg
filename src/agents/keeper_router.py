"""守密人路由：判断玩家是否在直接对 NPC 对话。

判断逻辑（按优先级）：
1. 显式对话：玩家文本包含对话关键词 + NPC 名字
2. 明确环境行动：含行动类动词 → 场景守密人（不跟 NPC 专线）
3. 问句对话：输入像问句，且近期叙事中最近发言的是在场 NPC
4. 短句接话：仅当输入较短、且不像转去调查/移动时，才延续与最近 NPC 的对话

说明：旧版「路径 3」在检测到最近 NPC 发言后无条件走 NPC Agent，会导致对话结束后
调查、移动等仍一直被路由到 NPC；因此必须限制长度并排除明显的场景行动语义。
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

# 问句特征（避免过宽：如单独「知道」会误判「我知道该怎么做」）
_QUESTION_HINTS = (
    "吗", "？", "什么", "怎么", "为什么", "哪里", "哪些", "哪位", "哪儿",
    "多少", "谁", "是否", "有没有", "能不能", "可不可以", "会不会", "是不是", "要不要",
)
# 「几」作疑问时多为「几个」「几位」等，避免单字「几」误触「几乎」
_QUESTION_NUMBER = ("几个", "几位", "几天", "几人", "几层", "几条", "几次", "几米", "几岁")

# 接话场景下，出现这些更像「转去行动/探索」而非继续盘问 NPC → 交场景守密人
_SCENE_PIVOT_PHRASES = (
    "我去", "我先", "我到", "走向", "前往", "离开", "走开", "转身",
    "四处", "周围", "附近", "楼上", "楼下", "外面", "屋里", "门口", "门外", "窗前",
    "看看", "瞧瞧", "搜查", "搜索", "寻找", "翻找", "检查", "调查",
    "打开", "蹲下", "站起", "靠近", "退后", "捡起", "拿起",
)

# 与 NPC 口头接话允许的最大字数（中文约 2～3 短句）；超出则默认走场景叙事
# B1：收紧到 40 字，避免「我走向 X 家的门」这类 8~20 字的移动描述被误判为接话
_CONTINUATION_MAX_CHARS = 40

# 玩家文本中明确的行动意图（出现这些词则优先走场景守密人）
_ACTION_HINTS = (
    "检查", "调查", "搜索", "观察", "查看", "前往", "走向", "离开", "打开",
    "攻击", "战斗", "逃跑", "闪避", "使用", "拿起", "翻找", "进入", "出去",
    "爬", "跳", "跑", "躲", "藏", "偷", "撬", "推", "拉", "踢",
    "射击", "开枪", "施放", "阅读", "研究", "破解", "修理",
    "开车", "驾驶", "游泳", "攀爬",
)


def _looks_like_question(t: str) -> bool:
    """识别「在向对方发问」；长段里的「有没有」多为环境描写，不归为问句。"""
    if "？" in t or "吗" in t:
        return True
    # 不含句末疑问标记时，仅对较短输入把「有没有/能不能…」当作口语问句（避免长探索描述误判）
    weak_interrogative = (
        "有没有", "能不能", "可不可以", "会不会", "是不是", "要不要",
    )
    if any(w in t for w in weak_interrogative):
        if len(t) <= _CONTINUATION_MAX_CHARS:
            return True
        return False
    if any(h in t for h in _QUESTION_HINTS):
        return True
    if any(h in t for h in _QUESTION_NUMBER):
        return True
    return False


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
    if _looks_like_question(t) and recent_narrative:
        last_npc = _find_last_speaking_npc(recent_narrative, session)
        if last_npc:
            return last_npc

    # --- 路径3：仅「短句接话」延续 NPC 线；长段叙述或明显转场景一律走叙事 Agent ---
    if recent_narrative:
        last_npc = _find_last_speaking_npc(recent_narrative, session)
        if last_npc:
            if len(t) > _CONTINUATION_MAX_CHARS:
                return None
            if any(h in t for h in _ACTION_HINTS):
                return None
            if any(p in t for p in _SCENE_PIVOT_PHRASES):
                return None
            # B1：若玩家文本明确提到**另一个** NPC 名字（不是 last_npc），
            # 说明已经转场，不要继续让旧 NPC 回应
            last_id, last_obj = last_npc
            for nid, npc in session.npcs.items():
                if nid == last_id or not npc.name or not npc.is_alive:
                    continue
                if npc.name in t:
                    return None
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

        checked += 1

    return None
