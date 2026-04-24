"""CoC 7版技能列表

所有技能及其基础值。包括1920s时代、现代时代和煤气灯时代的差异。
支持自定义技能和模组调整。
"""

from __future__ import annotations

# ============================================================
# CoC 7版标准技能列表：{技能名: 基础值}
# 基础值代表未经训练时的默认百分比值
# ============================================================

COC_7E_SKILLS: dict[str, int] = {
    # 战斗技能
    "闪避": 0,               # 基础值 = DEX/2，创建角色时计算
    "格斗（斗殴）": 25,
    "格斗（剑）": 20,
    "格斗（斧）": 15,
    "格斗（矛）": 20,
    "格斗（链枷）": 10,
    "格斗（鞭）": 5,
    "射击（手枪）": 20,
    "射击（步枪/霰弹枪）": 25,
    "射击（冲锋枪）": 15,
    "射击（弓）": 15,
    "投掷": 20,

    # 调查技能
    "会计": 5,
    "人类学": 1,
    "估价": 5,
    "考古学": 1,
    "图书馆使用": 20,
    "博物学": 10,
    "导航": 10,
    "侦查": 25,
    "聆听": 20,
    "追踪": 10,

    # 社交技能
    "魅惑": 15,
    "话术": 5,
    "恐吓": 15,
    "说服": 10,
    "心理学": 10,

    # 知识技能
    "克苏鲁神话": 0,         # 不可在角色创建时分配
    "历史": 5,
    "法律": 5,
    "医学": 1,
    "神秘学": 5,
    "科学（天文学）": 1,
    "科学（生物学）": 1,
    "科学（化学）": 1,
    "科学（密码学）": 1,
    "科学（地质学）": 1,
    "科学（数学）": 10,
    "科学（气象学）": 1,
    "科学（药学）": 1,
    "科学（物理学）": 1,
    "科学（动物学）": 1,

    # 身体技能
    "攀爬": 20,
    "游泳": 20,
    "跳跃": 20,
    "潜行": 20,
    "驾驶（汽车）": 20,
    "骑术": 5,
    "操纵重型机械": 1,

    # 艺术/工艺技能
    "艺术/手艺（摄影）": 5,
    "艺术/手艺（绘画）": 5,
    "艺术/手艺（写作）": 5,
    "艺术/手艺（雕塑）": 5,
    "艺术/手艺（烹饪）": 5,
    "艺术/手艺（表演）": 5,

    # 其他技能
    "乔装": 5,
    "电气维修": 10,
    "急救": 30,
    "催眠": 1,
    "锁匠": 1,
    "机械维修": 10,
    "精神分析": 1,
    "妙手": 10,
    "生存（沙漠）": 10,
    "生存（海洋）": 10,
    "生存（极地）": 10,
    "生存（山地）": 10,
    "潜水": 1,
    "动物驯养": 5,
    "信用评级": 0,            # 特殊：从职业技能点中分配，需在职业信用范围内

    # 语言技能（基础值为EDU，具体在角色创建时设定）
    "母语": 0,               # 基础值 = EDU，创建时计算
    "外语（英语）": 1,
    "外语（法语）": 1,
    "外语（德语）": 1,
    "外语（拉丁语）": 1,
    "外语（希腊语）": 1,
    "外语（阿拉伯语）": 1,
    "外语（日语）": 1,
    "外语（中文）": 1,
    "外语（西班牙语）": 1,
    "外语（俄语）": 1,
}

# ============================================================
# 时代特有技能
# ============================================================

# 1920s特有技能
SKILLS_1920S: dict[str, int] = {
    "驾驶（马车）": 20,
    "飞行（飞行器）": 1,
}

# 现代特有技能
SKILLS_MODERN: dict[str, int] = {
    "计算机使用": 5,
    "电子学": 1,
    "驾驶（飞机）": 1,
}

# 煤气灯时代（维多利亚时代）特有技能
SKILLS_GASLIGHT: dict[str, int] = {
    "驾驶（马车）": 20,
}

# 煤气灯时代技能基础值覆盖（高于通用表的值）
SKILLS_GASLIGHT_OVERRIDES: dict[str, int] = {
    "骑术": 15,              # 维多利亚时代骑术更普遍，基础值提高
}

# 各时代需排除的技能
SKILLS_EXCLUDE_1920S: set[str] = {
    "计算机使用",
    "电子学",
    "驾驶（飞机）",
}

SKILLS_EXCLUDE_MODERN: set[str] = {
    "驾驶（马车）",
    "飞行（飞行器）",
}

SKILLS_EXCLUDE_GASLIGHT: set[str] = {
    "计算机使用",
    "电子学",
    "驾驶（飞机）",
    "射击（冲锋枪）",        # 冲锋枪尚未发明
}

# ============================================================
# 技能分类映射
# ============================================================

