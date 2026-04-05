"""内置示例模组

提供开箱即用的CoC示例模组，适合新手玩家快速体验。
"""

from pathlib import Path

SAMPLES_DIR = Path(__file__).parent


def get_sample_module_path(name: str) -> Path:
    """获取示例模组文件路径"""
    path = SAMPLES_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"示例模组 '{name}' 不存在: {path}")
    return path


def list_sample_modules() -> list[str]:
    """列出所有可用的示例模组名称"""
    return [p.stem for p in SAMPLES_DIR.glob("*.json")]
