import hashlib
from datetime import datetime
from typing import Optional
import numpy as np

from ..models import Experience
from ..file_watcher import TTLManager


class SearchService:
    def __init__(
        self,
        store,
        vector_store,
        metrics,
        provider,
        project: str = "default",
    ):
        self._store = store
        self._vector_store = vector_store
        self._metrics = metrics
        self._provider = provider
        self._project = project
        self._ttl_manager = TTLManager()

    async def search(
        self,
        query: str,
        tags: Optional[list] = None,
        top_k: int = 3,
        threshold: float = 0.5,
        cross_project: bool = False,
        session_id: Optional[str] = None,
        enable_ab_test: bool = True,
    ) -> tuple:
        ab_test_group = "treatment"
        show_results = True
        if enable_ab_test and session_id:
            hash_val = int(hashlib.md5(session_id.encode()).hexdigest(), 16)
            if hash_val % 10 == 0:
                ab_test_group = "control"
                show_results = False

        candidates = self._store.list_active()
        if not cross_project:
            candidates = [e for e in candidates if e.project == self._project]

        valid_candidates = []
        for exp in candidates:
            if self._ttl_manager.is_expired(exp.last_hit_at):
                continue
            if exp.stale_reason:
                continue
            if tags and not any(t in exp.metadata.tech_stack for t in tags):
                continue
            valid_candidates.append(exp)

        if not show_results or not valid_candidates:
            self._metrics.record_search(query, 0)
            return [], {"ab_test_group": ab_test_group, "show_results": show_results, "strategy": "embedding_only"}

        from ..embeddings import cosine_similarity

        query_vec = np.array(self._provider.embed_text(query), dtype=np.float32)
        candidate_ids = [e.id for e in valid_candidates]
        ids, vecs = self._vector_store.get_all_vectors(candidate_ids)

        missing_exps = [e for e in valid_candidates if e.id not in ids]
        if missing_exps:
            missing_texts = [f"{e.title}\n{e.problem}\n{e.key_decisions}" for e in missing_exps]
            missing_vecs = self._provider.embed_texts(missing_texts)
            self._vector_store.save_vectors(list(zip([e.id for e in missing_exps], missing_vecs)))
            ids, vecs = self._vector_store.get_all_vectors(candidate_ids)

        if len(vecs) == 0:
            return [], {"ab_test_group": ab_test_group, "show_results": True, "strategy": "embedding_only"}

        scores = cosine_similarity(query_vec, vecs)

        results = []
        id_to_exp = {e.id: e for e in valid_candidates}
        for exp_id, score in zip(ids, scores):
            if score >= threshold:
                exp = id_to_exp[exp_id]
                exp.similarity = round(float(score), 3)
                results.append((exp, score))

        results.sort(key=lambda x: x[1], reverse=True)
        results = results[:top_k]

        now = datetime.utcnow().isoformat()
        for exp, _ in results:
            exp.last_hit_at = now
            self._store.update(exp)

        self._metrics.record_search(query, len(results))
        return [exp for exp, _ in results], {"ab_test_group": ab_test_group, "show_results": True, "strategy": "embedding_only"}