SKILL_CATEGORIES: dict[str, list[str]] = {
    "战斗技能": [
        "闪避", "格斗（斗殴）", "格斗（剑）", "格斗（斧）",
        "格斗（矛）", "格斗（链枷）", "格斗（鞭）",
        "射击（手枪）", "射击（步枪/霰弹枪）", "射击（冲锋枪）",
        "射击（弓）", "投掷",
    ],
    "调查技能": [
        "侦查", "聆听", "图书馆使用", "会计", "人类学",
        "估价", "考古学", "博物学", "导航", "追踪",
    ],
    "社交技能": [
        "魅惑", "话术", "恐吓", "说服", "心理学",
    ],
    "知识技能": [
        "克苏鲁神话", "历史", "法律", "医学", "神秘学",
    ],
    "身体技能": [
        "攀爬", "游泳", "跳跃", "潜行", "骑术",
        "驾驶（汽车）", "驾驶（马车）", "操纵重型机械",
    ],
    "科学技能": [
        "科学（天文学）", "科学（生物学）", "科学（化学）",
        "科学（密码学）", "科学（地质学）", "科学（数学）",
        "科学（气象学）", "科学（药学）", "科学（物理学）",
        "科学（动物学）",
    ],
    "艺术/手艺": [
        "艺术/手艺（摄影）", "艺术/手艺（绘画）", "艺术/手艺（写作）",
        "艺术/手艺（雕塑）", "艺术/手艺（烹饪）", "艺术/手艺（表演）",
    ],
    "语言": [
        "母语",
        "外语（英语）", "外语（法语）", "外语（德语）",
        "外语（拉丁语）", "外语（希腊语）", "外语（阿拉伯语）",
        "外语（日语）", "外语（中文）", "外语（西班牙语）", "外语（俄语）",
    ],
    "其他": [
        "乔装", "电气维修", "急救", "催眠", "锁匠",
        "机械维修", "精神分析", "妙手", "潜水", "动物驯养",
        "信用评级",
        "生存（沙漠）", "生存（海洋）", "生存（极地）", "生存（山地）",
        "计算机使用", "电子学", "飞行（飞行器）", "驾驶（飞机）",
    ],
}


# ============================================================
# 时代技能获取
# ============================================================

def get_skills_for_era(era: str = "1920s") -> dict[str, int]:
    """获取指定时代的完整技能列表

    Args:
        era: 时代标识。支持 "1920s" / "现代" / "modern" / "煤气灯" / "gaslight"

    Returns:
        该时代可用技能及其基础值的字典
    """
    skills = dict(COC_7E_SKILLS)

    if era == "1920s":
        # 添加1920s特有技能，排除现代技能
        skills.update(SKILLS_1920S)
        for name in SKILLS_EXCLUDE_1920S:
            skills.pop(name, None)

    elif era in ("现代", "modern"):
        # 添加现代特有技能，排除古典技能
        skills.update(SKILLS_MODERN)
        for name in SKILLS_EXCLUDE_MODERN:
            skills.pop(name, None)

    elif era in ("煤气灯", "gaslight"):
        # 维多利亚时代：添加特有技能，应用基础值覆盖，排除不适用技能
        skills.update(SKILLS_GASLIGHT)
        skills.update(SKILLS_GASLIGHT_OVERRIDES)
        for name in SKILLS_EXCLUDE_GASLIGHT:
            skills.pop(name, None)

    return skills


def get_skill_base(skill_name: str, era: str = "1920s") -> int:
    """获取技能的基础值"""
    skills = get_skills_for_era(era)
    return skills.get(skill_name, 1)


# ============================================================
# 自定义技能支持
# ============================================================

def add_custom_skill(skills: dict[str, int], name: str, base_value: int = 1) -> None:
    """添加自定义技能（模组可能引入的特殊技能）

    Args:
        skills: 技能字典（会被原地修改）
        name: 技能名称
        base_value: 基础值，默认1
    """
    skills[name] = base_value


def remove_skill(skills: dict[str, int], name: str) -> None:
    """移除不适用的技能

    Args:
        skills: 技能字典（会被原地修改）
        name: 要移除的技能名称

    Raises:
        KeyError: 技能不存在时抛出
    """
    if name not in skills:
        raise KeyError(f"技能 '{name}' 不存在于技能列表中")
    del skills[name]


# ============================================================
# 技能名解析：LLM 可能生成白名单外或带错字的技能名，
# resolve_skill() 将其映射到 investigator 的实际技能或属性。
# 绝对不会 fallback 到 value=1——要么模糊匹配，要么归到属性检定。
# ============================================================

# 属性检定（CoC 7e 中的「灵感=智力」、「幸运=幸运值」等）
# 键 = LLM 可能写出的名字，值 = 使用的 investigator 属性字段名
_ATTRIBUTE_CHECK_ALIASES: dict[str, str] = {
    "灵感": "INT",
    "智力": "INT",
    "知识": "EDU",
    "教育": "EDU",
    "意志": "POW",
    "力量": "STR",
    "敏捷": "DEX",
    "体质": "CON",
    "体型": "SIZ",
    "外貌": "APP",
    "幸运": "__LUCK__",
}

