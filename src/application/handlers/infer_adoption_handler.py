from __future__ import annotations
from typing import Callable
from ..commands import InferAdoptionCommand
from ..unit_of_work import AbstractUnitOfWork


class InferAdoptionHandler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork]):
        self._uow_factory = uow_factory

    def handle_infer_adoption(self, cmd: InferAdoptionCommand) -> list[dict]:
        if not cmd.experience_ids_injected:
            return []

        from ...embeddings import get_provider, cosine_similarity
        from ...storage import ExperienceStore, VectorStore, MetricsStore
        from ...domain.feedback import compute_new_confidence
        import numpy as np

        provider = get_provider()
        store = ExperienceStore()
        v_store = VectorStore()
        metrics = MetricsStore()

        v_resp = np.array(provider.embed_text(cmd.final_response), dtype=np.float32)
        ids, vecs = v_store.get_all_vectors(cmd.experience_ids_injected)

        missing_ids = [eid for eid in cmd.experience_ids_injected if eid not in ids]
        if missing_ids:
            missing_exps = [store.get(eid) for eid in missing_ids if store.get(eid)]
            if missing_exps:
                missing_texts = [f"{e.title}\n{e.problem}\n{e.key_decisions}" for e in missing_exps]
                missing_vecs = provider.embed_texts(missing_texts)
                v_store.save_vectors(list(zip([e.id for e in missing_exps], missing_vecs)))
                ids, vecs = v_store.get_all_vectors(cmd.experience_ids_injected)

        if len(vecs) == 0:
            return []

        scores = cosine_similarity(v_resp, vecs)

        results = []
        for exp_id, score in zip(ids, scores):
            score_float = float(score)
            adopted = score_float >= 0.60

            exp = store.get(exp_id)
            if exp:
                exp.confidence = compute_new_confidence(exp.confidence, adopted)
                from ...models import ExperienceStatus
                from ...domain.constants import AUTO_ARCHIVE_ADOPTION_THRESHOLD
                if exp.confidence <= AUTO_ARCHIVE_ADOPTION_THRESHOLD:
                    exp.status = ExperienceStatus.ARCHIVED
                    exp.reject_reason = "Low adoption rate, auto archived"
                store.update(exp)

                from ...models import Feedback
                metrics.record_feedback(Feedback(
                    experience_id=exp_id,
                    adopted=adopted,
                    reason=f"Auto inferred: {score_float:.2f} cosine similarity",
                ))

            results.append({
                "experience_id": exp_id,
                "adopted": adopted,
                "confidence": round(score_float if adopted else 0.0, 2),
                "matched_keywords": [],
                "match_rate": round(score_float, 2),
            })

        return results
