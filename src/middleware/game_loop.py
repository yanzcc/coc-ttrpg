"""游戏循环中间件

处理玩家行动的完整流程。支持两种模式：
1. 流式模式（默认）：守密人叙事直接流式输出，机制检定在叙事后触发
2. 图模式：通过LangGraph状态机处理（用于复杂的多Agent交互）
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import AsyncGenerator

from ..agents.combat import CombatAgent
from ..agents.dual_keepers import NPCKeeperAgent, SceneKeeperAgent
from ..agents.keeper_router import detect_npc_dialogue_target
from ..agents.memory_curator import merge_narration_into_session_memory
from ..agents.skill_check import SkillCheckAgent
from ..graph.game_graph import get_game_graph
from ..graph.state import GraphState, ActionType
from ..middleware.token_tracker import TokenTracker
from ..models.character import Investigator
from ..models.game_state import (
    GameSession, GamePhase, NarrativeEntry, PendingSkillCheck,
)
from ..rules.combat_rules import (
    resolve_attack, resolve_dodge, check_major_wound,
    MELEE_WEAPONS, RANGED_WEAPONS, FumbleEffect,
)
from ..rules.skill_check import check_skill, Difficulty, SuccessLevel
from ..rules.sanity import check_sanity
from ..storage.repositories import (
    SessionRepository, InvestigatorRepository, NarrativeRepository, ModuleRepository,
)
from .opening_prompt import (
    OPENING_PLAYER_PROMPT,
    format_module_opening_context,
    format_free_mode_opening_context,
    format_ongoing_module_context,
)

logger = logging.getLogger(__name__)

_opening_locks: dict[str, asyncio.Lock] = {}


def _opening_lock_for(session_id: str) -> asyncio.Lock:
    if session_id not in _opening_locks:
        _opening_locks[session_id] = asyncio.Lock()
    return _opening_locks[session_id]


# 机制标记正则
# 支持：【技能检定：侦查】【技能检定：侦查/困难】【技能检定：侦查/困难/奖励1】【技能检定：侦查/惩罚2】
SKILL_CHECK_PATTERN = re.compile(r'【技能检定：([^/】]+)(?:/([^/】]+))?(?:/([^/】]+))?(?:/([^】]+))?】')
SANITY_CHECK_PATTERN = re.compile(r'【理智检定：([^/】]+)/([^】]+)】')
COMBAT_PATTERN = re.compile(r'【进入战斗】')
SCENE_CHANGE_PATTERN = re.compile(r'【场景转换：([^/】]+)(?:/([^】]+))?】')
MODULE_END_PATTERN = re.compile(r'【模组结束】')
NPC_SPEECH_PATTERN = re.compile(r'【NPC发言：([^】]+)】')

# 需要立即停止流式输出的标记（LLM 在标记后应停下，但不一定服从，代码强制截断）
_STOP_MARKER = re.compile(
    r'【(?:技能检定|理智检定|NPC发言)：[^】]+】'
)


def _success_level_cn(level: SuccessLevel) -> str:
    return {
        SuccessLevel.FUMBLE: "大失败",
        SuccessLevel.FAILURE: "失败",
        SuccessLevel.REGULAR: "普通成功",
        SuccessLevel.HARD: "困难成功",
        SuccessLevel.EXTREME: "极难成功",
        SuccessLevel.CRITICAL: "大成功",
    }.get(level, str(level))


class GameLoop:
    """游戏循环处理器

    每个游戏会话一个实例。使用流式模式处理玩家行动。
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.token_tracker = TokenTracker(session_id)
        self.scene_keeper = SceneKeeperAgent(token_tracker=self.token_tracker)
        self.npc_keeper = NPCKeeperAgent(token_tracker=self.token_tracker)
        self.skill_narrator = SkillCheckAgent(token_tracker=self.token_tracker)
        self.combat_narrator = CombatAgent(token_tracker=self.token_tracker)
        self.session_repo = SessionRepository()
        self.investigator_repo = InvestigatorRepository()
        self.narrative_repo = NarrativeRepository()
        self.module_repo = ModuleRepository()

    async def _get_session(self) -> GameSession:
        session = await self.session_repo.get(self.session_id)
        if not session:
            raise ValueError(f"会话 {self.session_id} 不存在")
        return session

    async def _get_investigators(self) -> list[Investigator]:
        return await self.investigator_repo.list_by_session(self.session_id)

    async def _get_recent_narrative(self, limit: int = 15) -> list[NarrativeEntry]:
        return await self.narrative_repo.get_recent(self.session_id, limit=limit)

    async def _get_module_context(self, session: GameSession) -> str:
        """获取当前游戏进行中的模组上下文（非开场）。"""
        if not session.module_id:
            return ""
        mod = await self.module_repo.get(session.module_id)
        if not mod:
            return ""
        return format_ongoing_module_context(mod, session)

    async def process_action_stream(
        self,
        player_id: str,
        action_text: str,
    ) -> AsyncGenerator[dict, None]:
        """处理玩家行动（流式）

        主游戏循环入口。返回事件流：
        - {"type": "narrative_chunk", "chunk": "..."} — 叙事片段
        - {"type": "narrative_end", "full_text": "..."} — 叙事完成
        - {"type": "skill_check", ...} — 技能检定结果
        - {"type": "sanity_check", ...} — 理智检定结果
        - {"type": "system", "content": "..."} — 系统消息
        - {"type": "token_warning", "content": "..."} — Token预算警告
        """
        session = await self._get_session()
        investigators = await self._get_investigators()
        recent = await self._get_recent_narrative()

        # 记录玩家行动
        action_entry = NarrativeEntry(
            source=player_id,
            content=action_text,
            entry_type="action",
        )
        await self.narrative_repo.append(self.session_id, action_entry)

        # 更新会话阶段
        if session.phase == GamePhase.LOBBY:
            session.phase = GamePhase.EXPLORATION
            await self.session_repo.update(session)

        # ===== 战斗阶段：走战斗专用流程 =====
        if session.phase == GamePhase.COMBAT and session.combat:
            async for event in self._process_combat_turn(
                player_id, action_text, session, investigators, recent,
            ):
                yield event
            warning = self.token_tracker.check_budget_warnings()
            if warning:
                yield {"type": "token_warning", "content": warning}
            return

        npc_dialogue_target = detect_npc_dialogue_target(action_text, session, recent)

        # ���取模组上下文（���续注入守密人）
        module_context = await self._get_module_context(session)
        if module_context:
            logger.info(
                "===== 模组上下文 (%d chars) =====\n%s\n===== /模组上下文 =====",
                len(module_context), module_context,
            )

        # =====================================================================
        # 多段叙事循环
        #
        # 整体流程（单次玩家行动可能触发多轮守密人输出）：
        #   1. 场景守密人叙事（或NPC守密人，若玩家直接对话NPC）
        #   2. 解析输出中的标记：
        #      - 【NPC发言：X】→ 调用NPC守密人 → 流式输出
        #      - 【技���检定：X】→ 掷骰 → yield结果 → 场景守密人基于结果续写
        #      - 【理智检定】→ 同上
        #      - 【进入战斗】/【场景转换】/��模组结束】→ 处理后结束循环
        #   3. 若有技能/理智检定 → 续写（回到步骤1）
        #   4. 否则 → 到达玩家决策点，结束循环
        # =====================================================================
        full_text = ""              # 本轮所有输出的累积
        unsaved_text = ""           # 尚未保存到数据库的叙事文本
        current_action = action_text
        is_continuation = False     # 是否是检定后的续写
        MAX_ROUNDS = 5              # 防止无限循环

        for round_idx in range(MAX_ROUNDS):
            segment_text = ""
            had_check = False

            if npc_dialogue_target and not is_continuation:
                # 玩家明确与NPC对话——直接NPC守密人
                _nid, _npc = npc_dialogue_target
                logger.info("路由到 NPC 守密人：%s", _npc.name)
                try:
                    async for chunk in self.npc_keeper.narrate_stream(
                        player_action=current_action,
                        session=session,
                        investigators=investigators,
                        recent_narrative=recent,
                        npc=_npc,
                        module_context=module_context,
                    ):
                        segment_text += chunk
                        yield {
                            "type": "narrative_chunk",
                            "chunk": chunk,
                            "npc_name": _npc.name,
                        }
                except Exception as e:
                    yield {"type": "system", "content": f"NPC守密人出错：{str(e)}"}
                    break
            else:
                # 场景守密人叙事 —— 检测到标记时立即截断
                try:
                    yielded_len = 0  # 已发送给前端的字符数
                    async for chunk in self.scene_keeper.narrate_stream(
                        player_action=current_action,
                        session=session,
                        investigators=investigators,
                        recent_narrative=recent,
                        module_context=module_context,
                    ):
                        segment_text += chunk
                        # 检测停止标记（技能检定/理智检定/NPC发言）
                        stop_m = _STOP_MARKER.search(segment_text)
                        if stop_m:
                            # 只发送标记结尾为止的文本，丢弃标记之后的内容
                            cut = stop_m.end()
                            unsent = segment_text[yielded_len:cut]
                            if unsent:
                                yield {"type": "narrative_chunk", "chunk": unsent}
                            segment_text = segment_text[:cut]
                            logger.info(
                                "流式截断：检测到标记 %s，丢弃标记后 %d 字符",
                                stop_m.group(), len(chunk) - (cut - yielded_len),
                            )
                            break
                        else:
                            yield {"type": "narrative_chunk", "chunk": chunk}
                            yielded_len = len(segment_text)
                except Exception as e:
                    yield {"type": "system", "content": f"守密人Agent出错：{str(e)}"}
                    break

            full_text += segment_text
            unsaved_text += segment_text

            # --- 处理 NPC 发言标记 ---
            npc_markers = list(NPC_SPEECH_PATTERN.finditer(segment_text))

            # 如果有NPC标记，先保存场景守密人文本（NPC条目排在后面便于路由）
            if npc_markers and unsaved_text.strip():
                _clean_scene = NPC_SPEECH_PATTERN.sub('', unsaved_text)
                _clean_scene = SKILL_CHECK_PATTERN.sub('', _clean_scene)
                _clean_scene = SANITY_CHECK_PATTERN.sub('', _clean_scene).strip()
                if _clean_scene:
                    await self.narrative_repo.append(
                        self.session_id,
                        NarrativeEntry(
                            source="守密人",
                            content=_clean_scene,
                            entry_type="narration",
                        ),
                    )
                unsaved_text = ""

            for npc_match in npc_markers:
                npc_name = npc_match.group(1).strip()
                target_npc = None
                for nid, npc in session.npcs.items():
                    if npc.name == npc_name:
                        target_npc = npc
                        break
                if not target_npc:
                    logger.warning("NPC发言标记找不到NPC：%s", npc_name)
                    continue

                # 检测场景守密人是否已写了该NPC的「」对白
                marker_pos = npc_match.start()
                text_before = segment_text[:marker_pos]
                scene_has_dialogue = (
                    "「" in text_before and npc_name in text_before
                )
                if scene_has_dialogue:
                    logger.info(
                        "场景守密人已写 %s 的对白，跳过NPC守密人避免重复",
                        npc_name,
                    )
                    # 仍保存一条NPC记录便于路由
                    import re as _re
                    _quotes = _re.findall(r'「([^」]+)」', text_before)
                    _npc_line = _quotes[-1] if _quotes else ""
                    if _npc_line:
                        await self.narrative_repo.append(
                            self.session_id,
                            NarrativeEntry(
                                source=npc_name,
                                content=f"「{_npc_line}」",
                                entry_type="narration",
                            ),
                        )
                    continue

                logger.info("场景守密人触发 NPC 发言：%s", npc_name)
                npc_action = f"���场景叙述中{npc_name}需要开口说话。前文叙述：{segment_text[-600:]}）"
                npc_text = ""
                try:
                    async for chunk in self.npc_keeper.narrate_stream(
                        player_action=npc_action,
                        session=session,
                        investigators=investigators,
                        recent_narrative=recent,
                        npc=target_npc,
                        module_context=module_context,
                    ):
                        npc_text += chunk
                        yield {
                            "type": "narrative_chunk",
                            "chunk": chunk,
                            "npc_name": npc_name,
                        }
                except Exception:
                    logger.exception("NPC发言生成失败：%s", npc_name)
                if npc_text.strip():
                    # 保存NPC发言，source设为NPC名字便于对话延续路由
                    await self.narrative_repo.append(
                        self.session_id,
                        NarrativeEntry(
                            source=npc_name,
                            content=npc_text.strip(),
                            entry_type="narration",
                        ),
                    )
                full_text += "\n" + npc_text

            # --- 处理技能检定（掷骰，不再用 SkillCheckAgent 叙事） ---
            check_results_summary: list[str] = []
            session = await self._get_session()

            for match in SKILL_CHECK_PATTERN.finditer(segment_text):
                had_check = True
                async for event in self._process_skill_check(
                    match, investigators, session, segment_text, current_action,
                ):
                    yield event
                    if event["type"] == "skill_check":
                        lvl = _success_level_cn(
                            SuccessLevel[event["success_level"]]
                        )
                        extra = ""
                        if event.get("is_critical"):
                            extra = "（大成功！结果远超预期）"
                        elif event.get("is_fumble"):
                            extra = "（大失败！事情朝最糟糕的方向发展）"
                        check_results_summary.append(
                            f"{event['skill']}检定：掷出{event['roll']}，"
                            f"目标{event['target']}，结果{lvl}{extra}"
                        )

            for match in SANITY_CHECK_PATTERN.finditer(segment_text):
                had_check = True
                async for event in self._process_sanity_check(
                    match, investigators, session,
                ):
                    yield event
                    if event["type"] == "sanity_check":
                        check_results_summary.append(
                            f"理智检定：损失{event['san_lost']}点SAN"
                        )

            # --- 处理场景转换、战斗、模组结束 ---
            async for event in self._process_scene_combat_end(
                segment_text, investigators, session,
            ):
                yield event

            # --- 如果有检定，场景守密人续写 ---
            if had_check and round_idx < MAX_ROUNDS - 1:
                summary = "；".join(check_results_summary)
                # 提供之前的叙事片段作为上下文，防止重复叙事
                prev_context = segment_text[-800:] if segment_text else ""
                current_action = (
                    f"【检定结果续写】{summary}。\n"
                    f"你之前已经写到（请勿重复以下内容，直接从检定结果开始继续）：\n"
                    f"「{prev_context}」\n"
                    f"请紧接上文，根据检定结果继续叙事。"
                )
                is_continuation = True
                # 将当前叙事段和检定结果记入recent以便续写时有上下文
                if unsaved_text.strip():
                    clean_seg = SKILL_CHECK_PATTERN.sub('', unsaved_text)
                    clean_seg = SANITY_CHECK_PATTERN.sub('', clean_seg)
                    clean_seg = NPC_SPEECH_PATTERN.sub('', clean_seg).strip()
                    if clean_seg:
                        await self.narrative_repo.append(
                            self.session_id,
                            NarrativeEntry(
                                source="守密人",
                                content=clean_seg,
                                entry_type="narration",
                            ),
                        )
                    unsaved_text = ""
                recent = await self._get_recent_narrative()
                logger.info("检定后续写（第%d轮）：%s", round_idx + 1, summary)
                continue
            else:
                # 到���玩家决策点或无检定，结束循��
                break

        yield {"type": "narrative_end", "full_text": full_text}

        # --- 记录叙事 & 更新记忆 ---
        # unsaved_text 只包含最后一段尚未保存的叙事（前面的段在续写时已保存）
        clean_unsaved = SKILL_CHECK_PATTERN.sub('', unsaved_text)
        clean_unsaved = SANITY_CHECK_PATTERN.sub('', clean_unsaved)
        clean_unsaved = COMBAT_PATTERN.sub('', clean_unsaved)
        clean_unsaved = SCENE_CHANGE_PATTERN.sub('', clean_unsaved)
        clean_unsaved = MODULE_END_PATTERN.sub('', clean_unsaved)
        clean_unsaved = NPC_SPEECH_PATTERN.sub('', clean_unsaved).strip()

        if clean_unsaved:
            # 如果本轮是NPC直接回应，source记为NPC名字（便于后续路由识别对话延续）
            narration_source = "守密人"
            if npc_dialogue_target:
                _nid, _npc = npc_dialogue_target
                narration_source = _npc.name
            gm_entry = NarrativeEntry(
                source=narration_source,
                content=clean_unsaved,
                entry_type="narration",
            )
            await self.narrative_repo.append(self.session_id, gm_entry)

        # 用 full_text 做记忆更新（包含完整对话上下文）
        clean_full = SKILL_CHECK_PATTERN.sub('', full_text)
        clean_full = SANITY_CHECK_PATTERN.sub('', clean_full)
        clean_full = NPC_SPEECH_PATTERN.sub('', clean_full).strip()

        session = await self._get_session()
        try:
            await merge_narration_into_session_memory(
                clean_full, session, self.token_tracker,
            )
            if npc_dialogue_target:
                nid, npc = npc_dialogue_target
                session.keeper_memory.npc_memories.setdefault(nid, [])
                excerpt = clean_full.replace("\n", " ").strip()[:380]
                line = f"玩家：{action_text[:140]}… → 回应摘要：{excerpt}"
                if line not in session.keeper_memory.npc_memories[nid]:
                    session.keeper_memory.npc_memories[nid].append(line)
                session.keeper_memory.npc_memories[nid] = (
                    session.keeper_memory.npc_memories[nid][-14:]
                )
            session.updated_at = datetime.now()
            await self.session_repo.update(session)
        except Exception:
            logger.exception("会话记忆更新失败")

        # 检查Token预算警告
        warning = self.token_tracker.check_budget_warnings()
        if warning:
            yield {"type": "token_warning", "content": warning}

    async def process_opening_narration(self) -> AsyncGenerator[dict, None]:
        """首轮守密人发言：依据模组导入与开场场景（无玩家行动记录）。"""
        async with _opening_lock_for(self.session_id):
            if await self.narrative_repo.count(self.session_id) > 0:
                return

            session = await self._get_session()
            investigators = await self._get_investigators()
            recent: list[NarrativeEntry] = []

            module_context = ""
            if session.module_id:
                mod = await self.module_repo.get(session.module_id)
                if mod:
                    module_context = format_module_opening_context(mod, investigators)
            if not module_context.strip():
                module_context = format_free_mode_opening_context(session.name)
            logger.info(
                "===== 开场模组上下文 (%d chars) =====\n%s\n===== /开场模组上下文 =====",
                len(module_context), module_context,
            )

            if session.phase == GamePhase.LOBBY:
                session.phase = GamePhase.EXPLORATION
                await self.session_repo.update(session)

            full_text = ""
            try:
                async for chunk in self.scene_keeper.narrate_stream(
                    player_action=OPENING_PLAYER_PROMPT,
                    session=session,
                    investigators=investigators,
                    recent_narrative=recent,
                    module_context=module_context,
                ):
                    full_text += chunk
                    yield {"type": "narrative_chunk", "chunk": chunk}
            except Exception as e:
                logger.exception("开场叙述失败")
                yield {"type": "system", "content": f"开场叙述生成失败：{str(e)}"}
                return

            # --- 处理开场中的 NPC 发言标记 ---
            for npc_match in NPC_SPEECH_PATTERN.finditer(full_text):
                npc_name = npc_match.group(1).strip()
                target_npc = None
                for nid, npc in session.npcs.items():
                    if npc.name == npc_name:
                        target_npc = npc
                        break
                if not target_npc:
                    logger.warning("开场NPC发言标记找不到NPC：%s", npc_name)
                    continue
                logger.info("开场触发 NPC 发言：%s", npc_name)
                npc_action = f"（场景叙述中{npc_name}需要开口说话。前文叙述：{full_text[-600:]}）"
                npc_text = ""
                try:
                    async for chunk in self.npc_keeper.narrate_stream(
                        player_action=npc_action,
                        session=session,
                        investigators=investigators,
                        recent_narrative=recent,
                        npc=target_npc,
                        module_context=module_context,
                    ):
                        npc_text += chunk
                        yield {
                            "type": "narrative_chunk",
                            "chunk": chunk,
                            "npc_name": npc_name,
                        }
                except Exception:
                    logger.exception("开场NPC发言生成失败：%s", npc_name)
                full_text += "\n" + npc_text

            yield {"type": "narrative_end", "full_text": full_text}

            clean_text = SKILL_CHECK_PATTERN.sub('', full_text)
            clean_text = SANITY_CHECK_PATTERN.sub('', clean_text)
            clean_text = COMBAT_PATTERN.sub('', clean_text)
            clean_text = SCENE_CHANGE_PATTERN.sub('', clean_text)
            clean_text = MODULE_END_PATTERN.sub('', clean_text)
            clean_text = NPC_SPEECH_PATTERN.sub('', clean_text).strip()

            gm_entry = NarrativeEntry(
                source="守密人",
                content=clean_text,
                entry_type="narration",
            )
            await self.narrative_repo.append(self.session_id, gm_entry)

            session = await self._get_session()
            try:
                await merge_narration_into_session_memory(
                    clean_text, session, self.token_tracker,
                )
                session.updated_at = datetime.now()
                await self.session_repo.update(session)
            except Exception:
                logger.exception("开场记忆更新失败")

            session = await self._get_session()
            async for event in self._process_mechanics(
                full_text, investigators, session, player_action="",
            ):
                yield event

            warning = self.token_tracker.check_budget_warnings()
            if warning:
                yield {"type": "token_warning", "content": warning}

    # ------------------------------------------------------------------
    # 战斗处理
    # ------------------------------------------------------------------

    async def _process_combat_turn(
        self,
        player_id: str,
        action_text: str,
        session: GameSession,
        investigators: list[Investigator],
        recent: list[NarrativeEntry],
    ) -> AsyncGenerator[dict, None]:
        """处理战斗阶段的玩家行动：解析意图 → 掷骰 → 敌人回合 → 叙事。"""
        combat = session.combat
        if not combat:
            return

        default_inv = investigators[0] if investigators else None
        if not default_inv:
            return

        # 获取存活的敌方NPC
        enemy_npcs = [
            (p, session.npcs.get(p.id))
            for p in combat.participants
            if not p.is_player and p.id in session.npcs
            and session.npcs[p.id].is_alive
        ]

        action_lower = action_text.lower()
        round_actions: list[dict] = []   # 用于最终叙事
        full_text = ""

        # ====== 1. 解析玩家意图并执行 ======
        fled = False
        if any(kw in action_lower for kw in ("逃跑", "撤退", "逃走", "跑", "flee", "run")):
            # 逃跑：DEX 对抗检定
            fled = await self._resolve_flee(
                default_inv, enemy_npcs, round_actions,
            )
            # 不管逃跑成功还是失败，都yield系统事件
            for event in round_actions:
                if event.get("type") == "system":
                    yield event
        elif any(kw in action_lower for kw in (
            "闪避", "防御", "dodge",
        )):
            # 准备闪避——标记本轮用闪避，不主动攻击
            yield {"type": "system", "content": f"🛡️ {default_inv.name} 准备闪避下一次攻击。"}
            round_actions.append({
                "actor": default_inv.name,
                "action_type": "闪避准备",
                "target": "",
                "result": "等待敌方攻击",
                "damage": 0,
            })
        else:
            # 攻击——找目标和武器
            target_npc = self._find_combat_target(action_text, enemy_npcs)
            weapon_name, weapon_info = self._find_weapon(action_text, default_inv)

            if target_npc is None and enemy_npcs:
                target_npc = enemy_npcs[0]

            if target_npc:
                target_participant, target_npc_obj = target_npc
                skill_name = weapon_info.get("skill", "格斗（斗殴）")
                skill_val_obj = default_inv.skills.get(skill_name)
                attack_skill = skill_val_obj.current if skill_val_obj else 25

                # 伤害加值
                db = getattr(default_inv.derived, "damage_bonus", "0")
                damage_bonus = str(db) if db else "0"

                is_melee = "射击" not in skill_name
                success_level, damage, detail, fumble_fx = resolve_attack(
                    attack_skill_value=attack_skill,
                    damage_expression=weapon_info.get("damage", "1d3"),
                    damage_bonus=damage_bonus,
                    is_melee=is_melee,
                )

                is_hit = success_level >= SuccessLevel.REGULAR

                # 应用伤害到NPC
                if is_hit and damage > 0 and target_npc_obj:
                    npc_hp = target_npc_obj.stats.get("HP", 10)
                    npc_hp = max(0, npc_hp - damage)
                    target_npc_obj.stats["HP"] = npc_hp
                    if npc_hp <= 0:
                        target_npc_obj.is_alive = False
                    await self.session_repo.update(session)

                lvl_cn = _success_level_cn(success_level)
                target_name = target_npc_obj.name if target_npc_obj else "敌人"
                result_text = (
                    f"🎲 {default_inv.name} 用{weapon_name}攻击"
                    f"{target_name}（技能{attack_skill}，{detail}）"
                )

                # --- 大成功特殊提示 ---
                if success_level == SuccessLevel.CRITICAL:
                    result_text += f"\n🌟 大成功！造成 {damage} 点伤害（含额外伤害骰）"
                    if target_npc_obj and target_npc_obj.stats.get("HP", 0) <= 0:
                        result_text += f"，{target_name}被一击击倒！"
                # --- 大失败特殊效果 ---
                elif success_level == SuccessLevel.FUMBLE and fumble_fx:
                    result_text += f"\n💀 大失败！{fumble_fx.description}"
                    if fumble_fx.self_damage > 0:
                        old_hp = default_inv.derived.hp
                        default_inv.derived.hp = max(0, old_hp - fumble_fx.self_damage)
                        result_text += f"（自伤{fumble_fx.self_damage}点，HP: {old_hp}→{default_inv.derived.hp}）"
                        await self.investigator_repo.save(default_inv, self.session_id)
                    if fumble_fx.drop_weapon:
                        result_text += "（武器脱手！）"
                    if fumble_fx.lose_next_turn:
                        result_text += "（下轮无法行动）"
                    if fumble_fx.weapon_malfunction:
                        result_text += "（武器故障！）"
                elif is_hit:
                    result_text += f"，造成 {damage} 点伤害"
                    if target_npc_obj and target_npc_obj.stats.get("HP", 0) <= 0:
                        result_text += f"，{target_name}倒下了！"

                yield {"type": "system", "content": result_text}

                await self.narrative_repo.append(self.session_id, NarrativeEntry(
                    source="系统", content=result_text, entry_type="dice_roll",
                    metadata={"combat": True, "critical": success_level == SuccessLevel.CRITICAL,
                              "fumble": success_level == SuccessLevel.FUMBLE},
                ))

                round_actions.append({
                    "actor": default_inv.name,
                    "action_type": f"攻击（{weapon_name}）",
                    "target": target_name,
                    "result": lvl_cn,
                    "damage": damage if is_hit else 0,
                })

                # 经验标记
                if is_hit and skill_val_obj:
                    skill_val_obj.experience_check = True
                    await self.investigator_repo.save(default_inv, self.session_id)

        # ====== 2. 检查战斗是否结束 ======
        alive_enemies = [
            (p, session.npcs.get(p.id))
            for p in combat.participants
            if not p.is_player and p.id in session.npcs
            and session.npcs[p.id].is_alive
        ]

        if fled or not alive_enemies:
            # 战斗结束
            reason = "调查员撤退" if fled else "所有敌人被击倒"
            casualties = []
            for p in combat.participants:
                if not p.is_player and p.id in session.npcs:
                    npc = session.npcs[p.id]
                    if not npc.is_alive:
                        casualties.append({
                            "name": npc.name, "status": "死亡", "cause": "战斗中被击倒",
                        })
            if not default_inv.is_alive:
                casualties.append({
                    "name": default_inv.name, "status": "死亡", "cause": "战斗中阵亡",
                })

            # 叙事战斗结束
            narration_ctx = "\n".join(e.content for e in recent[-5:])
            try:
                end_text = await self.combat_narrator.narrate_combat_end(
                    reason=reason, casualties=casualties, context=narration_ctx,
                )
                yield {"type": "narrative_chunk", "chunk": end_text}
                full_text += end_text
            except Exception:
                logger.exception("战斗结束叙事失败")

            # 恢复探索阶段
            session.combat = None
            session.phase = GamePhase.EXPLORATION
            await self.session_repo.update(session)
            yield {
                "type": "combat_end",
                "content": f"⚔️ 战斗结束：{reason}",
            }
            yield {"type": "narrative_end", "full_text": full_text}

            if full_text.strip():
                await self.narrative_repo.append(self.session_id, NarrativeEntry(
                    source="守密人", content=full_text.strip(),
                    entry_type="narration",
                ))
            return

        # ====== 3. 敌方NPC回合 ======
        is_dodging = any(
            a.get("action_type") == "闪避准备" for a in round_actions
        )

        for enemy_p, enemy_npc in alive_enemies:
            if not enemy_npc:
                continue
            # NPC攻击调查员
            npc_attack_skill = enemy_npc.stats.get("格斗", enemy_npc.stats.get("攻击", 40))
            npc_damage_expr = enemy_npc.stats.get("伤害", None)
            if npc_damage_expr is None:
                npc_damage_expr = "1d3"
            else:
                npc_damage_expr = str(npc_damage_expr)
                # 如果是纯数字，说明是固定伤害值，转为骰子表达式
                if npc_damage_expr.isdigit():
                    npc_damage_expr = f"1d{int(npc_damage_expr) * 2}" if int(npc_damage_expr) > 0 else "1d3"

            npc_db = str(enemy_npc.stats.get("伤害加值", "0"))

            npc_success, npc_dmg, npc_detail, npc_fumble = resolve_attack(
                attack_skill_value=npc_attack_skill,
                damage_expression=npc_damage_expr,
                damage_bonus=npc_db,
                is_melee=True,
            )

            npc_hit = npc_success >= SuccessLevel.REGULAR

            # --- NPC大失败：自己出问题 ---
            if npc_success == SuccessLevel.FUMBLE and npc_fumble:
                result_text = (
                    f"💀 {enemy_npc.name}攻击{default_inv.name}"
                    f"（{npc_detail}）— 大失败！{npc_fumble.description}"
                )
                if npc_fumble.self_damage > 0:
                    npc_hp = enemy_npc.stats.get("HP", 10)
                    npc_hp = max(0, npc_hp - npc_fumble.self_damage)
                    enemy_npc.stats["HP"] = npc_hp
                    result_text += f"（自伤{npc_fumble.self_damage}点）"
                    if npc_hp <= 0:
                        enemy_npc.is_alive = False
                        result_text += f"，{enemy_npc.name}倒下了！"
                    await self.session_repo.update(session)
            # --- NPC大成功：额外伤害 ---
            elif npc_success == SuccessLevel.CRITICAL:
                result_text = (
                    f"🌟 {enemy_npc.name}攻击{default_inv.name}"
                    f"（{npc_detail}）— 大成功！"
                )
                npc_hit = True
            # --- 玩家闪避 ---
            elif npc_hit and is_dodging:
                dodge_val_obj = default_inv.skills.get("闪避")
                dodge_val = dodge_val_obj.current if dodge_val_obj else default_inv.characteristics.DEX // 2
                dodged, dodge_roll, dodge_level = resolve_dodge(
                    dodge_skill=dodge_val,
                    attack_success=npc_success,
                )
                if dodged:
                    npc_hit = False
                    npc_dmg = 0
                    result_text = (
                        f"🛡️ {enemy_npc.name}攻击{default_inv.name}"
                        f"（{npc_detail}），{default_inv.name}闪避"
                        f"（掷出{dodge_roll}）— 闪避成功！"
                    )
                else:
                    result_text = (
                        f"⚔️ {enemy_npc.name}攻击{default_inv.name}"
                        f"（{npc_detail}），{default_inv.name}闪避"
                        f"（掷出{dodge_roll}）— 闪避失败！"
                    )
            else:
                if npc_hit:
                    result_text = (
                        f"⚔️ {enemy_npc.name}攻击{default_inv.name}"
                        f"（{npc_detail}），命中！"
                    )
                else:
                    result_text = (
                        f"⚔️ {enemy_npc.name}攻击{default_inv.name}"
                        f"（{npc_detail}），未命中。"
                    )

            # 应用伤害到调查员
            if npc_hit and npc_dmg > 0:
                old_hp = default_inv.derived.hp
                default_inv.derived.hp = max(0, old_hp - npc_dmg)
                is_major = check_major_wound(npc_dmg, default_inv.derived.hp_max)
                result_text += f" 造成 {npc_dmg} 点伤害（HP: {old_hp}→{default_inv.derived.hp}）"
                if is_major:
                    result_text += " ⚠️ 重伤！"
                if default_inv.derived.hp <= 0:
                    result_text += f" 💀 {default_inv.name}倒下了！"
                await self.investigator_repo.save(default_inv, self.session_id)

            yield {"type": "system", "content": result_text}
            await self.narrative_repo.append(self.session_id, NarrativeEntry(
                source="系统", content=result_text, entry_type="dice_roll",
                metadata={"combat": True},
            ))

            round_actions.append({
                "actor": enemy_npc.name,
                "action_type": "攻击",
                "target": default_inv.name,
                "result": _success_level_cn(npc_success),
                "damage": npc_dmg if npc_hit else 0,
            })

        # ====== 4. 回合叙事摘要 ======
        narration_ctx = "\n".join(e.content for e in recent[-3:])
        try:
            round_text = await self.combat_narrator.narrate_round_summary(
                round_number=combat.round_number,
                actions=round_actions,
                context=narration_ctx,
            )
            yield {"type": "narrative_chunk", "chunk": "\n" + round_text}
            full_text += round_text
        except Exception:
            logger.exception("战斗轮摘要叙事失败")

        yield {"type": "narrative_end", "full_text": full_text}

        # 记录叙事
        if full_text.strip():
            await self.narrative_repo.append(self.session_id, NarrativeEntry(
                source="守密人", content=full_text.strip(),
                entry_type="narration",
            ))

        # ====== 5. 再次检查战斗是否结束（敌人全灭或调查员倒下） ======
        if not default_inv.is_alive or default_inv.derived.hp <= 0:
            session.combat = None
            session.phase = GamePhase.EXPLORATION
            await self.session_repo.update(session)
            yield {
                "type": "combat_end",
                "content": f"⚔️ 战斗结束：{default_inv.name}倒下了",
            }

    def _find_combat_target(
        self,
        action_text: str,
        enemy_npcs: list[tuple],
    ) -> tuple | None:
        """从行动文本中匹配攻击目标NPC。"""
        for participant, npc_obj in enemy_npcs:
            if npc_obj and npc_obj.name in action_text:
                return (participant, npc_obj)
        return None

    def _find_weapon(
        self,
        action_text: str,
        investigator: Investigator,
    ) -> tuple[str, dict]:
        """从行动文本中识别武器，返回 (武器名, 武器信息字典)。"""
        # 检查文本中提到的武器
        for name, info in {**MELEE_WEAPONS, **RANGED_WEAPONS}.items():
            if name in action_text:
                return name, info
        # 检查调查员物品栏
        if hasattr(investigator, "possessions"):
            for item in investigator.possessions:
                item_lower = item.lower() if isinstance(item, str) else str(item).lower()
                for name, info in {**MELEE_WEAPONS, **RANGED_WEAPONS}.items():
                    if name in item_lower:
                        return name, info
        # 默认拳头
        return "拳头", MELEE_WEAPONS["拳头"]

    async def _resolve_flee(
        self,
        investigator: Investigator,
        enemy_npcs: list[tuple],
        round_actions: list[dict],
    ) -> bool:
        """解析逃跑：DEX对抗检定。返回是否逃跑成功。"""
        inv_dex = investigator.characteristics.DEX
        # 取敌方最高DEX
        max_enemy_dex = 50
        for _, npc_obj in enemy_npcs:
            if npc_obj:
                max_enemy_dex = max(max_enemy_dex, npc_obj.stats.get("DEX", 50))

        from ..rules.dice import roll_d100
        inv_roll = roll_d100()
        inv_success = inv_roll.result <= inv_dex
        enemy_roll = roll_d100()
        enemy_success = enemy_roll.result <= max_enemy_dex

        fled = inv_success and not enemy_success
        if inv_success and enemy_success:
            fled = inv_roll.result < enemy_roll.result  # 对抗：更低的成功骰赢

        result = "逃跑成功！" if fled else "逃跑失败！被敌人拦住了。"
        detail = (
            f"🏃 {investigator.name}尝试逃跑"
            f"（DEX {inv_dex}，掷出{inv_roll.result}）"
            f"vs 敌方（DEX {max_enemy_dex}，掷出{enemy_roll.result}）"
            f"— {result}"
        )

        round_actions.append({
            "type": "system",
            "content": detail,
        })
        round_actions.append({
            "actor": investigator.name,
            "action_type": "逃跑",
            "target": "",
            "result": result,
            "damage": 0,
        })

        await self.narrative_repo.append(self.session_id, NarrativeEntry(
            source="系统", content=detail, entry_type="dice_roll",
            metadata={"combat": True, "flee": fled},
        ))
        return fled

    # ------------------------------------------------------------------
    # 新版拆分helper：技能检定 / 理智检定 / 场景·战斗·结束
    # ------------------------------------------------------------------

    async def _process_skill_check(
        self,
        match: re.Match,
        investigators: list[Investigator],
        session: GameSession,
        segment_text: str,
        current_action: str,
    ) -> AsyncGenerator[dict, None]:
        """处理单个技能检定标记：掷骰 + yield 结果（不做叙事包装，由场景守密人续写）。

        支持标记格式：
          【技能检定：侦查】
          【技能检定：侦查/困难】
          【技能检定：侦查/困难/奖励1】
          【技能检定：侦查/惩罚2】
          【技能检定：侦查/奖励1/惩罚1】  （相消 → 无额外骰）
        """
        default_inv = investigators[0] if investigators else None
        if not default_inv:
            return

        skill_name = match.group(1).strip()

        # 解析后续修饰组（group 2/3/4 可以是难度、奖励N、惩罚N 任意顺序）
        difficulty_str = ""
        bonus_dice = 0
        penalty_dice = 0
        for g in (match.group(2), match.group(3), match.group(4)):
            if not g:
                continue
            g = g.strip()
            if g in ("普通", "困难", "极难"):
                difficulty_str = g
            elif g.startswith("奖励"):
                try:
                    bonus_dice = int(g.replace("奖励", "")) or 1
                except ValueError:
                    bonus_dice = 1
            elif g.startswith("惩罚"):
                try:
                    penalty_dice = int(g.replace("惩罚", "")) or 1
                except ValueError:
                    penalty_dice = 1

        # 若守密人未指定难度，使用 SkillCheckAgent 推断
        if not difficulty_str:
            hint_start = max(0, match.start() - 1000)
            hint_end = min(len(segment_text), match.end() + 500)
            scene_hint = segment_text[hint_start:hint_end]
            try:
                difficulty_str = await self.skill_narrator.suggest_difficulty(
                    skill_name, current_action, scene_hint,
                )
            except Exception:
                difficulty_str = "普通"

        difficulty = {
            "普通": Difficulty.REGULAR,
            "困难": Difficulty.HARD,
            "极难": Difficulty.EXTREME,
        }.get(difficulty_str, Difficulty.REGULAR)

        skill_val = default_inv.skills.get(skill_name)
        current_val = skill_val.current if skill_val else 1

        result = check_skill(
            skill_name=skill_name,
            skill_value=current_val,
            difficulty=difficulty,
            bonus_dice=bonus_dice,
            penalty_dice=penalty_dice,
        )

        # 基础信息
        dice_info = ""
        if bonus_dice > 0 or penalty_dice > 0:
            parts = []
            if bonus_dice > 0:
                parts.append(f"奖励骰×{bonus_dice}")
            if penalty_dice > 0:
                parts.append(f"惩罚骰×{penalty_dice}")
            dice_info = f"，{'，'.join(parts)}"
            if result.roll.all_options and len(result.roll.all_options) > 1:
                dice_info += f"，可选{result.roll.all_options}"
        detail = (
            f"🎲 {default_inv.name} 的{skill_name}检定"
            f"（{difficulty_str}，目标 {result.target}{dice_info}）"
            f"：掷出 {result.roll.result}"
            f" — {_success_level_cn(result.success_level)}"
        )
        # 大成功 / 大失败特殊提示
        if result.is_critical:
            detail += " 🌟 大成功！结果远超预期！"
        elif result.is_fumble:
            detail += " 💀 大失败！事情朝最糟糕的方向发展！"

        yield {
            "type": "skill_check",
            "investigator": default_inv.name,
            "skill": skill_name,
            "value": current_val,
            "roll": result.roll.result,
            "target": result.target,
            "success_level": result.success_level.name,
            "succeeded": result.succeeded,
            "can_push": result.can_push,
            "is_critical": result.is_critical,
            "is_fumble": result.is_fumble,
            "bonus_dice": bonus_dice,
            "penalty_dice": penalty_dice,
            "detail": detail,
        }

        # 记录日志
        await self.narrative_repo.append(self.session_id, NarrativeEntry(
            source="系统", content=detail, entry_type="dice_roll",
            metadata={"skill": skill_name, "roll": result.roll.result,
                      "target": result.target, "success": result.succeeded,
                      "critical": result.is_critical, "fumble": result.is_fumble},
        ))

        # 经验标记（成功才标记）
        if result.succeeded and skill_val:
            skill_val.experience_check = True
            await self.investigator_repo.save(default_inv, self.session_id)

    async def _process_sanity_check(
        self,
        match: re.Match,
        investigators: list[Investigator],
        session: GameSession,
    ) -> AsyncGenerator[dict, None]:
        """处理单个理智检定标记。"""
        default_inv = investigators[0] if investigators else None
        if not default_inv:
            return

        success_loss = match.group(1).strip()
        fail_loss = match.group(2).strip()

        result = check_sanity(
            current_san=default_inv.derived.san,
            success_loss=success_loss,
            fail_loss=fail_loss,
            san_max=default_inv.derived.san_max,
            int_value=default_inv.characteristics.INT,
        )

        default_inv.derived.san = result.new_san
        await self.investigator_repo.save(default_inv, self.session_id)

        detail = f"🧠 {default_inv.name} 的理智检定：{result.details}"

        yield {
            "type": "sanity_check",
            "investigator": default_inv.name,
            "roll": result.roll_value,
            "target": result.current_san,
            "succeeded": result.succeeded,
            "san_lost": result.san_lost,
            "new_san": result.new_san,
            "temporary_insanity": result.triggered_temporary,
            "indefinite_insanity": result.triggered_indefinite,
            "permanent_insanity": result.triggered_permanent,
            "detail": detail,
        }

        await self.narrative_repo.append(self.session_id, NarrativeEntry(
            source="系统", content=detail, entry_type="dice_roll",
            metadata={"san_lost": result.san_lost, "new_san": result.new_san},
        ))

    async def _process_scene_combat_end(
        self,
        narrative_text: str,
        investigators: list[Investigator],
        session: GameSession,
    ) -> AsyncGenerator[dict, None]:
        """处理场景转换、战斗开始、模组结束标记。"""
        # 场景转换标记
        scene_match = SCENE_CHANGE_PATTERN.search(narrative_text)
        if scene_match:
            new_scene_name = scene_match.group(1).strip()
            new_scene_desc = (scene_match.group(2) or "").strip()
            matched_scene = None
            for sid, sc in session.scenes.items():
                if sc.name == new_scene_name or sid == new_scene_name:
                    matched_scene = sc
                    break
            if matched_scene:
                if session.current_scene:
                    for npc_id in session.current_scene.npcs_present:
                        if npc_id in session.npcs:
                            session.npcs[npc_id].is_present = False
                session.current_scene = matched_scene
                for npc_id in matched_scene.npcs_present:
                    if npc_id in session.npcs:
                        session.npcs[npc_id].is_present = True
            else:
                from ..models.game_state import SceneState
                new_sc = SceneState(
                    id=new_scene_name,
                    name=new_scene_name,
                    description=new_scene_desc,
                )
                session.scenes[new_sc.id] = new_sc
                if session.current_scene:
                    for npc_id in session.current_scene.npcs_present:
                        if npc_id in session.npcs:
                            session.npcs[npc_id].is_present = False
                session.current_scene = new_sc
            await self.session_repo.update(session)
            yield {
                "type": "scene_change",
                "scene_name": new_scene_name,
                "content": f"📍 场景转换：{new_scene_name}",
            }

            if session.module_id:
                mod = await self.module_repo.get(session.module_id)
                if mod:
                    mscene = mod.get_scene(
                        matched_scene.id if matched_scene else new_scene_name,
                    )
                    if mscene and mscene.is_ending:
                        yield {
                            "type": "system",
                            "content": "📍 进入结局场景。守密人将完成最后的叙述。",
                        }

        # 战斗标记
        if COMBAT_PATTERN.search(narrative_text):
            session.phase = GamePhase.COMBAT
            await self.session_repo.update(session)

            from ..models.game_state import CombatParticipant
            participants = []
            for inv in investigators:
                if inv.is_alive and inv.is_conscious:
                    participants.append({
                        "id": inv.id,
                        "is_player": True,
                        "name": inv.name,
                        "dex": inv.characteristics.DEX,
                    })
            for npc_id, npc in session.npcs.items():
                if npc.is_alive and npc.is_present:
                    participants.append({
                        "id": npc_id,
                        "is_player": False,
                        "name": npc.name,
                        "dex": npc.stats.get("DEX", 50),
                    })

            yield {
                "type": "combat_start",
                "participants": participants,
                "content": "⚔️ 进入战斗！请所有调查员准备战斗行动。",
            }

        # 模组结束标记
        if MODULE_END_PATTERN.search(narrative_text):
            session.phase = GamePhase.ENDED
            await self.session_repo.update(session)
            yield {
                "type": "module_end",
                "content": "📖 模组结束。感谢各位调查员的冒险！角色卡已解锁，可进行经验成长。",
            }

        # 自动触发场景转换
        if not scene_match and not MODULE_END_PATTERN.search(narrative_text):
            async for evt in self._check_auto_transitions(session):
                yield evt

    # ------------------------------------------------------------------
    # 旧版 _process_mechanics — 仅供 process_opening_narration 使用
    # ------------------------------------------------------------------

    async def _process_mechanics(
        self,
        narrative_text: str,
        investigators: list[Investigator],
        session: GameSession,
        player_action: str = "",
    ) -> AsyncGenerator[dict, None]:
        """（旧版）解析并处理叙事中的机制标记。仅由 opening / graph 路径调用。"""
        # 技能检定
        for match in SKILL_CHECK_PATTERN.finditer(narrative_text):
            async for event in self._process_skill_check(
                match, investigators, session, narrative_text, player_action,
            ):
                yield event

        # 理智检定
        for match in SANITY_CHECK_PATTERN.finditer(narrative_text):
            async for event in self._process_sanity_check(
                match, investigators, session,
            ):
                yield event

        # 场景/战斗/结束
        async for event in self._process_scene_combat_end(
            narrative_text, investigators, session,
        ):
            yield event

    async def _check_auto_transitions(
        self,
        session: GameSession,
    ) -> AsyncGenerator[dict, None]:
        """检查当前场景是否有 auto_trigger 转场条件已满足。

        当转场的 required_clues 全部已发��时，自动执行场景转换。
        """
        if not session.module_id or not session.current_scene:
            return
        mod = await self.module_repo.get(session.module_id)
        if not mod:
            return
        mscene = mod.get_scene(session.current_scene.id)
        if not mscene or not mscene.transitions:
            return

        # 收集所有已发现线索ID
        discovered_ids = set()
        if session.current_scene:
            discovered_ids.update(session.current_scene.clues_discovered)
        for cid, clue in session.clues.items():
            if clue.is_discovered:
                discovered_ids.add(cid)

        for trans in mscene.transitions:
            if not trans.auto_trigger or not trans.required_clues:
                continue
            # 检查是否所有需要的线索都已发现
            if all(rc in discovered_ids for rc in trans.required_clues):
                target = mod.get_scene(trans.target_scene_id)
                target_name = target.title if target else trans.target_scene_id
                logger.info("自动触发场景转换：%s → %s", mscene.title, target_name)

                # 执行场景转换
                matched = session.scenes.get(trans.target_scene_id)
                if matched:
                    if session.current_scene:
                        for npc_id in session.current_scene.npcs_present:
                            if npc_id in session.npcs:
                                session.npcs[npc_id].is_present = False
                    session.current_scene = matched
                    for npc_id in matched.npcs_present:
                        if npc_id in session.npcs:
                            session.npcs[npc_id].is_present = True
                    await self.session_repo.update(session)

                yield {
                    "type": "scene_change",
                    "scene_name": target_name,
                    "content": f"📍 场景自动转换：{target_name}",
                }

                # 检查是否转换到了结局场景
                if target and target.is_ending:
                    yield {
                        "type": "system",
                        "content": "📍 进入结局场景。守密人将完成最后的叙述。",
                    }
                # 每次只触发一个自动转场
                break

    async def process_action_graph(
        self,
        player_id: str,
        action_text: str,
    ) -> AsyncGenerator[dict, None]:
        """通过LangGraph状态机处理玩家行动

        与process_action_stream不同，这个方法通过LangGraph图执行完整的
        分类->叙事->检定->更新流程。

        用于复杂场景（如战斗轮、多步骤交互）。
        """
        session = await self._get_session()
        investigators = await self._get_investigators()
        recent = await self._get_recent_narrative()

        # 记录玩家行动
        action_entry = NarrativeEntry(
            source=player_id,
            content=action_text,
            entry_type="action",
        )
        await self.narrative_repo.append(self.session_id, action_entry)

        # 构建GraphState初始状态
        inv_map = {inv.id: inv for inv in investigators}
        initial_state = GraphState(
            session_id=self.session_id,
            phase=session.phase,
            module_id=session.module_id if hasattr(session, "module_id") else None,
            current_player_id=player_id,
            current_action=action_text,
            investigators=inv_map,
            narrative_log=recent,
            turn_count=getattr(session, "turn_count", 0),
            current_scene=session.current_scene,
            scenes=session.scenes,
            npcs=session.npcs,
            clues=session.clues,
            combat=session.combat,
            narrative_summary=session.narrative_summary,
            keeper_memory=session.keeper_memory,
        )

        # 调用LangGraph图
        try:
            game_graph = get_game_graph()
            final_state: GraphState = await game_graph.ainvoke(initial_state)
        except Exception as e:
            logger.exception("LangGraph图执行出错")
            yield {"type": "system", "content": f"LangGraph图执行出错：{str(e)}"}
            return

        # 提取叙事输出
        if final_state.narrative_output:
            yield {"type": "narrative_end", "full_text": final_state.narrative_output}

            # 记录守密人叙事（清除机制标记）
            clean_text = SKILL_CHECK_PATTERN.sub('', final_state.narrative_output)
            clean_text = SANITY_CHECK_PATTERN.sub('', clean_text)
            clean_text = COMBAT_PATTERN.sub('', clean_text)
            clean_text = SCENE_CHANGE_PATTERN.sub('', clean_text)
            clean_text = MODULE_END_PATTERN.sub('', clean_text).strip()

            gm_entry = NarrativeEntry(
                source="守密人",
                content=clean_text,
                entry_type="narration",
            )
            await self.narrative_repo.append(self.session_id, gm_entry)

            session = await self._get_session()
            try:
                await merge_narration_into_session_memory(
                    clean_text, session, self.token_tracker,
                )
                npc_hit = detect_npc_dialogue_target(action_text, session)
                if npc_hit:
                    nid, _npc = npc_hit
                    session.keeper_memory.npc_memories.setdefault(nid, [])
                    excerpt = clean_text.replace("\n", " ").strip()[:380]
                    line = f"玩家：{action_text[:140]}… → 回应摘要：{excerpt}"
                    if line not in session.keeper_memory.npc_memories[nid]:
                        session.keeper_memory.npc_memories[nid].append(line)
                    session.keeper_memory.npc_memories[nid] = (
                        session.keeper_memory.npc_memories[nid][-14:]
                    )
                session.updated_at = datetime.now()
                await self.session_repo.update(session)
            except Exception:
                logger.exception("图模式记忆更新失败")

        # 输出机制检定结果
        for result in final_state.mechanic_results:
            event_type = result.get("type", "system")
            yield result

            # 记录到叙事日志
            if "detail" in result:
                await self.narrative_repo.append(self.session_id, NarrativeEntry(
                    source="系统",
                    content=result["detail"],
                    entry_type="dice_roll",
                    metadata={k: v for k, v in result.items() if k not in ("type", "detail")},
                ))

        # 输出广播消息
        for msg in final_state.broadcast_messages:
            yield msg

        # 更新数据库中的角色状态
        for inv_id, inv in final_state.investigators.items():
            await self.investigator_repo.save(inv, self.session_id)

        # 更新会话阶段（如果图修改了）
        if final_state.phase != session.phase:
            session.phase = final_state.phase
            await self.session_repo.update(session)

        # 处理错误信息
        if final_state.error:
            yield {"type": "system", "content": f"图执行警告：{final_state.error}"}

        # 检查Token预算警告
        warning = self.token_tracker.check_budget_warnings()
        if warning:
            yield {"type": "token_warning", "content": warning}

    async def process_action(
        self,
        player_id: str,
        action_text: str,
        use_graph: bool = False,
    ) -> AsyncGenerator[dict, None]:
        """统一入口，根据use_graph选择处理模式

        Args:
            player_id: 玩家ID
            action_text: 行动文本
            use_graph: 是否使用LangGraph状态机模式。
                       False（默认）= 流式模式，适合一般叙事交互
                       True = 图模式，适合战斗轮、多步骤交互等复杂场景
        """
        if use_graph:
            async for event in self.process_action_graph(player_id, action_text):
                yield event
        else:
            async for event in self.process_action_stream(player_id, action_text):
                yield event

    def get_usage_summary(self) -> dict:
        """获取当前Token用量摘要"""
        return self.token_tracker.get_summary()


# 全局游戏循环实例缓存
_game_loops: dict[str, GameLoop] = {}


def get_game_loop(session_id: str) -> GameLoop:
    """获取或创建游戏循环实例"""
    if session_id not in _game_loops:
        _game_loops[session_id] = GameLoop(session_id)
    return _game_loops[session_id]
