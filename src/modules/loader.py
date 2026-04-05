"""模组导入器

将外部模组文档（Markdown/纯文本）解析为标准StoryModule格式。
使用Claude API进行智能提取。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from ..agents.base import BaseAgent
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

MODULE_EXTRACT_PROMPT = """你是一个CoC模组内容提取专家。

你的任务是从模组文档文本中提取结构化信息，转换为标准JSON格式。

提取要素：
1. 模组标题和元数据
2. 所有NPC及其属性
3. 所有地点及其描述
4. 所有场景及其触发条件
5. 所有线索及其发现方式
6. 时间线事件

请以JSON格式输出，格式如下：
{
  "metadata": {
    "title": "模组标题",
    "author": "作者（如有）",
    "era": "1920s 或 现代",
    "player_count_min": 2,
    "player_count_max": 5,
    "estimated_sessions": 1,
    "difficulty": "普通",
    "summary": "模组简介",
    "tags": ["标签1", "标签2"]
  },
  "npcs": [
    {
      "id": "npc_唯一标识",
      "name": "名字",
      "age": 30,
      "occupation": "职业",
      "description": "外貌与特征",
      "personality": "性格",
      "motivation": "动机",
      "secret": "隐藏信息",
      "dialogue_style": "说话风格",
      "stats": {},
      "skills": {},
      "initial_attitude": "中立"
    }
  ],
  "locations": [
    {
      "id": "loc_唯一标识",
      "name": "地点名",
      "description": "描述",
      "atmosphere": "氛围",
      "clue_ids": [],
      "npc_ids": [],
      "connections": {},
      "events": [],
      "is_starting_location": false
    }
  ],
  "scenes": [
    {
      "id": "scene_唯一标识",
      "title": "场景标题",
      "description": "守密人描述",
      "read_aloud": "朗读文本",
      "location_id": "",
      "npc_ids": [],
      "clue_ids": [],
      "likely_skill_checks": [],
      "transitions": [
        {
          "target_scene_id": "",
          "condition": "触发条件",
          "required_clues": [],
          "auto_trigger": false
        }
      ],
      "is_opening": false,
      "is_climax": false,
      "is_ending": false
    }
  ],
  "clues": [
    {
      "id": "clue_唯一标识",
      "name": "线索名",
      "description": "描述",
      "core": false,
      "location_id": "",
      "discovery_method": "发现方式",
      "discovery_difficulty": "普通",
      "leads_to": [],
      "handout_text": null
    }
  ],
  "timeline": [
    {
      "id": "evt_唯一标识",
      "description": "事件描述",
      "trigger_condition": "触发条件",
      "consequences": "后果"
    }
  ]
}

