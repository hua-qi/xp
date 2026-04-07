from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from ...models import (
    Experience, ExperienceType, ExperienceLevel,
    ExperienceMetadata, ExperienceStatus, ExperienceSource, ScopeType,
)
from ...domain.quality import compute_save_quality_score
from ..commands import SaveCommand


EXTRACTION_PROMPT_TEMPLATE = """你是一个工程经验提炼助手。根据以下任务信息，提炼出结构化的工程经验。

## 输入
任务描述：{task_description}
任务结果：{outcome_description}
结果状态：{outcome}

## 输出要求
严格按照以下 JSON 格式输出，不要输出其他内容：
{{
  "title": "10-20字的经验标题，概括核心问题和解法",
  "problem": "清晰描述问题场景和背景，50字以上",
  "solution": "具体的解决方案和步骤，50字以上",
  "key_decisions": "关键决策点和踩坑点，30字以上",
  "tags": ["技术栈标签", "最多5个"],
  "type": "bugfix 或 feature 或 pattern 三选一"
}}"""


class SaveHandler:
    def __init__(self, uow_factory, llm):
        self._uow_factory = uow_factory
        self._llm = llm

    async def handle(self, cmd: SaveCommand) -> dict[str, Any]:
        extracted = await self._extract(cmd)
        if extracted is None:
            return await self._save_pending(cmd)
        return await self._save_active(cmd, extracted)

    async def _extract(self, cmd: SaveCommand) -> Optional[dict]:
        prompt = EXTRACTION_PROMPT_TEMPLATE.format(
            task_description=cmd.task_description,
            outcome_description=cmd.outcome_description,
            outcome=cmd.outcome,
        )
        raw = await self._llm.call(prompt)
        if not raw:
            return None
        try:
            data = json.loads(raw.strip())
            for key in ("title", "problem", "solution", "key_decisions", "tags", "type"):
                if key not in data:
                    return None
            return data
        except (json.JSONDecodeError, KeyError):
            return None

    async def _save_pending(self, cmd: SaveCommand) -> dict[str, Any]:
        exp_id = str(uuid.uuid4())
        exp = Experience(
            id=exp_id,
            type=ExperienceType.PATTERN,
            level=ExperienceLevel.L1,
            title="(待 LLM 提炼)",
            tags=[],
            problem=cmd.task_description,
            solution=cmd.outcome_description,
            key_decisions="",
            confidence=0.5,
            status=ExperienceStatus.PENDING,
            source=ExperienceSource.AGENT,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=ExperienceMetadata(),
            project=cmd.project_id,
            scope_type=ScopeType.PROJECT,
            scope_id=cmd.project_id,
            retry_count=3,
            raw_input={
                "task_description": cmd.task_description,
                "outcome_description": cmd.outcome_description,
                "outcome": cmd.outcome,
            },
        )
        async with self._uow_factory() as uow:
            await uow.experiences.aadd(exp)
        return {"status": "pending_retry", "experience_id": exp_id}

    async def _save_active(self, cmd: SaveCommand, extracted: dict) -> dict[str, Any]:
        exp_id = str(uuid.uuid4())
        type_map = {"bugfix": ExperienceType.BUGFIX, "feature": ExperienceType.FEATURE}
        exp_type = type_map.get(extracted["type"], ExperienceType.PATTERN)
        exp = Experience(
            id=exp_id,
            type=exp_type,
            level=ExperienceLevel.L1,
            title=extracted["title"],
            tags=extracted.get("tags", []),
            problem=extracted["problem"],
            solution=extracted["solution"],
            key_decisions=extracted.get("key_decisions", ""),
            confidence=0.6,
            status=ExperienceStatus.ACTIVE,
            source=ExperienceSource.AGENT,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=ExperienceMetadata(),
            project=cmd.project_id,
            scope_type=ScopeType.PROJECT,
            scope_id=cmd.project_id,
        )
        quality = compute_save_quality_score(
            solution=exp.solution,
            key_decisions=exp.key_decisions,
            tags=exp.tags,
            outcome=cmd.outcome,
        )
        if quality < 80:
            exp.status = ExperienceStatus.PENDING
        async with self._uow_factory() as uow:
            await uow.experiences.aadd(exp)
        return {"status": "saved", "experience_id": exp_id, "quality": quality}
