"""数据路径解析：支持环境变量覆盖，默认仓库根目录下的 data/。"""

from __future__ import annotations

import os
from pathlib import Path

# 仓库根目录 = 本文件向上 3 级（src/selfgrow/paths.py -> 根）
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ.get("SELFGROW_DATA_DIR", PROJECT_ROOT / "data"))
FRAMEWORKS_DIR = DATA_DIR / "frameworks"
ASSESSMENTS_DIR = DATA_DIR / "assessments"
SCENARIOS_DIR = DATA_DIR / "scenarios"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"

# 本地 SQLite 库默认位置，可用 SELFGROW_DB 覆盖
DB_PATH = Path(os.environ.get("SELFGROW_DB", DATA_DIR / "selfgrow.db"))


def ensure_data_dirs() -> None:
    """确保数据目录存在（首次运行 / 测试隔离时调用）。"""
    for d in (FRAMEWORKS_DIR, ASSESSMENTS_DIR, SCENARIOS_DIR, KNOWLEDGE_DIR):
        d.mkdir(parents=True, exist_ok=True)
