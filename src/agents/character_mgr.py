"""角色管理Agent

处理角色创建引导、属性查询、状态追踪。
大部分操作是纯Python，仅在需要叙事包装时调用LLM。
"""

from __future__ import annotations

import json
import random
import re
import uuid
from typing import Optional

from .base import BaseAgent
from ..config import get_settings
from ..middleware.token_tracker import TokenTracker
from ..models.character import (
    Investigator,
    Characteristics,
    DerivedStats,
    SkillValue,
    Era,
    Gender,
    InventoryItem,
    CombatStatus,
)
from ..rules.character_creation import (
    roll_characteristics,
    apply_age_modifiers,
    roll_luck,
    generate_investigator_stats,
)
from ..rules.skill_list import COC_7E_SKILLS, OCCUPATIONS, get_skills_for_era

CHARACTER_MGR_SYSTEM_PROMPT = """你是克苏鲁的呼唤第7版的角色管理助手。

你的职责是协助玩家创建和管理调查员角色。

# 规则
- 引导玩家完成角色创建流程
- 解释属性和技能的含义
- 提供角色背景建议（符合1920年代设定）
- 使用中文
"""

# 技能点公式无法用简单乘法表达时，需要解析公式字符串
# 支持格式：EDU×4, EDU×2+DEX×2, EDU×2+APP×2 等
_ATTR_MAP = {
    "EDU": "EDU",
    "DEX": "DEX",
    "APP": "APP",
    "INT": "INT",
    "STR": "STR",
    "CON": "CON",
    "POW": "POW",
    "SIZ": "SIZ",
}


def _parse_skill_points_formula(formula: str, chars: Characteristics) -> int:
    """解析职业技能点公式

    支持格式：
    - "EDU×4"
    - "EDU×2+DEX×2"
    - "EDU×2+APP×2"

    Returns:
        计算出的技能点总数
    """
    total = 0
    # 将中文乘号统一为 *（不替换字母x/X，避免破坏属性名如DEX）
    formula = formula.replace("×", "*")
    # 按 + 分割各项
    parts = formula.split("+")
    for part in parts:
        part = part.strip()
        if "*" in part:
            attr_name, multiplier_str = part.split("*", 1)
            attr_name = attr_name.strip().upper()
            multiplier = int(multiplier_str.strip())
            attr_value = getattr(chars, attr_name, 0)
            total += attr_value * multiplier
        else:
            # 纯数字
            total += int(part.strip())
    return total


# 不可在角色创建时分配点数的技能
_EXCLUDED_SKILLS = {"克苏鲁神话"}

# AI 背景建议 JSON 键（须与前端 character_create 表单一致）
_BG_SUGGEST_KEYS = (
    "personal_description",
    "ideology",
    "significant_people",
    "meaningful_locations",
    "treasured_possessions",
    "traits",
)


def _extract_json_object(text: str) -> dict:
    """从模型输出中解析 JSON 对象（容忍 ```json 围栏或前后说明文字）。"""
    s = text.strip()
    fence = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", s, re.DOTALL | re.IGNORECASE)
    if fence:
        s = fence.group(1).strip()
    if not s.startswith("{"):
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end != -1 and end > start:
            s = s[start : end + 1]
    return json.loads(s)

# "任一"占位符 — 自动分配时从通用技能池中选取
_WILDCARD = "任一"


