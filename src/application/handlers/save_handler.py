from __future__ import annotations
import uuid
from datetime import datetime
from typing import Callable, Any

import numpy as np

from ..commands import SaveCommand
from ..unit_of_work import AbstractUnitOfWork
from ...domain.quality import compute_save_quality_score
from ...domain.save_domain import initial_confidence_for_outcome
from ...domain.experience import check_duplicate
from ...models import (
    Experience, ExperienceType, ExperienceLevel, ExperienceStatus,
    ExperienceSource, ExperienceMetadata, ScopeType,
)
from ...domain.constants import DUPLICATE_SIMILARITY_THRESHOLD


class SaveHandler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork], embedding_provider: Any):
        self._uow_factory = uow_factory
        self._provider = embedding_provider

    async def handle(self, cmd: SaveCommand) -> dict:
        quality_score = compute_save_quality_score(
            solution=cmd.solution,
            key_decisions=cmd.key_decisions,
            tags=cmd.tags,
            outcome=cmd.outcome,
        )

        confidence = initial_confidence_for_outcome(cmd.outcome)
        status = ExperienceStatus.ACTIVE if quality_score >= 80 else ExperienceStatus.PENDING

        embed_text = f"{cmd.task_description} {cmd.solution} {cmd.key_decisions}"
        new_vec = np.array(self._provider.embed_text(embed_text), dtype=np.float32)

        duplicate_warning = None
        async with self._uow_factory() as uow:
            active_exps = await uow.experiences.alist_by_status("active")
            pending_exps = await uow.experiences.alist_by_status("pending")
            project_exps = [
                e for e in active_exps
                if getattr(e, "scope_id", None) == cmd.project_id
            ] + [
                e for e in pending_exps
                if getattr(e, "scope_id", None) == cmd.project_id
            ]

            if project_exps:
                exp_ids = [e.id for e in project_exps]
                existing_ids, existing_vecs = await uow.vectors.aget_all_vectors(exp_ids)
                if existing_ids and existing_vecs.size > 0:
                    is_dup, dup_id, dup_score = check_duplicate(new_vec, existing_vecs, existing_ids)
                    if is_dup and dup_score >= DUPLICATE_SIMILARITY_THRESHOLD:
                        duplicate_warning = f"与经验 {dup_id} 相似度 {dup_score:.2f}，请确认是否需要合并"

            exp_id = str(uuid.uuid4())
            exp = Experience(
                id=exp_id,
                type=ExperienceType.BUGFIX,
                level=ExperienceLevel.L1,
                title=cmd.task_description[:60],
                tags=cmd.tags,
                problem=cmd.task_description,
                solution=cmd.solution,
                key_decisions=cmd.key_decisions,
                confidence=confidence,
                status=status,
                source=ExperienceSource.AGENT,
                created_at=datetime.utcnow().isoformat(),
                metadata=ExperienceMetadata(tech_stack=cmd.tags),
                scope_type=ScopeType.PROJECT,
                scope_id=cmd.project_id,
            )
            await uow.experiences.aadd(exp)
            await uow.vectors.asave_vector(exp_id, new_vec.tolist())

        result = {
            "experience_id": exp_id,
            "status": status.value,
            "quality_score": quality_score,
        }
        if duplicate_warning:
            result["duplicate_warning"] = duplicate_warning
        return result
