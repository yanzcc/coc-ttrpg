# coc-ttrpg

基于《克苏鲁的呼唤》桌游思路的 **多 Agent 驱动 TTRPG 框架**：FastAPI + WebSocket 实时叙事、Anthropic Claude 扮演守密人（含场景 / NPC 分工）、技能与理智检定、战斗轮、模组导入与角色卡等。

## 功能概览

- **大厅与游戏页**：创建会话、加载模组、调查员分配、流式叙事展示与历史恢复（重连 / 从大厅返回）
- **守密人 Agent**：场景描写与 NPC 对话分流、技能 / 理智检定叙事、记忆整理（Keeper Memory）
- **多人**：同一 `session_id` 下多玩家 WebSocket；探索期自由发言，战斗期结构化回合（全员提交后结算）
- **持久化**：SQLite 存储会话、调查员、`narrative_log` 等；叙事历史可按会话回放

## 环境要求

- Python **3.11+**
- [Anthropic API](https://docs.anthropic.com/) 密钥（Claude）

## 安装

```bash
cd coc-ttrpg
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

pip install -e ".[dev]"
```

## 配置

1. 在项目根目录创建 `.env`（可参考下方示例），**不要将真实密钥提交到 Git**。

```env
ANTHROPIC_API_KEY=sk-ant-api03-...
# 可选
# CLAUDE_MODEL=claude-sonnet-4-20250514
# HOST=0.0.0.0
# PORT=8000
```

2. 全局参数见 `config/app.yaml`（模型、`max_tokens`、会话 Token 预算、服务端口等）。也可用环境变量 `COC_TTRPG_CONFIG` 指向自定义 YAML。

## 运行

```bash
python run.py
```

浏览器访问 **http://127.0.0.1:8000**（默认端口以 `config/app.yaml` 为准）。

局域网内其他设备使用本机 IP，例如 `http://192.168.x.x:8000`，同一局游戏链接为 `/game/{会话id}?player=玩家名`。

## 项目结构（简要）

```
coc-ttrpg/
├── run.py                 # 启动 uvicorn
├── config/app.yaml        # 应用配置
├── src/
│   ├── api/               # FastAPI 路由、模板、静态资源
│   ├── agents/            # 各 LLM Agent（守密人、技能、战斗、记忆等）
│   ├── middleware/        # 游戏循环、上下文拼装
│   ├── models/            # 领域模型与消息类型
│   ├── storage/           # SQLAlchemy 与仓储
│   └── ...
├── data/                  # 数据目录（本地 .db 已被 .gitignore）
└── tests/
```

## 开发与测试

```bash
pytest
```

## 许可证

未默认指定许可证；如需开源请自行添加 `LICENSE` 并更新本说明。
