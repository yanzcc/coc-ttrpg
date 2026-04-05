"""故事生成Agent

负责从种子提示词生成完整CoC场景/模组，或将已有模组文档导入为标准格式。
作为预处理步骤运行，非每轮调用。
"""

from __future__ import annotations

import json
import re
from typing import AsyncGenerator, Optional

from .base import BaseAgent
from ..config import get_settings
from ..middleware.token_tracker import TokenTracker
from ..models.story_module import (
    StoryModule,
    ModuleMetadata,
    ModuleNPC,
    ModuleLocation,
    ModuleScene,
    ModuleClue,
    TimelineEvent,
    SceneTransition,
    Difficulty,
)

STORY_GEN_SYSTEM_PROMPT = """你是克苏鲁的呼唤模组设计专家。

你的职责是创建完整、可玩的CoC第7版模组。

# 模组结构要求
每个模组必须包含：
1. 元数据：标题、时代（1920s/现代）、建议人数、预计时长、难度
2. 背景故事：事件起因、幕后真相
3. NPC列表：每个NPC需要姓名、描述、动机、秘密信息
4. 地点列表：每个地点需要名称、描述、可发现的线索、连接到其他地点
5. 场景列表：每个场景需要ID、触发条件、朗读文本、可能的转场
6. 线索网络：每条线索需要ID、描述、发现方式、指向什么
7. 时间线：如果调查员不干预，事件将如何发展

# 设计原则
- 确保核心线索有多种发现方式（不要单点失败）
- NPC动机要合理且有层次
- 氛围要符合CoC的宇宙恐怖基调
- 故事要有明确的开头、发展和高潮
- 使用中文

# 输出格式
必须使用JSON格式输出，结构符合StoryModule模型定义。
"""

# tool_use工具定义：让Claude以结构化JSON返回完整模组
_MODULE_TOOL = {
    "name": "create_module",
    "description": "创建一个完整的CoC模组，以结构化JSON返回。",
    "input_schema": {
        "type": "object",
        "properties": {
            "metadata": {
                "type": "object",
                "description": "模组元数据",
                "properties": {
                    "title": {"type": "string", "description": "模组标题"},
                    "author": {"type": "string", "description": "作者"},
                    "era": {"type": "string", "description": "时代背景，如 '1920s' 或 '现代'"},
                    "player_count_min": {"type": "integer", "description": "最少玩家数"},
                    "player_count_max": {"type": "integer", "description": "最多玩家数"},
                    "estimated_sessions": {"type": "integer", "description": "预计游戏次数"},
                    "difficulty": {"type": "string", "enum": ["简单", "普通", "困难", "致命"]},
                    "summary": {"type": "string", "description": "模组简介"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "标签"},
                },
                "required": ["title", "summary"],
            },
            "npcs": {
                "type": "array",
                "description": "NPC列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "age": {"type": "integer"},
                        "occupation": {"type": "string"},
                        "description": {"type": "string"},
                        "personality": {"type": "string"},
                        "motivation": {"type": "string"},
                        "secret": {"type": "string"},
                        "dialogue_style": {"type": "string"},
                        "stats": {"type": "object", "description": "属性值字典"},
                        "skills": {"type": "object", "description": "技能值字典"},
                        "initial_attitude": {"type": "string"},
                    },
                    "required": ["id", "name"],
                },
            },
            "locations": {
                "type": "array",
                "description": "地点列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "atmosphere": {"type": "string"},
                        "clue_ids": {"type": "array", "items": {"type": "string"}},
                        "npc_ids": {"type": "array", "items": {"type": "string"}},
                        "connections": {"type": "object"},
                        "events": {"type": "array", "items": {"type": "string"}},
                        "is_starting_location": {"type": "boolean"},
                    },
                    "required": ["id", "name"],
                },
            },
            "scenes": {
                "type": "array",
                "description": "场景列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "read_aloud": {"type": "string"},
                        "location_id": {"type": "string"},
                        "npc_ids": {"type": "array", "items": {"type": "string"}},
                        "clue_ids": {"type": "array", "items": {"type": "string"}},
                        "likely_skill_checks": {"type": "array", "items": {"type": "string"}},
                        "transitions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "target_scene_id": {"type": "string"},
                                    "condition": {"type": "string"},
                                    "required_clues": {"type": "array", "items": {"type": "string"}},
                                    "auto_trigger": {"type": "boolean"},
                                },
                                "required": ["target_scene_id"],
                            },
                        },
                        "is_opening": {"type": "boolean"},
                        "is_climax": {"type": "boolean"},
                        "is_ending": {"type": "boolean"},
                    },
                    "required": ["id", "title"],
                },
            },
            "clues": {
                "type": "array",
                "description": "线索列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "core": {"type": "boolean"},
                        "location_id": {"type": "string"},
                        "discovery_method": {"type": "string"},
                        "discovery_difficulty": {"type": "string"},
                        "leads_to": {"type": "array", "items": {"type": "string"}},
                        "handout_text": {"type": "string"},
                    },
                    "required": ["id", "name"],
                },
            },
            "timeline": {
                "type": "array",
                "description": "时间线事件（调查员不干预时发生的事件）",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "description": {"type": "string"},
                        "trigger_condition": {"type": "string"},
                        "consequences": {"type": "string"},
                    },
                    "required": ["id", "description"],
                },
            },
        },
        "required": ["metadata", "npcs", "locations", "scenes", "clues", "timeline"],
    },
}


