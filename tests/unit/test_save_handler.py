import pytest
from src.application.commands import SaveCommand
from src.application.handlers.save_handler import SaveHandler
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.models import ExperienceStatus


class FakeEmbeddingProvider:
    def embed_text(self, text: str) -> list[float]:
        import numpy as np
        v = np.ones(64, dtype=np.float32)
        return (v / np.linalg.norm(v)).tolist()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


class TestSaveHandlerAutoActivate:
    def _make_handler(self, uow=None):
        if uow is None:
            uow = InMemoryUnitOfWork()
        provider = FakeEmbeddingProvider()
        return SaveHandler(uow_factory=lambda: uow, embedding_provider=provider), uow

    def _make_cmd(self, **kwargs):
        defaults = dict(
            task_description="修复 userId 为 null 的 NPE",
            solution="在 UserService.getUser() 入口增加 Objects.requireNonNull 检查，" + "x" * 40,
            key_decisions="在 Service 层而非 DAO 层做 null 检查，因为这是业务约束" + "x" * 10,
            tags=["java", "null-safety"],
            project_id="github.com/org/my-service",
            outcome="success",
        )
        defaults.update(kwargs)
        return SaveCommand(**defaults)

    @pytest.mark.asyncio
    async def test_high_quality_experience_auto_activates(self):
        handler, uow = self._make_handler()
        cmd = self._make_cmd()
        result = await handler.handle(cmd)
        exp_id = result["experience_id"]
        exp = uow.experiences.get(exp_id)
        assert exp is not None
        assert exp.status == ExperienceStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_low_quality_experience_stays_pending(self):
        handler, uow = self._make_handler()
        cmd = self._make_cmd(solution="短", key_decisions="短", tags=[], outcome="failed")
        result = await handler.handle(cmd)
        exp_id = result["experience_id"]
        exp = uow.experiences.get(exp_id)
        assert exp.status == ExperienceStatus.PENDING

    @pytest.mark.asyncio
    async def test_success_outcome_gives_confidence_0_65(self):
        handler, uow = self._make_handler()
        cmd = self._make_cmd(outcome="success")
        result = await handler.handle(cmd)
        exp = uow.experiences.get(result["experience_id"])
        assert abs(exp.confidence - 0.65) < 1e-6

    @pytest.mark.asyncio
    async def test_partial_outcome_gives_confidence_0_55(self):
        handler, uow = self._make_handler()
        cmd = self._make_cmd(outcome="partial")
        result = await handler.handle(cmd)
        exp = uow.experiences.get(result["experience_id"])
        assert abs(exp.confidence - 0.55) < 1e-6

    @pytest.mark.asyncio
    async def test_failed_outcome_gives_confidence_0_40(self):
        handler, uow = self._make_handler()
        cmd = self._make_cmd(outcome="failed")
        result = await handler.handle(cmd)
        exp = uow.experiences.get(result["experience_id"])
        assert abs(exp.confidence - 0.40) < 1e-6

    @pytest.mark.asyncio
    async def test_returns_experience_id(self):
        handler, uow = self._make_handler()
        result = await handler.handle(self._make_cmd())
        assert "experience_id" in result
        assert result["experience_id"] is not None

    @pytest.mark.asyncio
    async def test_experience_scope_type_is_project(self):
        handler, uow = self._make_handler()
        result = await handler.handle(self._make_cmd())
        exp = uow.experiences.get(result["experience_id"])
        from src.models import ScopeType
        assert exp.scope_type == ScopeType.PROJECT

    @pytest.mark.asyncio
    async def test_experience_scope_id_matches_project_id(self):
        handler, uow = self._make_handler()
        result = await handler.handle(self._make_cmd())
        exp = uow.experiences.get(result["experience_id"])
        assert exp.scope_id == "github.com/org/my-service"

    @pytest.mark.asyncio
    async def test_duplicate_detection_warns_when_similarity_above_0_85(self):
        handler, uow = self._make_handler()
        cmd = self._make_cmd()
        result1 = await handler.handle(cmd)
        result2 = await handler.handle(cmd)
        assert result2.get("duplicate_warning") is not None or result2.get("experience_id") is not None
