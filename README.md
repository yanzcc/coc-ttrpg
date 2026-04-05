# coc-ttrpg

**GitHub**：[https://github.com/yanzcc/coc-ttrpg](https://github.com/yanzcc/coc-ttrpg)

基于《克苏鲁的呼唤》桌游思路的 **多 Agent 驱动 TTRPG 框架**：FastAPI + WebSocket 实时叙事、Anthropic Claude 扮演守密人、技能与理智检定、战斗轮、模组导入与角色卡等。

## 功能概览

- **大厅与游戏页**：创建会话、加载模组、调查员分配、流式叙事；从大厅返回后通过 WebSocket `catch_up` 恢复 `narrative_log` 历史
- **分层守密人（KP）**
  - **`UnifiedKP`**（总协调）：统一入口 `route_player_action`（`async`），下属 **`narration`**（场景 / 纯旁白）与 **`npc_actor`**（单 NPC 扮演）
  - **旁白**：只写环境与机制标记；NPC 需开口时输出 `【NPC发言：全名】`，台词由 NPC 下属生成
  - **可选 KP 监督**：默认用 **Claude Haiku**（`config/app.yaml` 中 `keeper_supervisor_*`）在「旁白 vs NPC 专线」间做 JSON 路由；失败或未启用时回退 **规则路由**（`keeper_router.py`）
- **多人**：同一 `session_id` 下多玩家 WebSocket；探索期自由发言，战斗期结构化回合（全员提交后结算）
- **持久化**：SQLite 存储会话、调查员、`narrative_log` 等

## 环境要求

- Python **3.11+**
- [Anthropic API](https://docs.anthropic.com/) 密钥（Claude）

## 安装

```bash
git clone https://github.com/yanzcc/coc-ttrpg.git
cd coc-ttrpg
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

pip install -e ".[dev]"
```

## 配置

1. 在项目根目录创建 `.env`（可参考 `.env.example`），**不要将真实密钥提交到 Git**。

```env
ANTHROPIC_API_KEY=sk-ant-api03-...
# 可选
# CLAUDE_MODEL=claude-sonnet-4-20250514
# HOST=0.0.0.0
# PORT=8000
# KP 监督（Haiku）：设为 0 可关闭（pytest 默认也会关）
# KEEPER_SUPERVISOR_ENABLED=0
# KEEPER_SUPERVISOR_MODEL=claude-haiku-4-5-20251001
```

2. **`config/app.yaml`**：`llm.default_model`、各 Agent 的 `max_tokens`、会话 Token 预算、`keeper_supervisor_enabled` / `keeper_supervisor_model`（Haiku 监督，默认开启时使用 **Haiku 4.5**；旧 ID 若 404，代码会按序尝试备用模型）。也可用环境变量 **`COC_TTRPG_CONFIG`** 指向自定义 YAML。

## 运行

```bash
python run.py
```

浏览器访问 **http://127.0.0.1:8000**（端口以 `config/app.yaml` 为准）。

局域网内其他设备使用本机 IP，例如 `http://192.168.x.x:8000`；同一局为 `/game/{会话id}?player=玩家名`。

## 项目结构（简要）

```
coc-ttrpg/
├── run.py                      # 启动 uvicorn
├── config/app.yaml             # 应用配置
├── src/
│   ├── api/                    # FastAPI、模板、静态资源
│   ├── agents/
│   │   ├── hierarchical_keeper.py   # UnifiedKP
│   │   ├── keeper_supervisor.py     # Haiku 路由（可选）
│   │   ├── keeper_router.py         # 规则路由回退
│   │   ├── dual_keepers.py          # 场景旁白 / NPC 扮演 Agent
│   │   └── ...
│   ├── middleware/             # 游戏循环、上下文、Token 追踪
│   ├── models/
│   ├── storage/
│   └── ...
├── data/                       # 本地数据（*.db 已 .gitignore）
└── tests/
```

## 开发与测试

```bash
pytest
```

测试默认通过 **`KEEPER_SUPERVISOR_ENABLED=0`** 关闭 Haiku 监督，避免无密钥时请求 API（见 `tests/conftest.py`）。

## 推送到 GitHub

本仓库远程为 **`https://github.com/yanzcc/coc-ttrpg.git`**。若你 fork 或新建了副本，可：

```bash
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

已安装 [GitHub CLI](https://cli.github.com/) 时也可使用 `gh repo create ... --push`。

## 许可证

未默认指定许可证；如需开源请自行添加 `LICENSE` 并更新本说明。
