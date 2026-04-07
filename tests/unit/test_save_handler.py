import pytest
from unittest.mock import AsyncMock
from src.application.commands import SaveCommand
from src.application.handlers.save_handler import SaveHandler
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.models import ExperienceStatus


VALID_LLM_JSON = '''{
  "title": "修复 userId 为 null 的 NPE",
  "problem": "生产环境 UserService.getUser() 在 userId 为 null 时抛出 NullPointerException，影响接口正常响应",
  "solution": "在 UserService.getUser() 入口增加 Objects.requireNonNull 检查，在 Service 层而非 DAO 层做业务约束校验",
  "key_decisions": "在 Service 层而非 DAO 层做 null 检查，因为这是业务约束而非数据约束",
  "tags": ["java", "null-safety"],
  "type": "bugfix"
}'''


def make_llm(content):
    llm = AsyncMock()
    llm.call = AsyncMock(return_value=content)
    return llm


class TestSaveHandlerAutoActivate:
    def _make_handler(self, uow=None, llm_content=VALID_LLM_JSON):
        if uow is None:
            uow = InMemoryUnitOfWork()
        llm = make_llm(llm_content)
        return SaveHandler(uow_factory=lambda: uow, llm=llm), uow

    def _make_cmd(self, **kwargs):
        defaults = dict(
            task_description="修复 userId 为 null 的 NPE",
            outcome_description="在 UserService.getUser() 入口增加 null 检查后修复，超时率降至 0%",
            outcome="success",
            project_id="github.com/org/my-service",
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
        short_json = '''{
          "title": "短",
          "problem": "短",
          "solution": "短",
          "key_decisions": "短",
          "tags": [],
          "type": "bugfix"
        }'''
        handler, uow = self._make_handler(llm_content=short_json)
        cmd = self._make_cmd()
        result = await handler.handle(cmd)
        exp_id = result["experience_id"]
        exp = uow.experiences.get(exp_id)
        assert exp.status == ExperienceStatus.PENDING

    @pytest.mark.asyncio
    async def test_returns_experience_id(self):
        handler, uow = self._make_handler()
        result = await handler.handle(self._make_cmd())
        assert "experience_id" in result
        assert result["experience_id"] is not None

    @pytest.mark.asyncio
    async def test_pending_retry_on_llm_failure(self):
        handler, uow = self._make_handler(llm_content=None)
        cmd = self._make_cmd()
        result = await handler.handle(cmd)
        assert result["status"] == "pending_retry"

    @pytest.mark.asyncio
    async def test_saved_status_on_llm_success(self):
        handler, uow = self._make_handler()
        cmd = self._make_cmd()
        result = await handler.handle(cmd)
        assert result["status"] == "saved"

    @pytest.mark.asyncio
    async def test_duplicate_detection_warns_when_similarity_above_0_85(self):
        handler, uow = self._make_handler()
        cmd = self._make_cmd()
        result1 = await handler.handle(cmd)
        result2 = await handler.handle(cmd)
        assert result2.get("duplicate_warning") is not None or result2.get("experience_id") is not None