重要规则：
- 对文档中明确提到的内容忠实提取，不要编造未出现的信息
- 对ID使用 snake_case 格式，如 npc_old_man, loc_church
- 如果某些字段在原文中未提及，使用合理默认值
- 确保所有交叉引用ID一致（线索的location_id必须对应某个location的id）
- 只输出JSON，不要添加其他解释文字
"""

# 支持读取的文件后缀
_SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".text"}

# 文本分块阈值（单次API调用最大字符数，超过则分块处理）
_MAX_CHUNK_CHARS = 80_000


def _extract_json(text: str) -> dict:
    """从Claude响应文本中提取JSON对象

    处理可能包含markdown代码块标记的情况。
    """
    # 尝试直接解析
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)

    # 尝试提取代码块中的JSON
    code_block = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", text)
    if code_block:
        return json.loads(code_block.group(1).strip())

    # 最后尝试找第一个{到最后一个}
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError("无法从响应中提取有效JSON")


def _dict_to_module(data: dict) -> StoryModule:
    """将字典转换为StoryModule，宽容处理缺失字段"""
    # 解析metadata
    meta_raw = data.get("metadata", {})
    difficulty_val = meta_raw.get("difficulty", "普通")
    difficulty_map = {
        "简单": Difficulty.EASY,
        "普通": Difficulty.NORMAL,
        "困难": Difficulty.HARD,
        "致命": Difficulty.DEADLY,
    }
    meta_raw["difficulty"] = difficulty_map.get(difficulty_val, Difficulty.NORMAL)
    # 确保必填字段
    if "title" not in meta_raw:
        meta_raw["title"] = "未命名模组"
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


class ModuleLoader:
    """模组加载器

    使用Claude API将非结构化的模组文档智能提取为标准StoryModule格式。
    """

    def __init__(self, token_tracker: Optional[TokenTracker] = None):
        self.agent = BaseAgent(
            name="模组导入",
            system_prompt=MODULE_EXTRACT_PROMPT,
            token_tracker=token_tracker,
            max_tokens=get_settings().agents.module_loader,
        )

    async def load_from_text(self, text: str, filename: str = "") -> StoryModule:
        """从纯文本导入模组

        将文本发送给Claude进行结构化提取。对于超长文本会自动分块。

        Args:
            text: 模组文档文本
            filename: 原始文件名（可选，用于辅助判断）

        Returns:
            解析后的StoryModule

        Raises:
            ValueError: 如果无法解析模组内容
        """
        if not text.strip():
            raise ValueError("模组文本为空")

        # 对于较短文本，直接一次提取
        if len(text) <= _MAX_CHUNK_CHARS:
            return await self._extract_single(text, filename)

        # 超长文本：分块提取后合并
        return await self._extract_chunked(text, filename)

    async def _extract_single(self, text: str, filename: str = "") -> StoryModule:
        """单次提取：将完整文本交给Claude解析"""
        file_hint = f"（文件名：{filename}）" if filename else ""
        user_msg = (
            f"请从以下CoC模组文档中提取结构化信息{file_hint}：\n\n"
            f"---\n{text}\n---\n\n"
            f"请以JSON格式输出完整模组数据。"
        )
        messages = [{"role": "user", "content": user_msg}]
        response_text, _usage = await self.agent.invoke(messages=messages, temperature=0.3)
        data = _extract_json(response_text)
        return _dict_to_module(data)

    async def _extract_chunked(self, text: str, filename: str = "") -> StoryModule:
        """分块提取：先分段提取，再合并为完整模组

        对于超长模组文档，分成多个块分别提取，最后合并。
        """
        # 按段落分块，尽量保持语义完整
        chunks = self._split_text(text)
        all_npcs: list[dict] = []
        all_locations: list[dict] = []
        all_scenes: list[dict] = []
        all_clues: list[dict] = []
        all_timeline: list[dict] = []
        metadata: dict = {}

        for i, chunk in enumerate(chunks):
            file_hint = f"（文件名：{filename}）" if filename else ""
            user_msg = (
                f"这是一份CoC模组文档的第{i + 1}/{len(chunks)}部分{file_hint}。\n"
                f"请从中提取所有能识别的结构化信息：\n\n"
                f"---\n{chunk}\n---\n\n"
                f"请以JSON格式输出。如果该部分没有某类信息，对应列表返回空数组即可。"
            )
            messages = [{"role": "user", "content": user_msg}]
            response_text, _usage = await self.agent.invoke(messages=messages, temperature=0.3)

            try:
                data = _extract_json(response_text)
            except (json.JSONDecodeError, ValueError):
                # 某一块解析失败时跳过，不中断整体流程
                continue

            # 第一个有效metadata作为基准
            if not metadata and data.get("metadata"):
                metadata = data["metadata"]

            all_npcs.extend(data.get("npcs", []))
            all_locations.extend(data.get("locations", []))
            all_scenes.extend(data.get("scenes", []))
            all_clues.extend(data.get("clues", []))
            all_timeline.extend(data.get("timeline", []))

        # 去重（按id）
        def _dedup(items: list[dict]) -> list[dict]:
            seen: set[str] = set()
            result = []
            for item in items:
                item_id = item.get("id", "")
                if item_id and item_id in seen:
                    continue
                if item_id:
                    seen.add(item_id)
                result.append(item)
            return result

        merged = {
            "metadata": metadata or {"title": filename or "未命名模组"},
            "npcs": _dedup(all_npcs),
            "locations": _dedup(all_locations),
            "scenes": _dedup(all_scenes),
            "clues": _dedup(all_clues),
            "timeline": _dedup(all_timeline),
        }

        return _dict_to_module(merged)

    @staticmethod
    def _split_text(text: str) -> list[str]:
        """将长文本按段落边界分块

        尽量在双换行处分割，保持每块不超过阈值。
        """
        paragraphs = re.split(r"\n{2,}", text)
        chunks: list[str] = []
        current_chunk = ""

        for para in paragraphs:
            if len(current_chunk) + len(para) + 2 > _MAX_CHUNK_CHARS:
                if current_chunk:
                    chunks.append(current_chunk)
                # 如果单个段落就超过阈值，强制切割
                if len(para) > _MAX_CHUNK_CHARS:
                    for j in range(0, len(para), _MAX_CHUNK_CHARS):
                        chunks.append(para[j : j + _MAX_CHUNK_CHARS])
                    current_chunk = ""
                else:
                    current_chunk = para
            else:
                current_chunk = current_chunk + "\n\n" + para if current_chunk else para

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    async def load_from_file(self, file_path: str) -> StoryModule:
        """从文件导入模组

        支持 .txt 和 .md 文件。

        Args:
            file_path: 模组文件路径

        Returns:
            解析后的StoryModule

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 不支持的文件格式或无法解析
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在：{file_path}")

        if path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"不支持的文件格式：{path.suffix}。"
                f"目前支持：{', '.join(sorted(_SUPPORTED_EXTENSIONS))}"
            )

        # 尝试多种编码读取
        text = None
        for encoding in ("utf-8", "utf-8-sig", "gbk", "gb2312", "big5"):
            try:
                text = path.read_text(encoding=encoding)
                break
            except (UnicodeDecodeError, LookupError):
                continue

        if text is None:
            raise ValueError(f"无法读取文件，请确认文件编码：{file_path}")

        return await self.load_from_text(text, filename=path.name)

    def _parse_module_json(self, json_text: str) -> StoryModule:
        """解析JSON字符串为StoryModule

        Args:
            json_text: JSON格式的模组数据

        Returns:
            StoryModule实例
        """
        data = _extract_json(json_text)
        return _dict_to_module(data)


def get_sample_modules_dir() -> Path:
    """获取内置示例模组目录"""
    return Path(__file__).parent / "samples"
