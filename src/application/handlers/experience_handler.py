from __future__ import annotations
import uuid
from datetime import datetime
from typing import Callable
from ..commands import (
    CreateExperienceCommand,
    ActivateExperienceCommand,
    ArchiveExperienceCommand,
)
from ..unit_of_work import AbstractUnitOfWork
from ...domain.events import ExperienceCreated, ExperienceActivated, ExperienceArchived, EmbeddingRequested
from ...domain.constants import (
    QUALITY_SCORE_AUTO_ACTIVATE,
    QUALITY_SCORE_MIN_ACCEPT,
    CONFIDENCE_AUTO_ACTIVATE_INITIAL,
)
from ...domain.quality import compute_quality_score
from ...domain.metadata import infer_tech_stack, infer_scene, infer_type, infer_level


class ExperienceHandler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork], llm, metadata_inferrer):
        self._uow_factory = uow_factory
        self._llm = llm
        self._metadata = metadata_inferrer

    def handle_create(self, cmd: CreateExperienceCommand):
        parts = cmd.task_output.split("\n", 2)
        task_desc = parts[0] if len(parts) > 0 else cmd.task_output
        solution = parts[1] if len(parts) > 1 else ""
        key_decisions = parts[2] if len(parts) > 2 else ""

        meta = self._metadata.infer(cmd.task_output)
        tech_stack = meta.get("tech_stack", [])
        scene = meta.get("scene", [])
        level = meta.get("level", "L2")
        title = self._llm.generate_title(cmd.task_output)

        quality_score = compute_quality_score(
            key_decisions=key_decisions,
            solution_summary=solution,
            related_files=[],
            tech_stack=tech_stack,
        )

        if quality_score < QUALITY_SCORE_MIN_ACCEPT:
            raise ValueError(f"质量评分过低（{quality_score}/100），提取已拒绝。")

        exp_id = str(uuid.uuid4())
        status = "PENDING"
        confidence = 0.6

        class _Exp:
            pass

        exp = _Exp()
        exp.id = exp_id
        exp.title = title
        exp.problem = task_desc
        exp.solution = solution
        exp.key_decisions = key_decisions
        exp.status = status
        exp.confidence = confidence
        exp.tech_stack = tech_stack
        exp.scene = scene
        exp.level = level
        exp.source = "agent"
        exp.project_id = cmd.project_id
        exp.created_at = datetime.utcnow().isoformat()
        exp.tags = []
        exp.related_files = []
        exp.last_hit_at = None
        exp.reject_reason = None

        events = [
            ExperienceCreated(
                experience_id=exp_id,
                title=title,
                content=cmd.task_output,
                tech_stack=tech_stack,
                scene=scene,
                level=level,
                quality_score=quality_score,
                project_id=cmd.project_id,
            ),
            EmbeddingRequested(experience_id=exp_id, text=f"{title}\n{task_desc}\n{key_decisions}"),
        ]

        if quality_score >= QUALITY_SCORE_AUTO_ACTIVATE:
            exp.status = "ACTIVE"
            exp.confidence = CONFIDENCE_AUTO_ACTIVATE_INITIAL
            events.append(ExperienceActivated(experience_id=exp_id, triggered_by="auto"))

        with self._uow_factory() as uow:
            uow.experiences.add(exp)
            for event in events:
                uow.collect_event(event)

        return exp

    def handle_activate(self, cmd: ActivateExperienceCommand):
        with self._uow_factory() as uow:
            exp = uow.experiences.get(cmd.experience_id)
            if exp is None:
                return False
            exp.status = "ACTIVE"
            uow.experiences.update(exp)
            uow.collect_event(ExperienceActivated(
                experience_id=cmd.experience_id,
                triggered_by="manual",
            ))
        return True

    def handle_archive(self, cmd: ArchiveExperienceCommand):
        with self._uow_factory() as uow:
            exp = uow.experiences.get(cmd.experience_id)
            if exp is None:
                return False
            exp.status = "ARCHIVED"
            exp.reject_reason = cmd.reason
            uow.experiences.update(exp)
            uow.collect_event(ExperienceArchived(
                experience_id=cmd.experience_id,
                reason=cmd.reason,
            ))
        return True
