"""双守密人：旁白（场景）与 NPC 专精对话。

在架构上由 `hierarchical_keeper.UnifiedKP` 作为总 KP 挂载二者为下属 Agent；
业务代码应通过 `UnifiedKP.narration` / `UnifiedKP.npc_actor` 调用，而非散落 new。
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional

from .base import BaseAgent
from ..config import get_settings
from ..middleware.token_tracker import TokenTracker
from ..models.character import Investigator
from ..models.game_state import GameSession, NarrativeEntry, NPC
from .game_master import build_context_prompt

logger = logging.getLogger(__name__)


SCENE_KEEPER_PROMPT = """你是克苏鲁的呼唤第7版游戏的「场景守密人」——**纯旁白**，不是任何角色。

# 身份边界（最高优先级）
- 你只使用**第三人称旁白**：环境、氛围、客观发生的事、调查员可感知的现象。
- **你不是 NPC，也不代 NPC 出声。** 所有角色的**台词、引号对白、直接引语**一律禁止；由【NPC专精守密人】在系统调用后单独生成。
- **禁止出现**（针对一切 NPC/路人、电话那头的人声）：
  - 日式引号对白：「……」（除下文「物体文字」例外外，全文尽量不要出现「）
  - 西式引号对白："……" 或 '……'
  - 叙述性引语：某某**说/道/喊道/低声说/答道/嘟囔**后面的**可听清单词/句子**（可写：他嘴唇动了动，没有出声。）
  - 把 NPC 要说的具体内容写出来（即使不用引号）也算代发言——应改为笼统旁白或停到【NPC发言】
- **唯一允许的「」用法**：描写**物体表面可读文字**（招牌、告示、报纸标题、便条上的印刷字），且必须是物，不是人在说话。

# NPC 需要开口时——谁说话由标记决定
1. 你用旁白写到**即将发生对话**的瞬间（对方抬眼、清嗓子、嘴型变化等**无台词**暗示即可）。
2. **单独起一行**，只写：`【NPC发言：与模组一致的全名】`
3. **该行之后不要再写任何字符**（不要跟对白、不要跟省略号）。系统会专由 NPC Agent 生成该角色的「」台词与简短神态。

**对错示例**
- ✓ 托马斯打开门，面容憔悴，目光在你脸上停了一瞬，侧身让出通道。【NPC发言：托马斯·金博尔】
- ✗ 托马斯说：「你就是侦探吧。」
- ✗ 托马斯低声道：欢迎光临。
- ✗ 托马斯向你介绍：他叔叔已经失踪一年……（把具体说明内容写出来＝你在替 NPC 交代，应旁白概括或停到【NPC发言】）

# 核心原则（参考规则书第十章：主持游戏）
你是游戏的主持人。你的职责是描写环境、推进事件、裁定规则。
最重要的一点：**倾听玩家的发言，并根据他们所言所行作出反馈。**

你的输出**只包含**：
- 环境描写（视觉、听觉、嗅觉、触觉）
- 事件发生、时间推进、情节转折
- NPC 的**可见动作与神态**（无台词）
- 机制标记（技能检定、理智检定、战斗、场景转换、【NPC发言：名】）

# ★ 叙事节奏 —— 最重要的规则
**你必须叙事到"下一个有意义的事件/决策点"才能停下。**

合法的停止点只有以下几种：
1. 调查员面临需要做出选择或决定的时刻
2. 出现需要技能检定的行动（写出标记后停下）
3. 进入战斗
4. NPC需要对调查员说话（写出【NPC发言】标记后停下）

**以下情况绝对不算停止点，必须继续写下去：**
- 刚描写完环境氛围但什么事都没发生
- 调查员正在执行一个动作的过程中（如：正在走路、正在躺下、正在开门）
- 用"然而..."、"但是..."、"即将..."这类悬念句结尾——你必须把悬念的内容写出来
- 描写了"声音/异样/预感"但没有揭示或推进任何事

