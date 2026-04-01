import uuid
from datetime import datetime
from typing import Optional

from src.models import (
    Experience, ExperienceMetadata, ExperienceSource, ExperienceStatus,
)
from src.domain.quality import compute_quality_score
from src.domain.metadata import infer_tech_stack, infer_scene, infer_type, infer_level
from src.file_watcher import calculate_files_hashes


class ExtractionService:
    def __init__(self, store, vector_store, project: str = "default"):
        self._store = store
        self._vector_store = vector_store
        self._project = project

    async def extract(
        self,
        task_description: str,
        solution_summary: str,
        key_decisions: str,
        conversation_summary: Optional[str] = None,
        tags: Optional[list] = None,
        related_files: Optional[list] = None,
        title: Optional[str] = None,
    ) -> Experience:
        tags = tags or []
        related_files = related_files or []

        if not key_decisions or len(key_decisions.strip()) < 10:
            raise ValueError(
                "key_decisions 不能为空且长度不得少于 10 字。"
                "请补充关键决策/踩坑点后重试。"
            )
        if not solution_summary or len(solution_summary.strip()) < 20:
            raise ValueError(
                "solution_summary 长度不得少于 20 字。"
                "请补充解决方案摘要后重试。"
            )

        await self._check_duplicate(task_description, solution_summary)

        all_text = f"{task_description}\n{solution_summary}\n{key_decisions}"
        if conversation_summary:
            all_text = f"{all_text}\n{conversation_summary}"

        tech_stack = infer_tech_stack(all_text)
        scene = infer_scene(all_text)
        level = infer_level(task_description, key_decisions)
        exp_type = infer_type(task_description, key_decisions)

        quality_score = compute_quality_score(
            key_decisions=key_decisions,
            solution_summary=solution_summary,
            related_files=related_files,
            tech_stack=tech_stack if tech_stack else tags,
        )

        if quality_score < 40:
            raise ValueError(
                f"经验质量评分过低（{quality_score}/100），提取已拒绝。"
                f"请补充：key_decisions（当前{len(key_decisions.strip())}字，建议>=50字）"
                f"，solution_summary（当前{len(solution_summary.strip())}字，建议>=50字）"
                f"，相关文件路径，技术栈标签。"
            )

        file_hashes = calculate_files_hashes(related_files)
        if title is None:
            title = task_description[:60] + ("..." if len(task_description) > 60 else "")

        exp = Experience(
            id=str(uuid.uuid4()),
            type=exp_type,
            level=level,
            title=title,
            tags=tags,
            problem=task_description,
            solution=solution_summary,
            key_decisions=key_decisions,
            confidence=0.6,
            status=ExperienceStatus.PENDING,
            source=ExperienceSource.AGENT,
            created_at=datetime.utcnow().isoformat(),
            related_files=related_files,
            metadata=ExperienceMetadata(
                tech_stack=tech_stack if tech_stack else tags,
                problem_type=exp_type.value,
                scene=scene,
            ),
            file_hashes=file_hashes,
            project=self._project,
        )

        exp = self._store.add(exp)

        if quality_score >= 80:
            exp.status = ExperienceStatus.ACTIVE
            exp.confidence = 0.65
            self._store.update(exp)

        from src.embeddings import get_provider
        provider = get_provider()
        exp_text = f"{exp.title}\n{exp.problem}\n{exp.key_decisions}"
        vec = provider.embed_text(exp_text)
        self._vector_store.save_vector(exp.id, vec)

        return exp

    async def _check_duplicate(self, task_description: str, solution_summary: str):
        from src.embeddings import get_provider, cosine_similarity
        import numpy as np

        all_ids, all_vecs = self._vector_store.get_all_vectors()
        if len(all_vecs) == 0:
            return

        provider = get_provider()
        query_vec = np.array(provider.embed_text(f"{task_description}\n{solution_summary}"), dtype=np.float32)

        scores = cosine_similarity(query_vec, all_vecs)
        max_score = float(np.max(scores)) if len(scores) > 0 else 0.0

        if max_score >= 0.85:
            best_idx = int(np.argmax(scores))
            exp_id = all_ids[best_idx]
            raise ValueError(
                f"已存在高度相似的经验（相似度 {max_score:.2f}）：[{exp_id[:8]}]。"
                f"建议复用或用 `xp edit {exp_id[:8]}` 更新已有经验，而非新增。"
            )
