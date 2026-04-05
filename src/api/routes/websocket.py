"""WebSocket路由

处理实时游戏交互，接入守密人Agent进行流式叙事。
支持多人回合制、重连、战斗轮管理、玩家聊天。
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ...models.messages import ClientMessage, ServerMessage, MessageType
from ...models.game_state import (
    NarrativeEntry, GamePhase, CombatParticipant, CombatState,
)
from ...middleware.game_loop import get_game_loop
from ...storage.repositories import (
    SessionRepository, NarrativeRepository, InvestigatorRepository,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TurnManager — 结构化回合管理
# ---------------------------------------------------------------------------

class TurnManager:
    """管理结构化回合制，跟踪每轮中各玩家的行动提交状态。

    每个会话可以独立开启一个回合，所有参与玩家提交行动后才进行结算。
    """

    def __init__(self):
        # {session_id: {"players": set[str], "actions": {player_id: action}}}
        self._turns: dict[str, dict[str, Any]] = {}

    def start_structured_turn(self, session_id: str, players: list[str]) -> None:
        """开始一个新的结构化回合，要求所有指定玩家提交行动。"""
        self._turns[session_id] = {
            "players": set(players),
            "actions": {},
            "started_at": datetime.now(),
        }
        logger.info("会话 %s 开始结构化回合，参与者: %s", session_id, players)

    def submit_action(self, session_id: str, player_id: str, action: Any) -> bool:
        """提交某玩家的行动。返回 True 表示提交成功，False 表示该回合不存在或玩家不在列表中。"""
        turn = self._turns.get(session_id)
        if not turn:
            return False
        if player_id not in turn["players"]:
            return False
        turn["actions"][player_id] = action
        return True

    def is_all_submitted(self, session_id: str) -> bool:
        """检查该回合是否所有玩家都已提交行动。"""
        turn = self._turns.get(session_id)
        if not turn:
            return False
        return turn["players"] == set(turn["actions"].keys())

    def get_pending_players(self, session_id: str) -> list[str]:
        """获取尚未提交行动的玩家列表。"""
        turn = self._turns.get(session_id)
        if not turn:
            return []
        return [p for p in turn["players"] if p not in turn["actions"]]

    def resolve_turn(self, session_id: str) -> dict[str, Any]:
        """结算回合——返回所有已提交的行动并重置该回合。"""
        turn = self._turns.pop(session_id, None)
        if not turn:
            return {}
        return dict(turn["actions"])

    def has_active_turn(self, session_id: str) -> bool:
        """该会话是否有活跃的结构化回合。"""
        return session_id in self._turns


# ---------------------------------------------------------------------------
# ConnectionManager — WebSocket 连接管理
# ---------------------------------------------------------------------------

class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        # {session_id: {player_id: WebSocket}}
        self.active_connections: dict[str, dict[str, WebSocket]] = {}
        # 跟踪曾经连接过的玩家，用于判断重连
        # {session_id: set[player_id]}
        self._known_players: dict[str, set[str]] = {}

    async def connect(
        self,
        websocket: WebSocket,
        session_id: str,
        player_id: str,
    ) -> bool:
        """接受连接并注册。返回 True 表示重连，False 表示首次加入。"""
        await websocket.accept()

        is_reconnect = (
            session_id in self._known_players
            and player_id in self._known_players[session_id]
        )

        if session_id not in self.active_connections:
            self.active_connections[session_id] = {}
        if session_id not in self._known_players:
            self._known_players[session_id] = set()

        self.active_connections[session_id][player_id] = websocket
        self._known_players[session_id].add(player_id)

        if is_reconnect:
            # 重连通知
            await self.broadcast(session_id, ServerMessage.system(
                f"玩家 {player_id} 已重新连接"
            ), exclude=player_id)
        else:
            # 首次加入通知
            await self.broadcast(session_id, ServerMessage.system(
                f"玩家 {player_id} 已加入游戏"
            ), exclude=player_id)

        # 发送当前在线玩家列表
        players = list(self.active_connections[session_id].keys())
        await self.send_to_player(session_id, player_id, ServerMessage(
            type=MessageType.PLAYER_LIST,
            data={"players": players},
        ))

        return is_reconnect

    def disconnect(self, session_id: str, player_id: str):
        if session_id in self.active_connections:
            self.active_connections[session_id].pop(player_id, None)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

    async def send_to_player(
        self, session_id: str, player_id: str, message: ServerMessage,
    ):
        """向指定玩家发送消息"""
        connections = self.active_connections.get(session_id, {})
        ws = connections.get(player_id)
        if ws:
            try:
                await ws.send_json(message.model_dump(mode="json"))
            except Exception:
                logger.warning("发送消息给 %s/%s 失败", session_id, player_id)

    async def broadcast(
        self,
        session_id: str,
        message: ServerMessage,
        exclude: Optional[str] = None,
    ):
        """向会话中所有玩家广播消息"""
        connections = self.active_connections.get(session_id, {})
        for player_id, ws in connections.items():
            if player_id != exclude:
                try:
                    await ws.send_json(message.model_dump(mode="json"))
                except Exception:
                    logger.warning("广播消息给 %s/%s 失败", session_id, player_id)

    def get_online_players(self, session_id: str) -> list[str]:
        return list(self.active_connections.get(session_id, {}).keys())


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

manager = ConnectionManager()
turn_manager = TurnManager()


# ---------------------------------------------------------------------------
# 重连辅助
# ---------------------------------------------------------------------------

async def _send_player_character_sheet(session_id: str, player_id: str) -> None:
    """向指定玩家推送本会话中的调查员（首次连接与重连都需要）。

    优先匹配 player_id；若本会话仅有一名调查员，则回退为该角色（单人游戏常见）。
    """
    investigator_repo = InvestigatorRepository()
    investigators = await investigator_repo.list_by_session(session_id)
    for inv in investigators:
        if getattr(inv, "player_id", None) == player_id:
            await manager.send_to_player(session_id, player_id, ServerMessage(
                type=MessageType.CHARACTER_SHEET,
                data=inv.model_dump(mode="json"),
            ))
            return
    if len(investigators) == 1:
        await manager.send_to_player(session_id, player_id, ServerMessage(
            type=MessageType.CHARACTER_SHEET,
            data=investigators[0].model_dump(mode="json"),
        ))


async def push_session_character_sheets(session_id: str) -> None:
    """从数据库重读调查员并推送给在线玩家（技能/SAN 等变更后与 UI 同步，含物品栏）。"""
    investigator_repo = InvestigatorRepository()
    investigators = await investigator_repo.list_by_session(session_id)
    if not investigators:
        return
    connections = manager.active_connections.get(session_id, {})
    for ws_player_id in list(connections.keys()):
        inv = None
        for cand in investigators:
            if getattr(cand, "player_id", None) == ws_player_id:
                inv = cand
                break
        if inv is None and len(investigators) == 1:
            inv = investigators[0]
        if inv is not None:
            await manager.send_to_player(
                session_id,
                ws_player_id,
                ServerMessage(
                    type=MessageType.CHARACTER_SHEET,
                    data=inv.model_dump(mode="json"),
                ),
            )


async def _send_reconnect_catchup(session_id: str, player_id: str):
    """向连接的玩家发送历史叙事（角色卡由 connect 时统一推送）。"""
    narrative_repo = NarrativeRepository()

    # 发送近期叙事（最近50条——足以覆盖多轮游戏）
    # 始终发送 CATCH_UP（含空列表），便于前端在固定时机追加「已连接」等状态，避免与 onopen 抢跑导致历史被跳过。
    recent_entries = await narrative_repo.get_recent(session_id, limit=50)
    await manager.send_to_player(session_id, player_id, ServerMessage(
        type=MessageType.CATCH_UP,
        data={
            "entries": [
                {
                    "source": e.source,
                    "content": e.content,
                    "type": e.entry_type,
                    "timestamp": e.timestamp.isoformat(),
                }
                for e in recent_entries
            ],
            "count": len(recent_entries),
        },
    ))

    # 如果有活跃的结构化回合，通知回合状态
    if turn_manager.has_active_turn(session_id):
        pending = turn_manager.get_pending_players(session_id)
        await manager.send_to_player(session_id, player_id, ServerMessage(
            type=MessageType.TURN_PENDING,
            data={"pending_players": pending},
        ))


# ---------------------------------------------------------------------------
# 战斗轮管理辅助
# ---------------------------------------------------------------------------

async def _start_combat(session_id: str, participants: list[CombatParticipant]):
    """初始化战斗并广播先攻顺序。

    调用方传入参与者列表（已设置好 DEX），此函数排序并广播。
    """
    combat = CombatState(
        round_number=1,
        participants=participants,
    )
    combat.sort_by_dex()

    # 保存到会话状态
    session_repo = SessionRepository()
    session = await session_repo.get(session_id)
    if session:
        session.combat = combat
        session.phase = GamePhase.COMBAT
        await session_repo.update(session)

    # 广播战斗开始
    initiative_order = [
        {"id": p.id, "name": p.name, "dex": p.dex, "is_player": p.is_player}
        for p in combat.participants
    ]
    await manager.broadcast(session_id, ServerMessage(
        type=MessageType.COMBAT_START,
        data={"message": "战斗开始！"},
    ))
    await manager.broadcast(session_id, ServerMessage(
        type=MessageType.COMBAT_INITIATIVE,
        data={"initiative_order": initiative_order},
    ))

    # 开始结构化回合（仅玩家）
    player_ids = [p.id for p in combat.participants if p.is_player]
    if player_ids:
        turn_manager.start_structured_turn(session_id, player_ids)
        await manager.broadcast(session_id, ServerMessage(
            type=MessageType.TURN_START,
            data={
                "round": 1,
                "players": player_ids,
                "message": f"第 1 轮战斗，等待所有玩家行动…",
            },
        ))

    await _broadcast_combat_round(session_id, combat)


async def _broadcast_combat_round(session_id: str, combat: CombatState):
    """广播当前战斗轮信息。"""
    current = combat.current_participant
    await manager.broadcast(session_id, ServerMessage(
        type=MessageType.COMBAT_ROUND,
        data={
            "round": combat.round_number,
            "current_turn": {
                "id": current.id,
                "name": current.name,
                "is_player": current.is_player,
            } if current else None,
            "participants": [
                {
                    "id": p.id,
                    "name": p.name,
                    "has_acted": p.has_acted,
                    "is_player": p.is_player,
                }
                for p in combat.participants
            ],
        },
    ))


async def _advance_combat(session_id: str):
    """推进战斗——如果所有参与者均已行动，进入下一轮。"""
    session_repo = SessionRepository()
    session = await session_repo.get(session_id)
    if not session or not session.combat:
        return

    combat = session.combat
    if combat.all_acted:
        # 新一轮
        combat.round_number += 1
        for p in combat.participants:
            p.has_acted = False
            p.dodge_used = False
        combat.current_turn_index = 0

        await session_repo.update(session)

        # 开始新的结构化回合
        player_ids = [p.id for p in combat.participants if p.is_player]
        if player_ids:
            turn_manager.start_structured_turn(session_id, player_ids)
            await manager.broadcast(session_id, ServerMessage(
                type=MessageType.TURN_START,
                data={
                    "round": combat.round_number,
                    "players": player_ids,
                    "message": f"第 {combat.round_number} 轮战斗，等待所有玩家行动…",
                },
            ))

        await _broadcast_combat_round(session_id, combat)
    else:
        # 移到下一个未行动的参与者
        for i in range(len(combat.participants)):
            idx = (combat.current_turn_index + 1 + i) % len(combat.participants)
            if not combat.participants[idx].has_acted:
                combat.current_turn_index = idx
                break
        await session_repo.update(session)
        await _broadcast_combat_round(session_id, combat)


async def end_combat(session_id: str):
    """结束战斗，恢复探索阶段。"""
    session_repo = SessionRepository()
    session = await session_repo.get(session_id)
    if session:
        session.combat = None
        session.phase = GamePhase.EXPLORATION
        await session_repo.update(session)

    await manager.broadcast(session_id, ServerMessage(
        type=MessageType.COMBAT_END,
        data={"message": "战斗结束"},
    ))


# ---------------------------------------------------------------------------
# 消息处理器
# ---------------------------------------------------------------------------

async def _handle_ping(session_id: str, player_id: str):
    """心跳响应"""
    await manager.send_to_player(session_id, player_id, ServerMessage(
        type=MessageType.PONG,
        data={"server_time": datetime.now().isoformat()},
    ))


async def _handle_chat(session_id: str, player_id: str, data: dict):
    """玩家间聊天（非游戏行动）"""
    text = data.get("text", "").strip()
    if not text:
        return
    target = data.get("target")  # 私聊目标，None则广播
    msg = ServerMessage(
        type=MessageType.CHAT,
        data={
            "from": player_id,
            "text": text,
            "target": target,
            "timestamp": datetime.now().isoformat(),
        },
    )
    if target:
        # 私聊：发给目标和发送者
        await manager.send_to_player(session_id, target, msg)
        await manager.send_to_player(session_id, player_id, msg)
    else:
        await manager.broadcast(session_id, msg)


async def _handle_request_character_update(session_id: str, player_id: str):
    """向请求方发送最新角色数据"""
    investigator_repo = InvestigatorRepository()
    investigators = await investigator_repo.list_by_session(session_id)
    for inv in investigators:
        if getattr(inv, "player_id", None) == player_id:
            await manager.send_to_player(session_id, player_id, ServerMessage(
                type=MessageType.CHARACTER_SHEET,
                data=inv.model_dump(mode="json"),
            ))
            return
    if len(investigators) == 1:
        await manager.send_to_player(session_id, player_id, ServerMessage(
            type=MessageType.CHARACTER_SHEET,
            data=investigators[0].model_dump(mode="json"),
        ))
        return
    await manager.send_to_player(session_id, player_id, ServerMessage.error(
        "未找到你的角色数据", target=player_id,
    ))


async def _handle_player_action(session_id: str, player_id: str, data: dict):
    """处理玩家行动——兼容自由模式和回合制模式。"""
    action_text = data.get("text", "").strip()
    if not action_text:
        return

    # 如果当前有活跃的结构化回合，将行动记录到回合管理器
    if turn_manager.has_active_turn(session_id):
        ok = turn_manager.submit_action(session_id, player_id, action_text)
        if not ok:
            await manager.send_to_player(session_id, player_id, ServerMessage.error(
                "当前回合不需要你提交行动"
            ))
            return

        # 确认提交
        await manager.send_to_player(session_id, player_id, ServerMessage(
            type=MessageType.ACTION_SUBMITTED,
            data={"player_id": player_id, "action": action_text},
        ))

        # 广播等待状态
        pending = turn_manager.get_pending_players(session_id)
        await manager.broadcast(session_id, ServerMessage(
            type=MessageType.TURN_PENDING,
            data={"pending_players": pending},
        ))

        # 如果所有人都已提交，结算回合
        if turn_manager.is_all_submitted(session_id):
            all_actions = turn_manager.resolve_turn(session_id)
            await manager.broadcast(session_id, ServerMessage(
                type=MessageType.TURN_ALL_SUBMITTED,
                data={"actions": all_actions},
            ))

            # 按顺序将所有行动送入游戏循环
            game_loop = get_game_loop(session_id)
            for pid, act in all_actions.items():
                # 广播玩家行动
                await manager.broadcast(session_id, ServerMessage(
                    type=MessageType.NARRATIVE,
                    data={
                        "content": f"【{pid}】{act}",
                        "source": pid,
                        "type": "action",
                    },
                ))
                try:
                    async for event in game_loop.process_action_stream(
                        player_id=pid,
                        action_text=act,
                    ):
                        await _handle_game_event(session_id, event)
                except Exception as e:
                    error_detail = traceback.format_exc()
                    logger.error("游戏循环错误（回合制）: %s", error_detail)
                    await manager.broadcast(session_id, ServerMessage.system(
                        f"处理 {pid} 的行动时出错：{str(e)}"
                    ))

            # 如果处于战斗中，推进战斗轮
            session_repo = SessionRepository()
            session = await session_repo.get(session_id)
            if session and session.phase == GamePhase.COMBAT and session.combat:
                await _advance_combat(session_id)

            await push_session_character_sheets(session_id)
        return

    # --- 自由模式（原有逻辑） ---

    # 检查是否处于战斗中——如是，当作战斗行动处理
    session_repo = SessionRepository()
    session = await session_repo.get(session_id)
    if session and session.phase == GamePhase.COMBAT and session.combat:
        await _handle_combat_action(session_id, player_id, data)
        return

    # 广播玩家行动给所有人
    await manager.broadcast(session_id, ServerMessage(
        type=MessageType.NARRATIVE,
        data={
            "content": f"【{player_id}】{action_text}",
            "source": player_id,
            "type": "action",
        },
    ))

    # 获取游戏循环并处理行动
    game_loop = get_game_loop(session_id)

    try:
        async for event in game_loop.process_action_stream(
            player_id=player_id,
            action_text=action_text,
        ):
            await _handle_game_event(session_id, event)
    except Exception as e:
        error_detail = traceback.format_exc()
        logger.error("游戏循环错误: %s", error_detail)
        await manager.broadcast(session_id, ServerMessage.system(
            f"处理行动时出错：{str(e)}"
        ))
    finally:
        await push_session_character_sheets(session_id)


async def _handle_combat_action(session_id: str, player_id: str, data: dict):
    """处理战斗行动——标记参与者已行动并推进。

    支持两种模式：
    - 多人回合制：通过 TurnManager 收集所有人的行动后统一结算
    - 单人自由模式：立即通过游戏循环处理
    """
    session_repo = SessionRepository()
    session = await session_repo.get(session_id)
    if not session or not session.combat:
        await manager.send_to_player(session_id, player_id, ServerMessage.error(
            "当前不在战斗中"
        ))
        return

    action_text = data.get("text", "战斗行动")

    # 找到该玩家对应的参与者（player_id 可能是玩家ID而非调查员ID）
    investigator_repo = InvestigatorRepository()
    investigators = await investigator_repo.list_by_session(session_id)
    participant_id = player_id  # 默认
    for inv in investigators:
        if getattr(inv, "player_id", None) == player_id:
            participant_id = inv.id
            break

    # 标记已行动
    for p in session.combat.participants:
        if p.id == participant_id or p.id == player_id:
            p.has_acted = True
            break

    await session_repo.update(session)

    # 多人回合制模式
    if turn_manager.has_active_turn(session_id):
        turn_manager.submit_action(session_id, participant_id, action_text)

        pending = turn_manager.get_pending_players(session_id)
        await manager.broadcast(session_id, ServerMessage(
            type=MessageType.TURN_PENDING,
            data={"pending_players": pending},
        ))

        if turn_manager.is_all_submitted(session_id):
            all_actions = turn_manager.resolve_turn(session_id)
            await manager.broadcast(session_id, ServerMessage(
                type=MessageType.TURN_ALL_SUBMITTED,
                data={"actions": all_actions},
            ))

            # 处理所有战斗行动
            game_loop = get_game_loop(session_id)
            for pid, act in all_actions.items():
                await manager.broadcast(session_id, ServerMessage(
                    type=MessageType.NARRATIVE,
                    data={
                        "content": f"【{pid}】{act}",
                        "source": pid,
                        "type": "action",
                    },
                ))
                try:
                    async for event in game_loop.process_action_stream(
                        player_id=pid,
                        action_text=act,
                    ):
                        await _handle_game_event(session_id, event)
                except Exception as e:
                    logger.error("战斗行动处理错误: %s", traceback.format_exc())
                    await manager.broadcast(session_id, ServerMessage.system(
                        f"处理 {pid} 的战斗行动时出错：{str(e)}"
                    ))

            await _advance_combat(session_id)
            await push_session_character_sheets(session_id)
        return

    # 单人自由模式——立即处理
    await manager.broadcast(session_id, ServerMessage(
        type=MessageType.NARRATIVE,
        data={
            "content": f"【{player_id}】{action_text}",
            "source": player_id,
            "type": "action",
        },
    ))

    game_loop = get_game_loop(session_id)
    try:
        async for event in game_loop.process_action_stream(
            player_id=player_id,
            action_text=action_text,
        ):
            await _handle_game_event(session_id, event)
    except Exception as e:
        logger.error("战斗行动处理错误: %s", traceback.format_exc())
        await manager.broadcast(session_id, ServerMessage.system(
            f"处理战斗行动时出错：{str(e)}"
        ))

    await _advance_combat(session_id)
    await push_session_character_sheets(session_id)


# ---------------------------------------------------------------------------
# WebSocket 端点
# ---------------------------------------------------------------------------

@router.websocket("/ws/{session_id}/{player_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str, player_id: str):
    """WebSocket游戏连接端点"""
    is_reconnect = await manager.connect(websocket, session_id, player_id)

    try:
        await _send_player_character_sheet(session_id, player_id)
    except Exception:
        logger.warning("推送角色卡失败: %s", traceback.format_exc())

    # 总是发送历史叙事（无论首次还是重连，刷新页面后需要恢复对话记录）
    try:
        await _send_reconnect_catchup(session_id, player_id)
    except Exception:
        logger.warning("发送历史叙事失败: %s", traceback.format_exc())

    try:
        while True:
            data = await websocket.receive_json()
            msg_type_raw = data.get("type", "player_action")

            # 心跳检测——快速路径，不需要解析为 ClientMessage
            if msg_type_raw == "ping":
                await _handle_ping(session_id, player_id)
                continue

            msg = ClientMessage(
                type=MessageType(msg_type_raw),
                player_id=player_id,
                data=data.get("data", {}),
            )

            if msg.type == MessageType.PLAYER_ACTION:
                await _handle_player_action(session_id, player_id, msg.data)

            elif msg.type == MessageType.COMBAT_ACTION:
                await _handle_combat_action(session_id, player_id, msg.data)

            elif msg.type == MessageType.CHAT:
                await _handle_chat(session_id, player_id, msg.data)

            elif msg.type == MessageType.REQUEST_CHARACTER_UPDATE:
                await _handle_request_character_update(session_id, player_id)

            # 未识别的消息类型——忽略但记录
            else:
                logger.debug("未处理的消息类型: %s (玩家: %s)", msg.type, player_id)

    except WebSocketDisconnect:
        manager.disconnect(session_id, player_id)
        await manager.broadcast(session_id, ServerMessage.system(
            f"玩家 {player_id} 已离开游戏"
        ))


# ---------------------------------------------------------------------------
# 游戏事件 -> WebSocket 消息
# ---------------------------------------------------------------------------

async def _handle_game_event(session_id: str, event: dict):
    """将游戏循环事件转换为WebSocket消息并广播"""
    event_type = event.get("type")

    if event_type == "narrative_chunk":
        chunk_data: dict = {"chunk": event["chunk"]}
        if event.get("npc_name"):
            chunk_data["npc_name"] = event["npc_name"]
        await manager.broadcast(session_id, ServerMessage(
            type=MessageType.NARRATIVE_CHUNK,
            data=chunk_data,
        ))

    elif event_type == "narrative_end":
        # 叙事完成——前端通过 chunk 拼接，此处可发送完整信息供前端做最终处理
        if event.get("npc_name"):
            await manager.broadcast(session_id, ServerMessage(
                type=MessageType.NARRATIVE,
                data={
                    "content": event["full_text"],
                    "source": event["npc_name"],
                    "type": "npc_dialogue",
                },
            ))

    elif event_type == "skill_check":
        await manager.broadcast(session_id, ServerMessage(
            type=MessageType.DICE_RESULT,
            data=event,
        ))
        # 也作为叙事显示
        await manager.broadcast(session_id, ServerMessage(
            type=MessageType.NARRATIVE,
            data={
                "content": event["detail"],
                "source": "系统",
                "type": "dice_roll",
            },
        ))

    elif event_type == "sanity_check":
        await manager.broadcast(session_id, ServerMessage(
            type=MessageType.DICE_RESULT,
            data=event,
        ))
        await manager.broadcast(session_id, ServerMessage(
            type=MessageType.NARRATIVE,
            data={
                "content": event["detail"],
                "source": "系统",
                "type": "dice_roll",
            },
        ))

    elif event_type == "combat_start":
        # 检测到【进入战斗】标记——自动切换到回合制
        participants_data = event.get("participants", [])
        participants = [
            CombatParticipant(**p) if isinstance(p, dict) else p
            for p in participants_data
        ]
        if participants:
            await _start_combat(session_id, participants)

    elif event_type == "combat_end":
        await end_combat(session_id)

    elif event_type == "module_end":
        await manager.broadcast(session_id, ServerMessage.system(event["content"]))
        # 推送更新后的角色卡（已解锁，可编辑/成长）
        investigator_repo = InvestigatorRepository()
        investigators = await investigator_repo.list_by_session(session_id)
        for inv in investigators:
            await manager.broadcast(session_id, ServerMessage(
                type=MessageType.CHARACTER_SHEET,
                data=inv.model_dump(mode="json"),
            ))

    elif event_type == "system":
        await manager.broadcast(session_id, ServerMessage.system(event["content"]))

    elif event_type == "token_warning":
        await manager.broadcast(session_id, ServerMessage.system(event["content"]))

    elif event_type == "state_update":
        await manager.broadcast(session_id, ServerMessage(
            type=MessageType.STATE_UPDATE,
            data=event.get("data", {}),
        ))