class CharacterManagerAgent(BaseAgent):
    def __init__(
        self,
        token_tracker: Optional[TokenTracker] = None,
        model: Optional[str] = None,
    ):
        super().__init__(
            name="角色管理",
            system_prompt=CHARACTER_MGR_SYSTEM_PROMPT,
            token_tracker=token_tracker,
            model=model,
            max_tokens=get_settings().agents.character_mgr,
        )

    # ------------------------------------------------------------------
    # 纯Python：角色创建
    # ------------------------------------------------------------------

    def create_investigator(
        self,
        player_id: str,
        name: str,
        age: int = 30,
        gender: Gender = Gender.MALE,
        occupation: str = "私家侦探",
        era: Era = Era.CLASSIC_1920S,
        rng: Optional[random.Random] = None,
    ) -> Investigator:
        """创建调查员（纯Python，不调用LLM）

        流程：
        1. 掷属性（含年龄修正和教育增强）
        2. 计算衍生属性
        3. 初始化技能基础值
        4. 分配职业技能点
        5. 分配兴趣技能点

        Args:
            player_id: 玩家ID
            name: 角色名字
            age: 年龄（15-89）
            gender: 性别
            occupation: 职业名称（需在OCCUPATIONS中）
            era: 游戏时代
            rng: 随机数生成器（用于测试）

        Returns:
            完整的Investigator对象
        """
        if rng is None:
            rng = random.Random()

        # 1. 生成属性（含年龄修正、教育增强、幸运值）
        chars, luck, _notes = generate_investigator_stats(age=age, rng=rng)

        # 2. 计算衍生属性
        derived = DerivedStats.from_characteristics(chars, luck)

        # 3. 初始化全部技能的基础值
        era_skills = get_skills_for_era(era.value)
        skills: dict[str, SkillValue] = {}
        for skill_name, base_val in era_skills.items():
            # 特殊技能：闪避基础值 = DEX/2
            if skill_name == "闪避":
                actual_base = chars.DEX // 2
            # 特殊技能：母语基础值 = EDU
            elif skill_name == "母语":
                actual_base = chars.EDU
            else:
                actual_base = base_val
            skills[skill_name] = SkillValue(
                base=actual_base, current=actual_base
            )

        # 4. 分配职业技能点
        self._assign_occupation_skills(skills, chars, occupation, era, rng)

        # 5. 分配兴趣技能点（INT × 2）
        self._assign_interest_skills(skills, chars, era, rng)

        # 6. 构建Investigator对象
        inv = Investigator(
            id=str(uuid.uuid4()),
            player_id=player_id,
            name=name,
            age=age,
            gender=gender,
            occupation=occupation,
            era=era,
            characteristics=chars,
            derived=derived,
            skills=skills,
        )
        return inv

    def _assign_occupation_skills(
        self,
        skills: dict[str, SkillValue],
        chars: Characteristics,
        occupation: str,
        era: Era,
        rng: random.Random,
    ) -> None:
        """自动分配职业技能点

        策略：
        - 从OCCUPATIONS获取职业技能列表和技能点公式
        - 解析"任一"占位符，从可用技能池中随机选取
        - 过滤掉含"其他语言"或"任一"等需要替换的技能名称
        - 将总点数均匀分散到职业技能中
        - 每个技能最高不超过90
        """
        occ_data = OCCUPATIONS.get(occupation)
        if occ_data is None:
            # 未知职业：默认使用 EDU×2 作为技能点，选8个通用技能
            total_points = chars.EDU * 2
            occ_skill_names = self._pick_random_skills(
                skills, count=8, rng=rng, era=era
            )
        else:
            # 解析技能点公式
            formula = occ_data.get("skill_points", "EDU×4")
            total_points = _parse_skill_points_formula(formula, chars)

            # 解析技能列表，替换占位符
            raw_skills = occ_data.get("skills", [])
            occ_skill_names = self._resolve_skill_names(
                raw_skills, skills, rng, era
            )

        # 将点数均匀分散到职业技能中
        self._distribute_points(skills, occ_skill_names, total_points)

    def _assign_interest_skills(
        self,
        skills: dict[str, SkillValue],
        chars: Characteristics,
        era: Era,
        rng: random.Random,
    ) -> None:
        """自动分配兴趣技能点

        策略：
        - 兴趣技能点 = INT × 2
        - 从非职业技能（current == base 的技能）中随机选取若干
        - 将点数均匀分散
        """
        total_points = chars.INT * 2

        # 选择还没有被加过点的技能（即 current == base）
        candidates = [
            name for name, sv in skills.items()
            if sv.current == sv.base and name not in _EXCLUDED_SKILLS
        ]
        if not candidates:
            # 所有技能都已被分配过，则从非排除技能中随机选
            candidates = [
                name for name in skills if name not in _EXCLUDED_SKILLS
            ]

        # 选取最多8个兴趣技能
        count = min(8, len(candidates))
        chosen = rng.sample(candidates, count) if len(candidates) >= count else list(candidates)

        self._distribute_points(skills, chosen, total_points)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _resolve_skill_names(
        self,
        raw_skills: list[str],
        skills: dict[str, SkillValue],
        rng: random.Random,
        era: Era,
    ) -> list[str]:
        """将职业技能列表中的占位符解析为具体技能名

        处理以下情况：
        - "任一"：从全技能池中随机选取
        - "其他语言（任一）"：保留为固定技能名（如果存在）或随机选取
        - "艺术/手艺（任一）"：从艺术/手艺类技能中随机选取
        - 精确技能名：直接使用
        """
        resolved: list[str] = []
        used: set[str] = set()  # 避免重复选取

        for raw in raw_skills:
            if raw == _WILDCARD:
                # 从全技能池中随机选一个未被选过的
                picked = self._pick_one_skill(skills, used, rng, era)
                if picked:
                    resolved.append(picked)
                    used.add(picked)
            elif "任一" in raw and raw != _WILDCARD:
                # 如 "艺术/手艺（任一）" → 从艺术/手艺类中选
                prefix = raw.split("（")[0]
                matching = [
                    name for name in skills
                    if name.startswith(prefix)
                    and name not in used
                    and name not in _EXCLUDED_SKILLS
                ]
                if matching:
                    picked = rng.choice(matching)
                    resolved.append(picked)
                    used.add(picked)
                else:
                    # 找不到匹配的，随机选一个
                    picked = self._pick_one_skill(skills, used, rng, era)
                    if picked:
                        resolved.append(picked)
                        used.add(picked)
            elif raw.startswith("其他语言"):
                # "其他语言（拉丁语）"等 — 在技能表中可能不存在
                # 跳过，改为随机选一个替代技能
                picked = self._pick_one_skill(skills, used, rng, era)
                if picked:
                    resolved.append(picked)
                    used.add(picked)
            else:
                # 精确技能名
                if raw in skills and raw not in _EXCLUDED_SKILLS:
                    resolved.append(raw)
                    used.add(raw)
                else:
                    # 技能名不在列表中，随机替换
                    picked = self._pick_one_skill(skills, used, rng, era)
                    if picked:
                        resolved.append(picked)
                        used.add(picked)

        return resolved

    def _pick_one_skill(
        self,
        skills: dict[str, SkillValue],
        exclude: set[str],
        rng: random.Random,
        era: Era,
    ) -> Optional[str]:
        """从技能池中随机选取一个未被使用的技能"""
        candidates = [
            name for name in skills
            if name not in exclude and name not in _EXCLUDED_SKILLS
        ]
        if not candidates:
            return None
        return rng.choice(candidates)

    def _pick_random_skills(
        self,
        skills: dict[str, SkillValue],
        count: int,
        rng: random.Random,
        era: Era,
    ) -> list[str]:
        """从技能池中随机选取 count 个技能"""
        candidates = [
            name for name in skills if name not in _EXCLUDED_SKILLS
        ]
        actual_count = min(count, len(candidates))
        return rng.sample(candidates, actual_count)

    @staticmethod
    def _distribute_points(
        skills: dict[str, SkillValue],
        target_skills: list[str],
        total_points: int,
    ) -> None:
        """将点数均匀分散到指定技能中

        策略：轮流给每个技能加点，每轮每个技能加一定量，
        直到点数用完或所有技能达到上限（90）。

        Args:
            skills: 技能字典（会被就地修改）
            target_skills: 要分配的技能名列表
            total_points: 总点数
        """
        if not target_skills or total_points <= 0:
            return

        max_skill_value = 90
        remaining = total_points

        # 计算每个技能的平均分配量
        per_skill = remaining // len(target_skills)
        # 限制每个技能单次分配不超过上限允许的量
        # 先做一轮均匀分配
        leftover = remaining
        for skill_name in target_skills:
            if skill_name not in skills:
                continue
            sv = skills[skill_name]
            room = max_skill_value - sv.current
            add = min(per_skill, room)
            if add > 0:
                skills[skill_name] = SkillValue(
                    base=sv.base,
                    current=sv.current + add,
                    experience_check=sv.experience_check,
                )
                leftover -= add

        # 把剩余的点数继续分配（有些技能可能已满）
        # 循环分配直到点数用完或无法再分配
        while leftover > 0:
            distributed_any = False
            for skill_name in target_skills:
                if leftover <= 0:
                    break
                if skill_name not in skills:
                    continue
                sv = skills[skill_name]
                room = max_skill_value - sv.current
                if room > 0:
                    add = min(leftover, min(5, room))  # 每轮每技能最多加5
                    skills[skill_name] = SkillValue(
                        base=sv.base,
                        current=sv.current + add,
                        experience_check=sv.experience_check,
                    )
                    leftover -= add
                    distributed_any = True
            if not distributed_any:
                break  # 所有技能都到上限了，剩余点数浪费

    # ------------------------------------------------------------------
    # LLM辅助：背景建议
    # ------------------------------------------------------------------

    async def suggest_background(self, inv: Investigator) -> dict[str, str]:
        """用 LLM 生成角色背景建议（六栏结构化，与角色卡表单字段一致）。"""
        top_skills = sorted(
            [
                (name, sv.current)
                for name, sv in inv.skills.items()
                if sv.current > sv.base
            ],
            key=lambda x: x[1],
            reverse=True,
        )[:5]
        skill_desc = "、".join(
            f"{name}({val})" for name, val in top_skills
        ) if top_skills else "无突出技能"

        keys_line = ", ".join(_BG_SUGGEST_KEYS)
        prompt = (
            f"请为以下克苏鲁的呼唤调查员填写背景栏位建议。时代：{inv.era.value}。\n\n"
            f"姓名：{inv.name}\n"
            f"年龄：{inv.age}岁\n"
            f"性别：{inv.gender.value}\n"
            f"职业：{inv.occupation}\n"
            f"出生地/居住地：{inv.birthplace or '未填'} / {inv.residence or '未填'}\n"
            f"主要属性：STR {inv.characteristics.STR}，CON {inv.characteristics.CON}，"
            f"SIZ {inv.characteristics.SIZ}，DEX {inv.characteristics.DEX}，"
            f"APP {inv.characteristics.APP}，INT {inv.characteristics.INT}，"
            f"POW {inv.characteristics.POW}，EDU {inv.characteristics.EDU}\n"
            f"突出技能：{skill_desc}\n\n"
            "请只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释。"
            f"键必须恰好为（英文）：{keys_line}。"
            "各值为中文，对应角色卡：外貌与风格、思想信念、重要之人、意义非凡之地、珍视之物、性格特质。"
            "内容简洁，每栏约 1～3 句。"
        )

        messages = [{"role": "user", "content": prompt}]
        text, _usage = await self.invoke(messages, temperature=0.9)
        empty = {k: "" for k in _BG_SUGGEST_KEYS}
        try:
            raw = _extract_json_object(text.strip())
        except (json.JSONDecodeError, ValueError, TypeError):
            empty["personal_description"] = text.strip()
            return empty
        if not isinstance(raw, dict):
            empty["personal_description"] = text.strip()
            return empty
        return {k: str(raw.get(k) or "").strip() for k in _BG_SUGGEST_KEYS}
