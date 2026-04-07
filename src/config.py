import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

XP_HOME = Path(os.environ.get("XP_HOME", Path.home() / ".xp"))


def _config_path() -> Path:
    return XP_HOME / "config.json"


def save_config(data: dict) -> None:
    XP_HOME.mkdir(parents=True, exist_ok=True)
    _config_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_config() -> Optional[dict]:
    path = _config_path()
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class AppConfig:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    LLM_API_BASE: str = os.getenv("XP_LLM_API_BASE", "")
    LLM_API_KEY: str = os.getenv("XP_LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("XP_LLM_MODEL", "gpt-4o-mini")
    LLM_TIMEOUT: int = int(os.getenv("XP_LLM_TIMEOUT", "30"))


def get_config() -> AppConfig:
    return AppConfig(
        DATABASE_URL=os.getenv("DATABASE_URL", ""),
        LLM_API_BASE=os.getenv("XP_LLM_API_BASE", ""),
        LLM_API_KEY=os.getenv("XP_LLM_API_KEY", ""),
        LLM_MODEL=os.getenv("XP_LLM_MODEL", "gpt-4o-mini"),
        LLM_TIMEOUT=int(os.getenv("XP_LLM_TIMEOUT", "30")),
    )
