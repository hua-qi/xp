"""文件监听和 hash 追踪模块 (Phase 3)"""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .config import XP_HOME

WATCH_STATE_FILE = XP_HOME / "watch_state.json"


def _ensure_home():
    XP_HOME.mkdir(parents=True, exist_ok=True)


def calculate_file_hash(file_path: str) -> Optional[str]:
    """计算文件内容的 hash (SHA256 前 16 位)"""
    try:
        path = Path(file_path)
        if not path.exists():
            return None
        content = path.read_bytes()
        return hashlib.sha256(content).hexdigest()[:16]
    except (IOError, OSError):
        return None


def calculate_files_hashes(file_paths: list[str]) -> dict[str, str]:
    """批量计算文件 hashes"""
    result = {}
    for path in file_paths:
        hash_value = calculate_file_hash(path)
        if hash_value:
            result[path] = hash_value
    return result


class FileWatcher:
    """文件变更监听器"""

    def __init__(self):
        self._stale_checkers: list[callable] = []

    def add_stale_checker(self, checker: callable):
        """添加失效检查回调"""
        self._stale_checkers.append(checker)

    def check_files_changed(self, exp_id: str, file_hashes: dict[str, str]) -> tuple[bool, list[str]]:
        """
        检查文件是否变更

        Returns:
            (是否变更, 变更的文件列表)
        """
        changed_files = []
        for file_path, old_hash in file_hashes.items():
            current_hash = calculate_file_hash(file_path)
            if current_hash is None:
                # 文件被删除
                changed_files.append(file_path)
            elif current_hash != old_hash:
                changed_files.append(file_path)

        return len(changed_files) > 0, changed_files

    def run_check(self, experiences: list) -> list[tuple]:
        """
        运行检查，返回失效的经验列表

        Returns:
            [(experience, 变更文件列表), ...]
        """
        stale_experiences = []
        for exp in experiences:
            if not exp.file_hashes:
                continue
            changed, files = self.check_files_changed(exp.id, exp.file_hashes)
            if changed:
                stale_experiences.append((exp, files))
        return stale_experiences


class TTLManager:
    """TTL 管理器 - 90 天未命中自动归档"""

    TTL_DAYS = 90

    def is_expired(self, last_hit_at: Optional[str]) -> bool:
        """检查是否超过 TTL"""
        if not last_hit_at:
            return False
        try:
            last_hit = datetime.fromisoformat(last_hit_at)
            return datetime.utcnow() - last_hit > timedelta(days=self.TTL_DAYS)
        except ValueError:
            return False

    def check_experiences(self, experiences: list) -> list:
        """检查并返回过期经验列表"""
        expired = []
        for exp in experiences:
            if self.is_expired(exp.last_hit_at):
                expired.append(exp)
        return expired


class WatchState:
    """监听状态管理"""

    def __init__(self):
        self.last_check_at: Optional[str] = None
        self.stale_experience_ids: list[str] = []
        self.notified_ids: list[str] = []

    def save(self):
        """保存状态到文件"""
        _ensure_home()
        data = {
            "last_check_at": self.last_check_at,
            "stale_experience_ids": self.stale_experience_ids,
            "notified_ids": self.notified_ids,
        }
        with open(WATCH_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls) -> "WatchState":
        """从文件加载状态"""
        if not WATCH_STATE_FILE.exists():
            return cls()
        with open(WATCH_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        state = cls()
        state.last_check_at = data.get("last_check_at")
        state.stale_experience_ids = data.get("stale_experience_ids", [])
        state.notified_ids = data.get("notified_ids", [])
        return state
