from __future__ import annotations
from typing import Any

from ..commands import FeedbackV2Command
from ...models import ExperienceStatus

CONFIDENCE_ADOPTED_DELTA = 0.1
CONFIDENCE_REJECTED_DELTA = -0.05
CONFIDENCE_MIN = 0.0
CONFIDENCE_MAX = 1.0
CONFIDENCE_ARCHIVE_THRESHOLD = 0.2


class FeedbackV2Handler:
    def __init__(self, uow_factory, backend, llm):
        self._uow_factory = uow_factory
        self._backend = backend
        self._llm = llm

    async def handle(self, cmd: FeedbackV2Command) -> dict[str, Any]:
        comment_type = None
        if cmd.comment:
            comment_type = await self._analyze_comment(cmd.comment)

        all_ids = list(set(cmd.adopted_ids + cmd.rejected_ids))

        async with self._uow_factory() as uow:
            for exp_id in all_ids:
                exp = await uow.experiences.aget(exp_id)
                if exp is None:
                    continue

                is_adopted = exp_id in cmd.adopted_ids
                is_rejected = exp_id in cmd.rejected_ids
                is_needs_fix = (
                    is_rejected and comment_type == "needs_fix" and cmd.comment
                )

                if is_adopted:
                    exp.confidence = min(CONFIDENCE_MAX, exp.confidence + CONFIDENCE_ADOPTED_DELTA)
                elif is_rejected and not is_needs_fix:
                    exp.confidence = max(CONFIDENCE_MIN, exp.confidence + CONFIDENCE_REJECTED_DELTA)
                    if exp.confidence < CONFIDENCE_ARCHIVE_THRESHOLD:
                        exp.status = ExperienceStatus.ARCHIVED

                if is_needs_fix:
                    exp.status = ExperienceStatus.NEEDS_FIX
                    await self._backend.async_add_correction_request(
                        experience_id=exp_id,
                        session_id=cmd.session_id,
                        comment=cmd.comment,
                        task_description="",
                        outcome_description="",
                    )

                await uow.experiences.aupdate(exp)
                await self._backend.async_update_experience_stats(
                    exp_id,
                    hit=True,
                    adopted=is_adopted,
                    rejected=is_rejected and not is_needs_fix,
                )

        return {"status": "ok"}

    async def _analyze_comment(self, comment: str) -> str:
        prompt = (
            f"以下是用户对一条工程经验的反馈 comment，请判断反馈语义类型。\n\n"
            f"## 反馈内容\n{comment}\n\n"
            f"## 判断规则\n"
            f"- 如果反馈表达\"经验完全不适用、方向错误、和当前问题无关\"，输出：irrelevant\n"
            f"- 如果反馈表达\"经验思路/方向是对的，但某些细节、版本、参数有误\"，输出：needs_fix\n\n"
            f"只输出一个词：irrelevant 或 needs_fix"
        )
        raw = await self._llm.call(prompt)
        if raw and raw.strip() in ("irrelevant", "needs_fix"):
            return raw.strip()
        return "irrelevant"