# 具象技能的常见别名/错写 → 标准 CoC 7e 技能
_SKILL_NAME_ALIASES: dict[str, str] = {
    "聆听或观察": "聆听",
    "观察": "侦查",
    "查看": "侦查",
    "搜查": "侦查",
    "搜索": "侦查",
    "查找": "侦查",
    "察言观色": "心理学",
    "读心": "心理学",
    "聆听声音": "聆听",
    "偷听": "聆听",
    "追查": "追踪",
    "翻查": "图书馆使用",
    "阅读": "图书馆使用",
    "研究": "图书馆使用",
    "急救术": "急救",
    "医术": "医学",
    "锁匠": "锁匠技术",
    "开锁": "锁匠技术",
}


def _normalize_skill_name(name: str) -> str:
    """去掉空白、把全角括号转半角，便于匹配。"""
    return (
        name.replace("（", "(")
        .replace("）", ")")
        .replace(" ", "")
        .replace("\u3000", "")
        .strip()
    )


def resolve_skill(requested: str, investigator) -> tuple[str, int]:
    """把 LLM 请求的技能名解析为 (规范名, 当前值)。

    解析顺序：
    1. 属性检定别名（灵感→INT、幸运→LUCK 等）
    2. 精确匹配 investigator 已有技能
    3. 规范化括号后再匹配
    4. 技能名别名表
    5. 专攻家族回退（射击/格斗/艺术/科学/语言 系列取最高）
    6. 子串模糊匹配
    7. CoC 7e 白名单基础值
    8. 最终兜底：按「灵感」规则用 INT（远好于 value=1）

    Args:
        requested: LLM 给出的技能名
        investigator: Investigator 对象

    Returns:
        (display_name, current_value)
    """
    req = (requested or "").strip()
    if not req:
        return ("灵感", investigator.characteristics.INT)

    chars = investigator.characteristics
    derived = investigator.derived

    # 1. 属性检定
    if req in _ATTRIBUTE_CHECK_ALIASES:
        attr = _ATTRIBUTE_CHECK_ALIASES[req]
        if attr == "__LUCK__":
            return (req, getattr(derived, "luck", 50))
        return (req, getattr(chars, attr))

    # 2. 精确匹配
    sk = investigator.skills.get(req)
    if sk is not None:
        return (req, sk.current)

    # 3. 括号规范化
    req_norm = _normalize_skill_name(req)
    for name, val in investigator.skills.items():
        if _normalize_skill_name(name) == req_norm:
            return (name, val.current)

    # 4. 别名表
    if req in _SKILL_NAME_ALIASES:
        alt = _SKILL_NAME_ALIASES[req]
        alt_sk = investigator.skills.get(alt)
        if alt_sk is not None:
            return (alt, alt_sk.current)
        return (alt, COC_7E_SKILLS.get(alt, 10))

    # 5. 专攻家族回退（射击（手枪）/格斗（斗殴）/艺术（摄影）等）
    _families = ("射击", "格斗", "艺术", "手艺", "科学", "语言", "驾驶", "操作重型机械")
    for fam in _families:
        if req.startswith(fam):
            candidates = [
                (n, v.current)
                for n, v in investigator.skills.items()
                if n.startswith(fam)
            ]
            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                return candidates[0]

    # 6. 子串模糊匹配
    for name, val in investigator.skills.items():
        if not name:
            continue
        if name in req or req in name:
            return (name, val.current)

    # 7. CoC 白名单基础值
    if req in COC_7E_SKILLS:
        return (req, COC_7E_SKILLS[req])
    # 括号规范化再查一次白名单
    for wl_name, wl_val in COC_7E_SKILLS.items():
        if _normalize_skill_name(wl_name) == req_norm:
            return (wl_name, wl_val)

    # 8. 兜底：灵感（INT）——比永远失败的 value=1 合理得多
    return (f"{req}（按灵感/智力处理）", chars.INT)


def get_module_adjusted_skills(
    era: str,
    extra_skills: dict[str, int] | None = None,
    remove_skills: list[str] | None = None,
) -> dict[str, int]:
    """获取经模组调整后的技能列表

    先获取对应时代的基础技能列表，再应用模组的增删调整。

    Args:
        era: 时代
        extra_skills: 模组额外添加的技能 {名称: 基础值}
        remove_skills: 模组要移除的技能名列表

    Returns:
        调整后的技能字典
    """
    skills = get_skills_for_era(era)

    if remove_skills:
        for name in remove_skills:
            skills.pop(name, None)

    if extra_skills:
        skills.update(extra_skills)

    return skills


# ============================================================
# 职业与职业技能的映射
# 数据来源：克苏鲁的呼唤第七版调查员手册
#
# 每个职业包含：
#   credit_rating: (最低, 最高) 信用评级范围
#   skills: 本职技能列表（"任一"表示自选，"社交技能（任一）"等表示分类自选）
#   skill_points: 职业技能点计算公式
#   skill_points_alt: 可选的替代公式（如 EDU×2+STR×2 或 EDU×2+DEX×2）
#   tags: 标签（"古典"=1920s特色, "现代"=现代特色, "原作向"=洛夫克拉夫特作品常见）
# ============================================================

