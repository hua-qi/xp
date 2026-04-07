from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np

from ..commands import SearchV2Command
from ...models import Session


class SearchV2Handler:
    def __init__(self, backend, llm, embedding_provider):
        self._backend = backend
        self._llm = llm
        self._embed = embedding_provider

    async def handle(self, cmd: SearchV2Command) -> dict[str, Any]:
        ab_group = await self._backend.async_get_ab_group(cmd.project_id)
        session_id = str(uuid.uuid4())

        if ab_group == "A":
            results = await self._a_group_search(cmd)
        else:
            exp_ids, vecs = await self._backend.async_get_vectors_by_project(cmd.project_id)
            results = await self._b_group_search(cmd.task_description, exp_ids, vecs)

        await self._backend.async_record_session(
            Session(
                session_id=session_id,
                task_description=cmd.task_description,
                experience_ids_injected=[r["id"] for r in results],
                iteration_count=1,
                had_error_correction=False,
                user_accepted=True,
                ab_test_group=ab_group,
                ab_test_result_shown=True,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        return {"session_id": session_id, "experiences": results[:cmd.top_k]}

    async def _a_group_search(self, cmd: SearchV2Command) -> list[dict]:
        exps = await self._backend.async_fulltext_search(
            cmd.task_description, cmd.project_id, limit=20
        )
        if not exps:
            return []
        candidates = "\n".join(
            f"ID: {e.id}\n标题: {e.title}\n问题: {e.problem}\n方案: {e.solution}"
            for e in exps[:10]
        )
        prompt = (
            f"根据以下任务描述，从候选经验中选出最相关的至多3条。\n\n"
            f"## 任务\n{cmd.task_description}\n\n"
            f"## 候选经验\n{candidates}\n\n"
            f"只输出 JSON 数组，包含最相关的经验 ID，按相关度降序排列。"
        )
        raw = await self._llm.call(prompt)
        if not raw:
            return []
        try:
            ids = json.loads(raw.strip())
            id_map = {e.id: e for e in exps}
            return [
                {"id": eid, "title": id_map[eid].title, "problem": id_map[eid].problem}
                for eid in ids
                if eid in id_map
            ]
        except Exception:
            return []

    async def _b_group_search(
        self, task_description: str, exp_ids: list[str], vecs: np.ndarray
    ) -> list[dict]:
        if len(exp_ids) == 0 or (hasattr(vecs, "size") and vecs.size == 0):
            return []
        query_vec = np.array(
            self._embed.embed_text(task_description), dtype=np.float32
        )
        query_vec = query_vec / (np.linalg.norm(query_vec) + 1e-9)
        scores = vecs @ query_vec
        top_indices = np.argsort(scores)[::-1]
        results = []
        for idx in top_indices:
            if float(scores[idx]) >= 0.5:
                results.append({"id": exp_ids[idx], "score": float(scores[idx])})
        return results[:3]
