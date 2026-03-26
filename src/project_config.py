"""项目配置管理 (Phase 3)"""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .models import ProjectConfig


XP_HOME = Path(os.environ.get("XP_HOME", "/Users/lianzimeng/workspace/xp-data"))
PROJECT_CONFIG_FILE = XP_HOME / "projects.json"
CURRENT_PROJECT_FILE = XP_HOME / "current_project"


def _ensure_home():
    XP_HOME.mkdir(parents=True, exist_ok=True)


class ProjectManager:
    """项目管理器"""

    def __init__(self):
        self._projects: dict[str, ProjectConfig] = {}
        self._load()

    def _load(self):
        """加载项目配置"""
        if PROJECT_CONFIG_FILE.exists():
            with open(PROJECT_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for name, config in data.items():
                self._projects[name] = ProjectConfig(**config)

    def _save(self):
        """保存项目配置"""
        _ensure_home()
        data = {name: asdict(config) for name, config in self._projects.items()}
        with open(PROJECT_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def create(self, name: str, tags: list[str] = None, root_path: str = None) -> ProjectConfig:
        """创建新项目"""
        if name in self._projects:
            raise ValueError(f"项目 '{name}' 已存在")

        config = ProjectConfig(
            name=name,
            tags=tags or [],
            root_path=root_path,
        )
        self._projects[name] = config
        self._save()
        return config

    def get(self, name: str) -> Optional[ProjectConfig]:
        """获取项目配置"""
        return self._projects.get(name)

    def list(self) -> list[ProjectConfig]:
        """列出所有项目"""
        return list(self._projects.values())

    def set_current(self, name: str):
        """设置当前项目"""
        if name not in self._projects:
            raise ValueError(f"项目 '{name}' 不存在")
        _ensure_home()
        CURRENT_PROJECT_FILE.write_text(name, encoding="utf-8")

    def get_current(self) -> str:
        """获取当前项目名称"""
        if CURRENT_PROJECT_FILE.exists():
            return CURRENT_PROJECT_FILE.read_text(encoding="utf-8").strip()
        return "default"

    def update(self, name: str, **kwargs) -> Optional[ProjectConfig]:
        """更新项目配置"""
        if name not in self._projects:
            return None
        config = self._projects[name]
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        self._save()
        return config

    def enable_cloud_sync(self, name: str, provider: str, **config_kwargs) -> Optional[ProjectConfig]:
        """启用云端同步"""
        return self.update(
            name,
            cloud_sync_enabled=True,
            cloud_provider=provider,
            cloud_config=config_kwargs
        )

    def disable_cloud_sync(self, name: str) -> Optional[ProjectConfig]:
        """禁用云端同步"""
        return self.update(
            name,
            cloud_sync_enabled=False,
            cloud_provider=None,
            cloud_config={}
        )
