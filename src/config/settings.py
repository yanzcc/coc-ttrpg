"""自单一 YAML 加载的应用配置（Pydantic），环境变量覆盖敏感项。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

# src/config -> src -> 项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "app.yaml"


class PathsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_dir: str = "data"


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: Optional[str] = None


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_model: str = "claude-sonnet-4-20250514"
    api_key: Optional[str] = None


class AgentsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_default: int = 4096
    game_master: int = 2048
    scene_keeper: int = 4096
    npc_keeper: int = 1536
    skill_check: int = 512
    combat: int = 1024
    memory_curator: int = 2048
    character_mgr: int = 1024
    story_gen: int = 8192
    module_loader: int = 8192
    # KP 监督路由（Claude Haiku 等）：判断本轮旁白 vs NPC 专线；失败时回退规则
    keeper_supervisor_enabled: bool = False
    keeper_supervisor_model: str = "claude-haiku-4-5-20251001"
    keeper_supervisor_max_tokens: int = 256


class ContextConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    builder_max_tokens: int = 8000
    summarize_max_tokens: int = 1024


class SessionConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_token_budget: int = 500_000
    token_warning_thresholds: list[int] = Field(default_factory=lambda: [50, 80, 95])


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    uvicorn_reload: bool = True


class APIConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = "克苏鲁的呼唤 TTRPG"
    description: str = "多Agent驱动的克苏鲁的呼唤跑团框架"
    version: str = "0.1.0"


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    paths: PathsConfig = Field(default_factory=PathsConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    api: APIConfig = Field(default_factory=APIConfig)

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    def resolved_data_dir(self) -> Path:
        return (PROJECT_ROOT / self.paths.data_dir).resolve()

    def effective_database_url(self) -> str:
        env_url = os.getenv("DATABASE_URL")
        if env_url:
            return env_url
        if self.database.url:
            return self.database.url
        db_path = self.resolved_data_dir() / "coc_ttrpg.db"
        return f"sqlite+aiosqlite:///{db_path.as_posix()}"

    def effective_anthropic_api_key(self) -> str | None:
        return os.getenv("ANTHROPIC_API_KEY") or self.llm.api_key

    def effective_server_host(self) -> str:
        return os.getenv("HOST", self.server.host)

    def effective_server_port(self) -> int:
        return int(os.getenv("PORT", str(self.server.port)))


def _config_file_path() -> Path:
    override = os.getenv("COC_TTRPG_CONFIG")
    if override:
        return Path(override).expanduser().resolve()
    return _DEFAULT_CONFIG_PATH


def _load_raw_from_yaml() -> dict:
    path = _config_file_path()
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


@lru_cache
def get_settings() -> AppSettings:
    raw = _load_raw_from_yaml()
    return AppSettings.model_validate(raw)


def reset_settings() -> None:
    """测试或热重载前清除缓存。"""
    get_settings.cache_clear()
