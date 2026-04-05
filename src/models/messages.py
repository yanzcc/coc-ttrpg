"""WebSocket消息类型定义

客户端和服务端之间的消息协议。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """消息类型"""
    # 客户端 -> 服务端
    PLAYER_ACTION = "player_action"         # 玩家行动
    PLAYER_JOIN = "player_join"             # 玩家加入
    PLAYER_LEAVE = "player_leave"           # 玩家离开
    CHARACTER_UPDATE = "character_update"    # 角色信息更新
    COMBAT_ACTION = "combat_action"         # 战斗行动
    PUSH_ROLL = "push_roll"                 # 孤注一掷

    # 服务端 -> 客户端
    NARRATIVE = "narrative"                 # 叙事文本（可流式）
    NARRATIVE_CHUNK = "narrative_chunk"     # 流式叙事片段
    DICE_RESULT = "dice_result"             # 骰子结果
    STATE_UPDATE = "state_update"           # 游戏状态更新
    CHARACTER_SHEET = "character_sheet"     # 角色卡更新
    COMBAT_UPDATE = "combat_update"         # 战斗状态更新
    TURN_PROMPT = "turn_prompt"             # 轮到某玩家行动
    SYSTEM_MESSAGE = "system_message"       # 系统消息
    ERROR = "error"                         # 错误消息
    PLAYER_LIST = "player_list"             # 在线玩家列表
    CATCH_UP = "catch_up"                   # 重连回顾摘要

    # 回合制相关
    TURN_START = "turn_start"               # 回合开始通知
    TURN_ALL_SUBMITTED = "turn_all_submitted"  # 所有玩家已提交行动
    TURN_PENDING = "turn_pending"           # 等待中的玩家列表
    ACTION_SUBMITTED = "action_submitted"   # 行动已提交确认

    # 战斗轮相关
    COMBAT_START = "combat_start"           # 战斗开始
    COMBAT_INITIATIVE = "combat_initiative" # 先攻顺序
    COMBAT_ROUND = "combat_round"           # 战斗轮信息
    COMBAT_END = "combat_end"               # 战斗结束

    # 聊天 & 心跳
    CHAT = "chat"                           # 玩家间聊天
    PING = "ping"                           # 心跳请求
    PONG = "pong"                           # 心跳响应

    # 请求
    REQUEST_CHARACTER_UPDATE = "request_character_update"  # 请求角色数据


class ClientMessage(BaseModel):
    """客户端发送的消息"""
    type: MessageType
    player_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)


class ServerMessage(BaseModel):
    """服务端发送的消息"""
    type: MessageType
    data: dict[str, Any] = Field(default_factory=dict)
    target_player: Optional[str] = None  # None表示广播给所有人
    timestamp: datetime = Field(default_factory=datetime.now)

    @classmethod
    def narrative(cls, content: str, target: Optional[str] = None) -> ServerMessage:
        return cls(type=MessageType.NARRATIVE, data={"content": content}, target_player=target)

    @classmethod
    def narrative_chunk(cls, chunk: str, target: Optional[str] = None) -> ServerMessage:
        return cls(type=MessageType.NARRATIVE_CHUNK, data={"chunk": chunk}, target_player=target)

    @classmethod
    def dice_result(cls, result: dict, target: Optional[str] = None) -> ServerMessage:
        return cls(type=MessageType.DICE_RESULT, data=result, target_player=target)

    @classmethod
    def system(cls, content: str, target: Optional[str] = None) -> ServerMessage:
        return cls(type=MessageType.SYSTEM_MESSAGE, data={"content": content}, target_player=target)

    @classmethod
    def error(cls, message: str, target: Optional[str] = None) -> ServerMessage:
        return cls(type=MessageType.ERROR, data={"message": message}, target_player=target)