def _build_user_prompt(
    seed_prompt: str,
    era: str,
    player_count: int,
    difficulty: str,
) -> str:
    """构造生成模组的用户提示词"""
    return (
        f"请根据以下要求生成一个完整的CoC模组：\n\n"
        f"## 创意种子\n{seed_prompt}\n\n"
        f"## 参数\n"
        f"- 时代背景：{era}\n"
        f"- 建议玩家人数：{player_count}\n"
        f"- 难度：{difficulty}\n\n"
        f"请使用 create_module 工具输出完整模组。确保：\n"
        f"1. 至少3个NPC、3个地点、4个场景、5条线索、3个时间线事件\n"
        f"2. 核心线索要有多种发现途径\n"
        f"3. 场景之间要有清晰的转场逻辑\n"
        f"4. 故事有完整的起承转合\n"
    )


def _parse_tool_result(blocks: list[dict]) -> StoryModule:
    """从invoke_with_tools返回的content blocks中解析StoryModule"""
    for block in blocks:
        if block.get("type") == "tool_use" and block.get("name") == "create_module":
            data = block["input"]
            return _dict_to_module(data)
    # 如果没有tool_use块，尝试从text块中提取JSON
    for block in blocks:
        if block.get("type") == "text":
            text = block["text"]
            json_match = re.search(r"\{[\s\S]*\}", text)
            if json_match:
                data = json.loads(json_match.group())
                return _dict_to_module(data)
    raise ValueError("Claude未返回有效的模组数据，请重试")


def _dict_to_module(data: dict) -> StoryModule:
    """将字典数据转换为StoryModule，处理字段默认值"""
    # 解析metadata
    meta_raw = data.get("metadata", {})
    difficulty_val = meta_raw.get("difficulty", "普通")
    # 映射难度字符串到枚举
    difficulty_map = {"简单": Difficulty.EASY, "普通": Difficulty.NORMAL, "困难": Difficulty.HARD, "致命": Difficulty.DEADLY}
    meta_raw["difficulty"] = difficulty_map.get(difficulty_val, Difficulty.NORMAL)
    metadata = ModuleMetadata(**{k: v for k, v in meta_raw.items() if k in ModuleMetadata.model_fields})

    # 解析NPCs
    npcs = []
    for npc_raw in data.get("npcs", []):
        npcs.append(ModuleNPC(**{k: v for k, v in npc_raw.items() if k in ModuleNPC.model_fields}))

    # 解析地点
    locations = []
    for loc_raw in data.get("locations", []):
        locations.append(ModuleLocation(**{k: v for k, v in loc_raw.items() if k in ModuleLocation.model_fields}))

    # 解析场景
    scenes = []
    for scene_raw in data.get("scenes", []):
        transitions = []
        for t in scene_raw.get("transitions", []):
            transitions.append(SceneTransition(**{k: v for k, v in t.items() if k in SceneTransition.model_fields}))
        scene_data = {k: v for k, v in scene_raw.items() if k in ModuleScene.model_fields and k != "transitions"}
        scene_data["transitions"] = transitions
        scenes.append(ModuleScene(**scene_data))

    # 解析线索
    clues = []
    for clue_raw in data.get("clues", []):
        clues.append(ModuleClue(**{k: v for k, v in clue_raw.items() if k in ModuleClue.model_fields}))

    # 解析时间线
    timeline = []
    for evt_raw in data.get("timeline", []):
        timeline.append(TimelineEvent(**{k: v for k, v in evt_raw.items() if k in TimelineEvent.model_fields}))

    return StoryModule(
        metadata=metadata,
        npcs=npcs,
        locations=locations,
        scenes=scenes,
        clues=clues,
        timeline=timeline,
    )


class StoryGeneratorAgent(BaseAgent):
    def __init__(self, token_tracker: Optional[TokenTracker] = None, model: Optional[str] = None):
        super().__init__(
            name="故事生成",
            system_prompt=STORY_GEN_SYSTEM_PROMPT,
            token_tracker=token_tracker,
            model=model,
            max_tokens=get_settings().agents.story_gen,
        )

    async def generate_module(
        self,
        seed_prompt: str,
        era: str = "1920s",
        player_count: int = 3,
        difficulty: str = "普通",
    ) -> StoryModule:
        """从种子提示词生成完整模组

        使用invoke_with_tools获取结构化JSON输出，然后解析为StoryModule。

        Args:
            seed_prompt: 模组创意描述（如"一栋闹鬼的维多利亚庄园"）
            era: 时代背景
            player_count: 建议玩家人数
            difficulty: 难度（简单/普通/困难/致命）

        Returns:
            解析后的StoryModule实例
        """
        user_msg = _build_user_prompt(seed_prompt, era, player_count, difficulty)
        messages = [{"role": "user", "content": user_msg}]

        blocks, _usage = await self.invoke_with_tools(
            messages=messages,
            tools=[_MODULE_TOOL],
            temperature=0.8,
        )

        return _parse_tool_result(blocks)

    async def generate_module_stream(
        self,
        seed_prompt: str,
        era: str = "1920s",
        player_count: int = 3,
        difficulty: str = "普通",
    ) -> AsyncGenerator[str, None]:
        """流式生成模组（用于显示进度）

        先通过流式输出让用户看到生成过程，然后在流结束后
        调用generate_module获取结构化结果。

        Yields:
            生成过程中的文本片段（用于前端显示进度）
        """
        user_msg = _build_user_prompt(seed_prompt, era, player_count, difficulty)
        # 流式提示词不要求tool_use，让Claude自由输出方便实时展示
        stream_prompt = (
            f"{user_msg}\n\n"
            f"请直接用中文描述你正在设计的模组内容，包括故事概要、NPC设定、"
            f"地点描述、场景设计、线索网络和时间线。\n"
            f"不需要JSON格式，用自然语言描述即可。"
        )
        messages = [{"role": "user", "content": stream_prompt}]

        async for chunk in self.stream(messages=messages, temperature=0.8):
            yield chunk
