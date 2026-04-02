import pytest


def _make_setup(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")


def test_finalize_task_extract_fails_session_still_runs(tmp_path, monkeypatch):
    _make_setup(tmp_path, monkeypatch)
    from src.embeddings import EmbeddingProvider, set_provider
    from src.application.handlers.extract_handler import ExtractHandler
    from src.application.handlers.session_handler import SessionHandler
    from src.application.commands import ExtractExperienceCommand, RecordSessionCommand
    from src.infrastructure.unit_of_work import UnitOfWork

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())

    extract_handler = ExtractHandler(uow_factory=UnitOfWork)
    session_handler = SessionHandler(uow_factory=UnitOfWork)

    result = {"extract": {"status": "skipped", "id": None, "reason": None}, "session": {"status": "skipped"}}

    try:
        exp = extract_handler.handle_extract(ExtractExperienceCommand(
            task_description="测试任务",
            solution_summary="解决方案摘要超过二十个字符的内容",
            key_decisions="短",
            final_response="最终回复内容",
        ))
        result["extract"] = {"status": "ok", "id": exp.id, "reason": None}
    except Exception as e:
        result["extract"] = {"status": "skipped", "id": None, "reason": str(e)}

    try:
        session_handler.handle_record_session(RecordSessionCommand(
            session_id="test-session-001",
            task_description="测试任务",
        ))
        result["session"] = {"status": "ok"}
    except Exception as e:
        result["session"] = {"status": "error", "reason": str(e)}

    assert result["extract"]["status"] == "skipped"
    assert result["session"]["status"] == "ok"


def test_finalize_task_all_steps_succeed(tmp_path, monkeypatch):
    _make_setup(tmp_path, monkeypatch)
    from src.embeddings import EmbeddingProvider, set_provider
    from src.application.handlers.extract_handler import ExtractHandler
    from src.application.handlers.session_handler import SessionHandler
    from src.application.commands import ExtractExperienceCommand, RecordSessionCommand
    from src.infrastructure.unit_of_work import UnitOfWork

    class FakeProvider(EmbeddingProvider):
        def embed_texts(self, texts):
            return [[0.1] * 64 for _ in texts]

    set_provider(FakeProvider())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("XP_LLM_API_KEY", raising=False)

    extract_handler = ExtractHandler(uow_factory=UnitOfWork)
    session_handler = SessionHandler(uow_factory=UnitOfWork)

    result = {"extract": {"status": "skipped", "id": None}, "session": {"status": "skipped"}}

    try:
        exp = extract_handler.handle_extract(ExtractExperienceCommand(
            task_description="修复登录后状态不保持的 bug，需要在 token 过期时自动刷新",
            solution_summary="在 token 过期时自动刷新，并存入 localStorage，确保状态持久化",
            key_decisions="不要在 useEffect 里直接调用 setState，会导致无限循环",
        ))
        result["extract"] = {"status": "ok", "id": exp.id}
    except Exception as e:
        result["extract"] = {"status": "skipped", "id": None, "reason": str(e)}

    try:
        session_handler.handle_record_session(RecordSessionCommand(
            session_id="test-session-002",
            task_description="修复登录后状态不保持的 bug",
        ))
        result["session"] = {"status": "ok"}
    except Exception as e:
        result["session"] = {"status": "error", "reason": str(e)}

    assert result["extract"]["status"] == "ok"
    assert result["extract"]["id"] is not None
    assert result["session"]["status"] == "ok"


def test_server_finalize_task_extract_fails_session_recorded(tmp_path, monkeypatch):
    pytest.skip("depends on mcp module not installed")
