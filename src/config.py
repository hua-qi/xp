import json
import os
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