OCCUPATIONS: dict[str, dict] = {
    # === 原作向 & 经典职业 ===
    "古文物学家": {
        "credit_rating": (30, 70),
        "skills": ["估价", "艺术/手艺（任一）", "历史", "图书馆使用",
                    "外语（任一）", "社交技能（任一）", "侦查", "任一"],
        "skill_points": "EDU×4",
        "tags": ["原作向"],
    },
    "考古学家": {
        "credit_rating": (10, 40),
        "skills": ["估价", "考古学", "历史", "外语（任一）",
                    "图书馆使用", "侦查", "机械维修", "导航"],
        "skill_points": "EDU×4",
        "tags": ["原作向"],
    },
    "作家": {
        "credit_rating": (9, 30),
        "skills": ["艺术/手艺（写作）", "历史", "图书馆使用", "博物学",
                    "神秘学", "外语（任一）", "母语", "任一"],
        "skill_points": "EDU×4",
        "tags": ["原作向"],
    },
    "医生": {
        "credit_rating": (30, 80),
        "skills": ["急救", "医学", "外语（拉丁语）", "心理学",
                    "科学（生物学）", "科学（药学）", "任一", "任一"],
        "skill_points": "EDU×4",
        "tags": ["原作向"],
    },
    "私家侦探": {
        "credit_rating": (9, 30),
        "skills": ["艺术/手艺（摄影）", "乔装", "法律", "图书馆使用",
                    "社交技能（任一）", "心理学", "侦查", "任一"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },
    "记者": {
        "credit_rating": (9, 30),
        "skills": ["艺术/手艺（摄影）", "社交技能（任一）", "历史",
                    "图书馆使用", "母语", "心理学", "任一", "任一"],
        "skill_points": "EDU×4",
        "tags": ["原作向"],
    },
    "教授": {
        "credit_rating": (20, 70),
        "skills": ["图书馆使用", "外语（任一）", "母语", "心理学",
                    "任一", "任一", "任一", "任一"],
        "skill_points": "EDU×4",
        "tags": ["原作向"],
    },
    "神秘学家": {
        "credit_rating": (9, 65),
        "skills": ["人类学", "历史", "图书馆使用", "社交技能（任一）",
                    "神秘学", "外语（任一）", "科学（天文学）", "任一"],
        "skill_points": "EDU×4",
        "tags": ["原作向"],
    },
    "图书馆员": {
        "credit_rating": (9, 35),
        "skills": ["会计", "图书馆使用", "外语（任一）", "母语",
                    "任一", "任一", "任一", "任一"],
        "skill_points": "EDU×4",
        "tags": ["原作向"],
    },
    "警探": {
        "credit_rating": (20, 50),
        "skills": ["艺术/手艺（表演）", "射击（手枪）", "法律", "聆听",
                    "社交技能（任一）", "心理学", "侦查", "任一"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
        "tags": ["原作向"],
    },
    "巡警": {
        "credit_rating": (9, 30),
        "skills": ["格斗（斗殴）", "射击（手枪）", "急救", "社交技能（任一）",
                    "法律", "心理学", "侦查", "驾驶（汽车）"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
        "tags": ["原作向"],
    },

    # === 学术/专业 ===
    "会计师": {
        "credit_rating": (30, 70),
        "skills": ["会计", "法律", "图书馆使用", "聆听",
                    "说服", "侦查", "任一", "任一"],
        "skill_points": "EDU×4",
    },
    "建筑师": {
        "credit_rating": (30, 70),
        "skills": ["会计", "艺术/手艺（技术制图）", "法律", "母语",
                    "图书馆使用", "说服", "心理学", "科学（数学）"],
        "skill_points": "EDU×4",
    },
    "工程师": {
        "credit_rating": (30, 60),
        "skills": ["艺术/手艺（技术制图）", "电气维修", "图书馆使用",
                    "机械维修", "操纵重型机械", "科学（工程学）", "科学（物理学）", "任一"],
        "skill_points": "EDU×4",
    },
    "科学家": {
        "credit_rating": (9, 50),
        "skills": ["科学（任一）", "科学（任一）", "科学（任一）",
                    "图书馆使用", "外语（任一）", "母语", "社交技能（任一）", "侦查"],
        "skill_points": "EDU×4",
    },
    "研究员": {
        "credit_rating": (9, 30),
        "skills": ["历史", "图书馆使用", "社交技能（任一）", "外语（任一）",
                    "侦查", "任一", "任一", "任一"],
        "skill_points": "EDU×4",
    },
    "实验室助理": {
        "credit_rating": (10, 30),
        "skills": ["图书馆使用", "电气维修", "外语（任一）",
                    "科学（化学）", "科学（任一）", "科学（任一）", "侦查", "任一"],
        "skill_points": "EDU×4",
    },

    # === 医疗 ===
    "护士": {
        "credit_rating": (9, 30),
        "skills": ["急救", "聆听", "医学", "社交技能（任一）",
                    "心理学", "科学（生物学）", "科学（化学）", "侦查"],
        "skill_points": "EDU×4",
    },
    "精神病学家": {
        "credit_rating": (30, 80),
        "skills": ["外语（任一）", "聆听", "医学", "说服",
                    "精神分析", "心理学", "科学（生物学）", "科学（化学）"],
        "skill_points": "EDU×4",
    },
    "心理学家": {
        "credit_rating": (10, 40),
        "skills": ["会计", "图书馆使用", "聆听", "说服",
                    "精神分析", "心理学", "任一", "任一"],
        "skill_points": "EDU×4",
    },
    "药剂师": {
        "credit_rating": (35, 75),
        "skills": ["会计", "急救", "外语（拉丁语）", "图书馆使用",
                    "社交技能（任一）", "心理学", "科学（药学）", "科学（化学）"],
        "skill_points": "EDU×4",
    },
    "法医": {
        "credit_rating": (40, 60),
        "skills": ["外语（拉丁语）", "图书馆使用", "医学", "说服",
                    "科学（生物学）", "科学（司法科学）", "科学（药学）", "侦查"],
        "skill_points": "EDU×4",
    },

    # === 法律/政治 ===
    "律师": {
        "credit_rating": (30, 80),
        "skills": ["会计", "法律", "图书馆使用", "社交技能（任一）",
                    "社交技能（任一）", "心理学", "任一", "任一"],
        "skill_points": "EDU×4",
    },
    "法官": {
        "credit_rating": (50, 80),
        "skills": ["历史", "恐吓", "法律", "图书馆使用",
                    "聆听", "母语", "说服", "心理学"],
        "skill_points": "EDU×4",
    },
    "政治家": {
        "credit_rating": (50, 90),
        "skills": ["魅惑", "历史", "恐吓", "话术",
                    "聆听", "母语", "说服", "心理学"],
        "skill_points": "EDU×2+APP×2",
    },

    # === 宗教 ===
    "牧师": {
        "credit_rating": (9, 60),
        "skills": ["会计", "历史", "图书馆使用", "聆听",
                    "外语（任一）", "社交技能（任一）", "心理学", "任一"],
        "skill_points": "EDU×4",
    },
    "传教士": {
        "credit_rating": (0, 30),
        "skills": ["艺术/手艺（任一）", "急救", "机械维修", "医学",
                    "博物学", "社交技能（任一）", "任一", "任一"],
        "skill_points": "EDU×2+APP×2",
    },

    # === 军事/执法 ===
    "军官": {
        "credit_rating": (20, 70),
        "skills": ["会计", "射击（任一）", "导航", "急救",
                    "社交技能（任一）", "社交技能（任一）", "心理学", "任一"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },
    "士兵": {
        "credit_rating": (9, 30),
        "skills": ["攀爬", "闪避", "格斗（斗殴）", "射击（步枪/霰弹枪）",
                    "潜行", "生存（任一）", "任一", "任一"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },
    "联邦探员": {
        "credit_rating": (20, 40),
        "skills": ["驾驶（汽车）", "格斗（斗殴）", "射击（手枪）", "法律",
                    "说服", "潜行", "侦查", "任一"],
        "skill_points": "EDU×4",
    },
    "间谍": {
        "credit_rating": (20, 60),
        "skills": ["艺术/手艺（表演）", "射击（任一）", "聆听", "外语（任一）",
                    "社交技能（任一）", "心理学", "妙手", "潜行"],
        "skill_points": "EDU×2+APP×2",
        "skill_points_alt": "EDU×2+DEX×2",
    },
    "赏金猎人": {
        "credit_rating": (9, 30),
        "skills": ["驾驶（汽车）", "电气维修", "格斗（斗殴）", "社交技能（任一）",
                    "法律", "心理学", "追踪", "潜行"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },

    # === 犯罪 ===
    "窃贼": {
        "credit_rating": (5, 40),
        "skills": ["估价", "攀爬", "电气维修", "聆听",
                    "锁匠", "妙手", "潜行", "侦查"],
        "skill_points": "EDU×2+DEX×2",
    },
    "打手": {
        "credit_rating": (5, 30),
        "skills": ["驾驶（汽车）", "格斗（斗殴）", "射击（任一）", "社交技能（任一）",
                    "社交技能（任一）", "心理学", "潜行", "侦查"],
        "skill_points": "EDU×2+STR×2",
    },
    "欺诈师": {
        "credit_rating": (10, 65),
        "skills": ["估价", "艺术/手艺（表演）", "法律", "聆听",
                    "社交技能（任一）", "社交技能（任一）", "心理学", "妙手"],
        "skill_points": "EDU×2+APP×2",
    },
    "走私者": {
        "credit_rating": (20, 60),
        "skills": ["射击（任一）", "聆听", "导航", "社交技能（任一）",
                    "驾驶（汽车）", "心理学", "妙手", "侦查"],
        "skill_points": "EDU×2+APP×2",
        "skill_points_alt": "EDU×2+DEX×2",
    },
    "黑帮老大": {
        "credit_rating": (60, 95),
        "skills": ["格斗（斗殴）", "射击（手枪）", "法律", "聆听",
                    "社交技能（任一）", "社交技能（任一）", "心理学", "侦查"],
        "skill_points": "EDU×2+APP×2",
    },
    "混混": {
        "credit_rating": (3, 10),
        "skills": ["攀爬", "社交技能（任一）", "格斗（斗殴）", "射击（任一）",
                    "跳跃", "妙手", "潜行", "投掷"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },

    # === 艺术/表演 ===
    "演员": {
        "credit_rating": (9, 40),
        "skills": ["艺术/手艺（表演）", "乔装", "格斗（斗殴）", "历史",
                    "社交技能（任一）", "社交技能（任一）", "心理学", "任一"],
        "skill_points": "EDU×2+APP×2",
    },
    "音乐家": {
        "credit_rating": (9, 30),
        "skills": ["艺术/手艺（器乐）", "社交技能（任一）", "聆听", "心理学",
                    "任一", "任一", "任一", "任一"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+POW×2",
    },
    "艺术家": {
        "credit_rating": (9, 50),
        "skills": ["艺术/手艺（任一）", "历史", "社交技能（任一）", "外语（任一）",
                    "心理学", "侦查", "任一", "任一"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+POW×2",
    },
    "摄影师": {
        "credit_rating": (9, 30),
        "skills": ["艺术/手艺（摄影）", "社交技能（任一）", "心理学",
                    "科学（化学）", "潜行", "侦查", "任一", "任一"],
        "skill_points": "EDU×4",
    },
    "艺人": {
        "credit_rating": (9, 70),
        "skills": ["艺术/手艺（表演）", "乔装", "社交技能（任一）", "社交技能（任一）",
                    "聆听", "心理学", "任一", "任一"],
        "skill_points": "EDU×2+APP×2",
    },

    # === 商业 ===
    "古董商": {
        "credit_rating": (30, 50),
        "skills": ["会计", "估价", "驾驶（汽车）", "社交技能（任一）",
                    "社交技能（任一）", "历史", "图书馆使用", "导航"],
        "skill_points": "EDU×4",
    },
    "书商": {
        "credit_rating": (20, 40),
        "skills": ["会计", "估价", "驾驶（汽车）", "历史",
                    "图书馆使用", "母语", "外语（任一）", "社交技能（任一）"],
        "skill_points": "EDU×4",
    },
    "店老板": {
        "credit_rating": (20, 40),
        "skills": ["会计", "社交技能（任一）", "社交技能（任一）", "电气维修",
                    "聆听", "机械维修", "心理学", "侦查"],
        "skill_points": "EDU×2+APP×2",
        "skill_points_alt": "EDU×2+DEX×2",
    },
    "推销员": {
        "credit_rating": (9, 40),
        "skills": ["会计", "社交技能（任一）", "社交技能（任一）", "驾驶（汽车）",
                    "聆听", "心理学", "妙手", "任一"],
        "skill_points": "EDU×2+APP×2",
    },
    "酒保": {
        "credit_rating": (8, 25),
        "skills": ["会计", "社交技能（任一）", "社交技能（任一）", "格斗（斗殴）",
                    "聆听", "心理学", "侦查", "任一"],
        "skill_points": "EDU×2+APP×2",
    },

    # === 户外/体能 ===
    "运动员": {
        "credit_rating": (9, 70),
        "skills": ["攀爬", "跳跃", "格斗（斗殴）", "骑术",
                    "社交技能（任一）", "游泳", "投掷", "任一"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },
    "拳击手": {
        "credit_rating": (9, 60),
        "skills": ["闪避", "格斗（斗殴）", "恐吓", "跳跃",
                    "心理学", "侦查", "任一", "任一"],
        "skill_points": "EDU×2+STR×2",
    },
    "杂技演员": {
        "credit_rating": (9, 20),
        "skills": ["攀爬", "闪避", "跳跃", "投掷",
                    "侦查", "游泳", "任一", "任一"],
        "skill_points": "EDU×2+DEX×2",
    },
    "猎人": {
        "credit_rating": (20, 50),
        "skills": ["射击（步枪/霰弹枪）", "聆听", "博物学", "导航",
                    "外语（任一）", "科学（生物学）", "潜行", "追踪"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },
    "旅行家": {
        "credit_rating": (5, 20),
        "skills": ["射击（步枪/霰弹枪）", "急救", "聆听", "博物学",
                    "导航", "侦查", "生存（任一）", "追踪"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },
    "登山家": {
        "credit_rating": (30, 60),
        "skills": ["攀爬", "急救", "跳跃", "聆听",
                    "导航", "外语（任一）", "生存（任一）", "追踪"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },
    "探险家": {
        "credit_rating": (55, 80),
        "skills": ["攀爬", "射击（任一）", "历史", "跳跃",
                    "博物学", "导航", "外语（任一）", "生存（任一）"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
        "tags": ["古典"],
    },

    # === 交通/驾驶 ===
    "飞行员": {
        "credit_rating": (20, 70),
        "skills": ["电气维修", "机械维修", "导航", "操纵重型机械",
                    "驾驶（飞行器）", "科学（天文学）", "任一", "任一"],
        "skill_points": "EDU×2+DEX×2",
    },
    "海员": {
        "credit_rating": (9, 30),
        "skills": ["电气维修", "格斗（斗殴）", "射击（任一）", "急救",
                    "导航", "驾驶（船）", "生存（海洋）", "游泳"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },

    # === 服务/劳动 ===
    "农民": {
        "credit_rating": (9, 30),
        "skills": ["艺术/手艺（耕作）", "驾驶（汽车）", "社交技能（任一）", "机械维修",
                    "博物学", "操纵重型机械", "追踪", "任一"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },
    "工匠": {
        "credit_rating": (10, 40),
        "skills": ["会计", "艺术/手艺（任一）", "艺术/手艺（任一）", "机械维修",
                    "博物学", "侦查", "任一", "任一"],
        "skill_points": "EDU×2+DEX×2",
    },
    "消防员": {
        "credit_rating": (9, 30),
        "skills": ["攀爬", "闪避", "驾驶（汽车）", "急救",
                    "跳跃", "机械维修", "操纵重型机械", "投掷"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },
    "技师": {
        "credit_rating": (9, 40),
        "skills": ["艺术/手艺（任一）", "攀爬", "驾驶（汽车）", "电气维修",
                    "机械维修", "操纵重型机械", "任一", "任一"],
        "skill_points": "EDU×4",
    },
    "管家": {
        "credit_rating": (9, 40),
        "skills": ["会计", "艺术/手艺（任一）", "急救", "聆听",
                    "心理学", "侦查", "任一", "任一"],
        "skill_points": "EDU×4",
    },
    "服务生": {
        "credit_rating": (9, 20),
        "skills": ["会计", "艺术/手艺（任一）", "闪避", "聆听",
                    "社交技能（任一）", "社交技能（任一）", "心理学", "任一"],
        "skill_points": "EDU×2+APP×2",
        "skill_points_alt": "EDU×2+DEX×2",
    },
    "勤杂护工": {
        "credit_rating": (6, 15),
        "skills": ["电气维修", "社交技能（任一）", "格斗（斗殴）", "急救",
                    "聆听", "机械维修", "心理学", "潜行"],
        "skill_points": "EDU×2+STR×2",
    },

    # === 白领 ===
    "编辑": {
        "credit_rating": (10, 30),
        "skills": ["会计", "历史", "母语", "社交技能（任一）",
                    "社交技能（任一）", "心理学", "侦查", "任一"],
        "skill_points": "EDU×4",
    },
    "秘书": {
        "credit_rating": (9, 30),
        "skills": ["会计", "艺术/手艺（速记）", "社交技能（任一）", "社交技能（任一）",
                    "母语", "图书馆使用", "心理学", "任一"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+APP×2",
    },
    "设计师": {
        "credit_rating": (20, 60),
        "skills": ["会计", "艺术/手艺（摄影）", "艺术/手艺（任一）", "图书馆使用",
                    "机械维修", "心理学", "侦查", "任一"],
        "skill_points": "EDU×4",
    },
    "白领职员": {
        "credit_rating": (9, 20),
        "skills": ["会计", "母语", "法律", "图书馆使用",
                    "聆听", "社交技能（任一）", "任一", "任一"],
        "skill_points": "EDU×4",
    },
    "管理人员": {
        "credit_rating": (20, 80),
        "skills": ["会计", "外语（任一）", "法律", "社交技能（任一）",
                    "社交技能（任一）", "心理学", "任一", "任一"],
        "skill_points": "EDU×4",
    },

    # === 特殊/上流 ===
    "业余爱好者": {
        "credit_rating": (50, 99),
        "skills": ["艺术/手艺（任一）", "射击（任一）", "外语（任一）", "骑术",
                    "社交技能（任一）", "任一", "任一", "任一"],
        "skill_points": "EDU×2+APP×2",
        "tags": ["原作向"],
    },
    "绅士/淑女": {
        "credit_rating": (40, 90),
        "skills": ["艺术/手艺（任一）", "社交技能（任一）", "社交技能（任一）",
                    "射击（步枪/霰弹枪）", "历史", "外语（任一）", "导航", "骑术"],
        "skill_points": "EDU×2+APP×2",
    },
    "教团首领": {
        "credit_rating": (30, 60),
        "skills": ["会计", "社交技能（任一）", "社交技能（任一）", "神秘学",
                    "心理学", "侦查", "任一", "任一"],
        "skill_points": "EDU×4",
    },

    # === 底层/边缘 ===
    "流浪汉": {
        "credit_rating": (0, 5),
        "skills": ["攀爬", "跳跃", "聆听", "导航",
                    "社交技能（任一）", "潜行", "任一", "任一"],
        "skill_points": "EDU×2+APP×2",
        "skill_points_alt": "EDU×2+DEX×2",
    },
    "游民": {
        "credit_rating": (0, 5),
        "skills": ["艺术/手艺（任一）", "攀爬", "跳跃", "聆听",
                    "锁匠", "导航", "潜行", "任一"],
        "skill_points": "EDU×2+APP×2",
        "skill_points_alt": "EDU×2+DEX×2",
    },
    "性工作者": {
        "credit_rating": (5, 50),
        "skills": ["艺术/手艺（任一）", "社交技能（任一）", "社交技能（任一）", "闪避",
                    "心理学", "妙手", "潜行", "任一"],
        "skill_points": "EDU×2+APP×2",
    },

    # === 其他 ===
    "事务所侦探": {
        "credit_rating": (20, 45),
        "skills": ["社交技能（任一）", "格斗（斗殴）", "射击（任一）", "法律",
                    "图书馆使用", "心理学", "潜行", "追踪"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },
    "动物训练师": {
        "credit_rating": (10, 40),
        "skills": ["跳跃", "聆听", "博物学", "骑术",
                    "科学（动物学）", "潜行", "追踪", "任一"],
        "skill_points": "EDU×2+APP×2",
        "skill_points_alt": "EDU×2+POW×2",
    },
    "精神病院看护": {
        "credit_rating": (8, 20),
        "skills": ["闪避", "格斗（斗殴）", "急救", "社交技能（任一）",
                    "社交技能（任一）", "聆听", "心理学", "潜行"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },
    "赌徒": {
        "credit_rating": (8, 50),
        "skills": ["会计", "艺术/手艺（表演）", "社交技能（任一）", "社交技能（任一）",
                    "聆听", "心理学", "妙手", "侦查"],
        "skill_points": "EDU×2+APP×2",
        "skill_points_alt": "EDU×2+DEX×2",
    },
    "潜水员": {
        "credit_rating": (9, 30),
        "skills": ["急救", "机械维修", "驾驶（船）",
                    "科学（生物学）", "侦查", "游泳", "任一", "任一"],
        "skill_points": "EDU×2+DEX×2",
    },
    "殡葬师": {
        "credit_rating": (20, 40),
        "skills": ["会计", "驾驶（汽车）", "社交技能（任一）", "历史",
                    "神秘学", "心理学", "科学（生物学）", "科学（化学）"],
        "skill_points": "EDU×4",
    },
    "博物馆管理员": {
        "credit_rating": (10, 30),
        "skills": ["会计", "估价", "考古学", "历史",
                    "图书馆使用", "神秘学", "外语（任一）", "侦查"],
        "skill_points": "EDU×4",
    },
    "工会活动家": {
        "credit_rating": (5, 50),
        "skills": ["会计", "社交技能（任一）", "社交技能（任一）", "格斗（斗殴）",
                    "法律", "聆听", "操纵重型机械", "心理学"],
        "skill_points": "EDU×4",
    },
    "狂热者": {
        "credit_rating": (0, 30),
        "skills": ["历史", "社交技能（任一）", "社交技能（任一）", "心理学",
                    "潜行", "任一", "任一", "任一"],
        "skill_points": "EDU×2+APP×2",
        "skill_points_alt": "EDU×2+POW×2",
    },
    "牛仔": {
        "credit_rating": (9, 20),
        "skills": ["闪避", "格斗（斗殴）", "急救", "跳跃",
                    "骑术", "生存（任一）", "投掷", "追踪"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },
    "淘金客": {
        "credit_rating": (0, 10),
        "skills": ["攀爬", "急救", "历史", "机械维修",
                    "导航", "科学（地质学）", "侦查", "任一"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },
    "部落成员": {
        "credit_rating": (0, 15),
        "skills": ["攀爬", "格斗（斗殴）", "聆听", "博物学",
                    "神秘学", "侦查", "游泳", "生存（任一）"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },
    "学生": {
        "credit_rating": (5, 10),
        "skills": ["母语", "图书馆使用", "聆听",
                    "任一", "任一", "任一", "任一", "任一"],
        "skill_points": "EDU×4",
    },
    "替身演员": {
        "credit_rating": (10, 50),
        "skills": ["攀爬", "闪避", "电气维修", "格斗（斗殴）",
                    "急救", "跳跃", "游泳", "任一"],
        "skill_points": "EDU×2+DEX×2",
        "skill_points_alt": "EDU×2+STR×2",
    },
    "饲养员": {
        "credit_rating": (9, 40),
        "skills": ["会计", "闪避", "急救", "博物学",
                    "医学", "科学（药学）", "科学（动物学）", "骑术"],
        "skill_points": "EDU×4",
    },

    # === 现代特有 ===
    "计算机工程师": {
        "credit_rating": (10, 70),
        "skills": ["计算机使用", "电气维修", "电子学", "图书馆使用",
                    "科学（数学）", "侦查", "任一", "任一"],
        "skill_points": "EDU×4",
        "tags": ["现代"],
    },
    "黑客": {
        "credit_rating": (10, 70),
        "skills": ["计算机使用", "电气维修", "电子学", "图书馆使用",
                    "侦查", "社交技能（任一）", "任一", "任一"],
        "skill_points": "EDU×4",
        "tags": ["现代"],
    },
    "超心理学家": {
        "credit_rating": (9, 30),
        "skills": ["人类学", "艺术/手艺（摄影）", "历史", "图书馆使用",
                    "神秘学", "外语（任一）", "心理学", "任一"],
        "skill_points": "EDU×4",
    },
    "除魅师": {
        "credit_rating": (20, 50),
        "skills": ["社交技能（任一）", "社交技能（任一）", "驾驶（汽车）", "格斗（斗殴）",
                    "历史", "神秘学", "心理学", "潜行"],
        "skill_points": "EDU×4",
        "tags": ["现代"],
    },
}