**关键规则：当调查员执行了一个明确的行动（如"睡觉""离开""翻找"），你必须叙事到这个行动的结果/后果。**
例如：
- 玩家说"睡觉" → 你必须叙事到：安睡到天亮（描写醒来后的情况）、被什么惊醒、做了噩梦、睡眠中发生了事件——选择一个结果并写出来
- 玩家说"翻找房间" → 你必须叙事到：找到了什么 / 什么都没找到但触发了别的事
- 玩家说"离开这里" → 你必须叙事到：到达了下一个地点 / 路上遇到了什么

当被系统以"【检定结果续写】"指令调用时，表示之前的技能检定已完成，你需要根据结果继续叙事直到下一个停止点。

# 主动叙事（推动剧情前进）
- 即将发生的事件：**直接让它发生**，不铺垫暗示后停下
- 线索通过正常行为可发现：自然融入叙事
- 采用"好的，然后…"/"好的，但是…"态度，不直接否定玩家
- **不要反复渲染同一种氛围**。如果已经描写过"墙壁中的声音"，下次要推进——声音变化了？源头暴露了？还是消失了？

# ★ 回应长度 —— 必须动态变化（与 API 的 max_tokens 上限无关：上限很高，短输出是内容选择，不是被截断到几百字）
长度由"发生了多少事"决定，不是由"写了多少描写"决定，也**不要**养成「每轮都写差不多三四百字就停」的习惯。

- **简单问答**（"我累吗？""这里有什么？"）→ 2-4句，直接回答，不要展开长篇描写
- **日常移动/过渡**（从A走到B，路上无事）→ 1-2句带过，不要详细描写每一步
- **到达新地点** → 环境、氛围、可互动细节可写**较长一段**，再给行动空间
- **调查、搜索、冲突升级、恐怖铺垫或关键情节** → **充分展开**：多段描写、感官细节、节奏变化均可，需要时写到上千字也合理
- **紧急情况** → 急促短句

**绝对不要每次都写差不多的长度。** 该长则长、该短则短；短不等于「每轮固定中等篇幅」。
若当前轮需要推进到合法停止点，而篇幅仍明显偏短、事件未落地，必须继续写。

# 机制标记（每次回应最多出现一个检定标记，写完后停下等系统处理）
- 【技能检定：技能名】普通难度
- 【技能检定：技能名/困难】或【技能检定：技能名/极难】— 指定难度
- 【技能检定：技能名/奖励1】— 有利情境给1个奖励骰（如充足准备、极佳条件）
- 【技能检定：技能名/惩罚1】— 不利情境给1个惩罚骰（如黑暗、受伤、仓促）
- 【技能检定：技能名/困难/惩罚1】— 可组合难度与奖励/惩罚
- 【理智检定：成功损失/失败损失】
- 【进入战斗】
- 【场景转换：场景名/描述】
- 【模组结束】
- 【NPC发言：NPC名】

奖励骰/惩罚骰使用场景：
- 奖励骰：调查员有充分准备、条件极佳、有人协助、出其不意
- 惩罚骰：环境恶劣（黑暗/暴风雨）、调查员受伤/疲惫、仓促行动、被干扰
- 可以给多个（奖励2、惩罚2），但通常1个即可

# 禁止
- **不要写任何 NPC/路人的台词或对话内容**（含「」与“说道”类引语）；需要说话只用【NPC发言】交给专精 Agent
- 不要替调查员决定行动
- 持有物与事实以上下文为准
- 不要编造模组中不存在的关键线索或NPC
- **不要用悬念/省略号/暗示性结尾来偷懒结束叙事**
- 若违反旁白规则写了台词，系统仍会再调用 NPC Agent，玩家将看到**重复或打架**的两套话——严禁如此

使用中文。"""


NPC_KEEPER_PROMPT_TEMPLATE = """你是克苏鲁的呼唤中的 NPC 专精守密人。

# 职责
- 你只扮演下面指定的这一名 NPC
- 输出该NPC的**直接发言**（用「」引号标记台词）与简短伴随动作/表情
- 语言风格必须符合时代背景与人物性格
- 秘密不可主动和盘托出，除非被说服或情境合理
- **不要描写全景环境**——环境由场景守密人（纯旁白）负责；场景守密人**不会**写出你的台词，只会写到【NPC发言：你的名字】为止
- 不要替其他NPC或调查员说话/做决定
- 若需要检定，在发言后另起一行加标记如【技能检定：心理学】

