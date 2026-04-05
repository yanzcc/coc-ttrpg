"""默认关闭 Haiku 监督路由，避免 pytest 无 API 密钥时发起网络请求。

生产环境由 config/app.yaml 开启；本地测试可设 KEEPER_SUPERVISOR_ENABLED=1 单独验证。
"""

import pytest

from src.config.settings import reset_settings


@pytest.fixture(autouse=True)
def _disable_keeper_supervisor_for_tests(monkeypatch):
    monkeypatch.setenv("KEEPER_SUPERVISOR_ENABLED", "0")
    reset_settings()
    yield
    reset_settings()
