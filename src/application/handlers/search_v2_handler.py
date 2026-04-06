from __future__ import annotations
import uuid
from datetime import datetime
from typing import Callable, Any

import numpy as np

from ..commands import SearchV2Command
from ..unit_of_work import AbstractUnitOfWork
from ...domain.manifest_parser import parse_manifest
from ...domain.search_v2 import (
    apply_scope_weight,
    apply_tech_stack_boost,
    merge_and_deduplicate,
    ScopeWeightedResult,
)
from ...models import ScopeType, SearchEvent


class SearchV2Handler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork], embedding_provider: Any):
        self._uow_factory = uow_factory
        self._provider = embedding_provider

    async def handle(self, cmd: SearchV2Command) -> dict:
        manifest_info = parse_manifest(cmd.project_manifest)
        language = manifest_info["language"]
        frameworks = manifest_info["frameworks"]
        top_deps = manifest_info["top_dependencies"]

        query_text = f"{cmd.task_description} {language} {' '.join(top_deps)}"
        query_vec = np.array(self._provider.embed_text(query_text), dtype=np.float32)

        async with self._uow_factory() as uow:
            all_exps = uow.experiences.list_by_status("active")

            project_exps = [e for e in all_exps if e.scope_type == ScopeType.PROJECT and e.scope_id == cmd.project_id]
            business_exps = [e for e in all_exps if e.scope_type == ScopeType.BUSINESS]
            team_exps = [e for e in all_exps if e.scope_type == ScopeType.TEAM]

            weighted_results: list[ScopeWeightedResult] = []
            for scope_exps, scope_name in [
                (project_exps, "project"),
                (business_exps, "business"),
                (team_exps, "team"),
            ]:
                for exp in scope_exps:
                    vec = await self._get_or_compute_vector(exp, uow)
                    if vec is None:
                        continue
                    raw_score = float(np.dot(query_vec, vec) / (np.linalg.norm(query_vec) * np.linalg.norm(vec) + 1e-9))
                    if raw_score < 0.5:
                        continue
                    boosted = apply_tech_stack_boost(
                        score=raw_score,
                        exp_tags=exp.tags,
                        query_languages=[language] + frameworks,
                        query_dependencies=top_deps,
                    )
                    final_score = apply_scope_weight(score=boosted, scope_type=scope_name)
                    weighted_results.append(ScopeWeightedResult(exp_id=exp.id, score=final_score, scope_type=scope_name))

        merged = merge_and_deduplicate(weighted_results, top_k=cmd.top_k, threshold=0.0)

        exp_map = {e.id: e for e in all_exps}
        results = []
        for r in merged:
            exp = exp_map.get(r.exp_id)
            if exp:
                results.append({
                    "id": exp.id,
                    "title": exp.title,
                    "level": exp.level.value,
                    "source_level": r.scope_type,
                    "tags": exp.tags,
                    "problem": exp.problem,
                    "solution": exp.solution,
                    "key_decisions": exp.key_decisions,
                    "score": round(r.score, 3),
                })

        search_event_id = str(uuid.uuid4())
        return {
            "search_event_id": search_event_id,
            "results": results,
        }

    async def _get_or_compute_vector(self, exp, uow) -> "np.ndarray | None":
        ids, vecs = uow.vectors.get_all_vectors([exp.id])
        if ids and len(vecs) > 0:
            return np.array(vecs[0], dtype=np.float32)
        embed_text = f"{exp.title} {exp.solution} {exp.key_decisions}"
        vec = self._provider.embed_text(embed_text)
        uow.vectors.save_vector(exp.id, vec)
        return np.array(vec, dtype=np.float32)