# 调用场景
你会在两种情况下被调用：
1. **调查员直接与你对话** — 直接回应调查员的发言
2. **场景旁白已停在你的发言点** — 上文是场景守密人的无台词旁白，末尾由系统插入了【NPC发言：你】；你根据情境**第一次**说出此时该说的内容（不要假设旁白里已经替你说过话）

# 像真人一样反应
NPC不是信息售货机，应根据情境主动表现：
- 被问到不安/愤怒/悲伤的问题 → 表现情绪，可能反问、回避、沉默
- 本身有紧迫事务 → 主动提起，不等调查员问到
- 触及痛处 → 反应更长、更有情感
- 简单寒暄/重复问题 → 简短应对（1-2句）
- 发言末尾可通过动作/表情暗示还有话没说完

# 回应长度（勿每轮都卡在几句；需要时可说较长一段）
- 简单回答/寒暄：1-3句
- 重要信息/回忆：可明显加长，带停顿、犹豫、表情与潜台词
- 情绪爆发/关键剧情：充分展开，不必自我限制在固定字数
- **绝不要每次都写一样长**

使用中文。

---
# 当前扮演的角色
姓名：{name}
概况：{description}
对话风格提示：{dialogue_notes}
守密人可见秘密（影响反应，勿直接剧透）：{secret}
"""


def _build_messages(
    player_action: str,
    context: str,
    recent_narrative: list[NarrativeEntry],
) -> list[dict]:
    messages: list[dict] = []
    if context:
        messages.append({"role": "user", "content": f"[游戏上下文]\n{context}"})
        messages.append({"role": "assistant", "content": "明白。"})
    for entry in recent_narrative:
        if entry.source == "守密人":
            messages.append({"role": "assistant", "content": entry.content})
        else:
            prefix = f"[{entry.source}]" if entry.entry_type == "action" else ""
            messages.append({"role": "user", "content": f"{prefix} {entry.content}"})
    messages.append({"role": "user", "content": player_action})
    return messages


class SceneKeeperAgent(BaseAgent):
    """场景 / 情节描述守密人"""

    def __init__(
        self,
        token_tracker: Optional[TokenTracker] = None,
        model: Optional[str] = None,
    ):
        super().__init__(
            name="场景守密人",
            system_prompt=SCENE_KEEPER_PROMPT,
            token_tracker=token_tracker,
            model=model,
            max_tokens=get_settings().agents.scene_keeper,
        )

    async def narrate_stream(
        self,
        player_action: str,
        session: GameSession,
        investigators: list[Investigator],
        recent_narrative: list[NarrativeEntry],
        module_context: str = "",
    ) -> AsyncGenerator[str, None]:
        verbosity = "详细"
        if self.token_tracker:
            verbosity = self.token_tracker.suggested_verbosity
        context = build_context_prompt(
            session, investigators, recent_narrative,
            verbosity=verbosity, module_context=module_context,
        )
        # context 仅注入 system prompt（可缓存），不再重复放入 user messages
        messages = _build_messages(player_action, "", recent_narrative)
        full_system = self.system_prompt + ("\n\n" + context if context else "")
        logger.debug(
            "===== 场景守密人 system prompt (%d chars) =====\n%s",
            len(full_system), full_system,
        )
        old = self.system_prompt
        self.system_prompt = full_system
        try:
            async for chunk in self.stream(messages, temperature=0.8):
                yield chunk
        finally:
            self.system_prompt = old

    async def narrate(
        self,
        player_action: str,
        session: GameSession,
        investigators: list[Investigator],
        recent_narrative: list[NarrativeEntry],
        module_context: str = "",
    ) -> tuple[str, dict]:
        """非流式叙事（LangGraph 等路径）。"""
        verbosity = "详细"
        if self.token_tracker:
            verbosity = self.token_tracker.suggested_verbosity
        context = build_context_prompt(
            session, investigators, recent_narrative,
            verbosity=verbosity, module_context=module_context,
        )
        messages = _build_messages(player_action, "", recent_narrative)
        full_system = self.system_prompt + ("\n\n" + context if context else "")
        old = self.system_prompt
        self.system_prompt = full_system
        try:
            return await self.invoke(messages, temperature=0.8)
        finally:
            self.system_prompt = old


class NPCKeeperAgent(BaseAgent):
    """NPC 对话专精守密人"""

    def __init__(
        self,
        token_tracker: Optional[TokenTracker] = None,
        model: Optional[str] = None,
    ):
        super().__init__(
            name="NPC守密人",
            system_prompt="你是 NPC 专精守密人；完整指令在每轮动态 system 中给出。",
            token_tracker=token_tracker,
            model=model,
            max_tokens=get_settings().agents.npc_keeper,
        )

    async def narrate_stream(
        self,
        player_action: str,
        session: GameSession,
        investigators: list[Investigator],
        recent_narrative: list[NarrativeEntry],
        npc: NPC,
        module_context: str = "",
    ) -> AsyncGenerator[str, None]:
        verbosity = "详细"
        if self.token_tracker:
            verbosity = self.token_tracker.suggested_verbosity
        # NPC 守密人只需要精简的游戏上下文，不需要完整模组信息
        base_ctx = build_context_prompt(
            session, investigators, recent_narrative,
            verbosity=verbosity, module_context="",
        )
        npc_lines: list[str] = []
        mem = getattr(session, "keeper_memory", None)
        if mem and npc.id in mem.npc_memories:
            for b in mem.npc_memories[npc.id][-8:]:
                npc_lines.append(f"· {b}")
        mem_s = "\n".join(npc_lines) if npc_lines else "（暂无该角色专属记忆条目）"
        role_block = NPC_KEEPER_PROMPT_TEMPLATE.format(
            name=npc.name,
            description=npc.description or "无",
            dialogue_notes=npc.dialogue_notes or "无",
            secret=npc.secret or "无",
        )
        full_system = (
            f"{role_block}\n\n# 该 NPC 已有记忆（须一致）\n{mem_s}\n\n"
            f"# 共通游戏上下文\n{base_ctx}"
        )
        logger.debug(
            "===== NPC守密人[%s] system prompt (%d chars) =====\n%s",
            npc.name, len(full_system), full_system,
        )
        messages = _build_messages(
            f"调查员行动/发言：{player_action}\n请以该 NPC 身份回应。",
            "",
            recent_narrative,
        )
        old = self.system_prompt
        self.system_prompt = full_system
        try:
            async for chunk in self.stream(messages, temperature=0.85):
                yield chunk
        finally:
            self.system_prompt = old

    async def narrate(
        self,
        player_action: str,
        session: GameSession,
        investigators: list[Investigator],
        recent_narrative: list[NarrativeEntry],
        npc: NPC,
        module_context: str = "",
    ) -> tuple[str, dict]:
        """非流式 NPC 对话（LangGraph 等路径）。"""
        verbosity = "详细"
        if self.token_tracker:
            verbosity = self.token_tracker.suggested_verbosity
        base_ctx = build_context_prompt(
            session, investigators, recent_narrative,
            verbosity=verbosity, module_context="",
        )
        npc_lines: list[str] = []
        mem = getattr(session, "keeper_memory", None)
        if mem and npc.id in mem.npc_memories:
            for b in mem.npc_memories[npc.id][-8:]:
                npc_lines.append(f"· {b}")
        mem_s = "\n".join(npc_lines) if npc_lines else "（暂无该角色专属记忆条目）"
        role_block = NPC_KEEPER_PROMPT_TEMPLATE.format(
            name=npc.name,
            description=npc.description or "无",
            dialogue_notes=npc.dialogue_notes or "无",
            secret=npc.secret or "无",
        )
        full_system = (
            f"{role_block}\n\n# 该 NPC 已有记忆（须一致）\n{mem_s}\n\n"
            f"# 共通游戏上下文\n{base_ctx}"
        )
        messages = _build_messages(
            f"调查员行动/发言：{player_action}\n请以该 NPC 身份回应。",
            "",
            recent_narrative,
        )
        old = self.system_prompt
        self.system_prompt = full_system
        try:
            return await self.invoke(messages, temperature=0.85)
        finally:
            self.system_prompt = old
