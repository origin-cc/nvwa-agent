"""路径解析：配置中的相对路径一律基于仓库根目录解析，与服务启动 cwd 无关。"""
from pathlib import Path

# backend/nvwa_agent/core/paths.py -> 仓库根目录
REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def resolve_path(value) -> Path:
    """将配置中的相对路径（如 ./plugins）解析为基于仓库根目录的绝对 Path。"""
    p = Path(value)
    return p if p.is_absolute() else (REPO_ROOT / p).resolve()
