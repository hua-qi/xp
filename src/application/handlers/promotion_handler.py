from __future__ import annotations
from datetime import datetime
from typing import Callable, Any

from ..commands import ScanPromotionCandidatesCommand
from ..unit_of_work import AbstractUnitOfWork
from ...domain.promotion import compute_promotion_score, is_promotion_candidate
from ...models import ScopeType


class PromotionScanHandler:
    SIMILARITY_THRESHOLD = 0.85

    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork], embedding_provider: Any):
        self._uow_factory = uow_factory
        self._provider = embedding_provider

    async def handle(self, cmd: ScanPromotionCandidatesCommand) -> dict:
        import numpy as np

        async with self._uow_factory() as uow:
            all_active = await uow.experiences.alist_by_status("active")
            project_exps = [
                e for e in all_active
                if e.scope_type == ScopeType.PROJECT
            ]

            if not project_exps:
                return {"candidates": []}

            exp_ids = [e.id for e in project_exps]
            ids, vecs = await uow.vectors.aget_all_vectors(exp_ids)

            if not ids or vecs.size == 0:
                return {"candidates": []}

            id_to_exp = {e.id: e for e in project_exps}
            id_to_vec = {eid: vecs[i] for i, eid in enumerate(ids)}

            candidates = []
            processed = set()

            for exp_id in ids:
                if exp_id in processed:
                    continue
                exp = id_to_exp.get(exp_id)
                if exp is None:
                    continue

                similar_exps = []
                different_projects = set()
                query_vec = id_to_vec[exp_id]

                for other_id in ids:
                    if other_id == exp_id:
                        continue
                    other_exp = id_to_exp.get(other_id)
                    if other_exp is None:
                        continue
                    if other_exp.scope_id == exp.scope_id:
                        continue

                    other_vec = id_to_vec[other_id]
                    norm_q = np.linalg.norm(query_vec)
                    norm_o = np.linalg.norm(other_vec)
                    if norm_q == 0 or norm_o == 0:
                        continue
                    similarity = float(np.dot(query_vec, other_vec) / (norm_q * norm_o))
                    if similarity >= self.SIMILARITY_THRESHOLD:
                        similar_exps.append(other_id)
                        different_projects.add(other_exp.scope_id)

                if len(different_projects) < 1:
                    continue

                created_dt = datetime.fromisoformat(exp.created_at)
                age_days = (datetime.utcnow() - created_dt).days

                cross_project_count = len(different_projects) + 1
                score = compute_promotion_score(
                    cross_project_count=cross_project_count,
                    adoption_rate=exp.adoption_rate,
                    recall_count=exp.recall_count,
                )

                if is_promotion_candidate(
                    score=score,
                    cross_project_count=cross_project_count,
                    adoption_rate=exp.adoption_rate,
                    recall_count=exp.recall_count,
                    age_days=age_days,
                ):
                    candidates.append({
                        "experience_id": exp_id,
                        "score": round(score, 3),
                        "cross_project_count": cross_project_count,
                        "similar_exp_ids": similar_exps,
                        "reason": (
                            f"在 {cross_project_count} 个项目中均有相似记录，"
                            f"采纳率 {exp.adoption_rate:.0%}，建议提升到 Business 层"
                        ),
                    })
                    processed.add(exp_id)
                    processed.update(similar_exps)

                    if not cmd.dry_run:
                        exp.stale_reason = f"promotion_candidate:score={score:.3f}"
                        await uow.experiences.aupdate(exp)

        return {"candidates": candidates}
