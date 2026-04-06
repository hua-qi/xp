import pytest
from tests.helpers.fake_uow import InMemoryUnitOfWork


async def test_get_stats_fields_exist():
    from src.application.handlers.stats_handler import StatsHandler
    from src.application.commands import GetStatsCommand

    handler = StatsHandler(uow_factory=InMemoryUnitOfWork)
    stats = await handler.handle_get_stats(GetStatsCommand())

    assert "archived_count" in stats
    assert "type_distribution" in stats
    assert isinstance(stats["type_distribution"], dict)
    assert "avg_confidence" in stats
    assert "zombie_count" in stats
    assert "top_miss_queries" in stats
    assert "trend_30d" in stats
    assert "new_experiences" in stats["trend_30d"]
    assert "new_sessions" in stats["trend_30d"]


async def test_cmd_stats_no_crash(monkeypatch, capsys):
    from unittest.mock import patch, AsyncMock, MagicMock

    mock_bus = MagicMock()
    mock_bus.dispatch = AsyncMock(return_value={
        "session_total": 0,
        "result_shown": {"count": 0, "avg_iterations": 0.0, "error_rate": 0.0, "accept_rate": 0.0},
        "result_not_shown": {"count": 0, "avg_iterations": 0.0, "error_rate": 0.0, "accept_rate": 0.0},
        "active_count": 0, "pending_count": 0, "archived_count": 0,
        "type_distribution": {}, "avg_confidence": 0.0,
        "search_total": 0, "search_hit_rate": 0.0, "avg_result_count": 0.0,
        "query_adoption_rate": 0.0, "top_miss_queries": [],
        "review_confirmed": 0, "review_rejected": 0, "review_pass_rate": 0.0,
        "top_adopted_experiences": [], "zombie_count": 0,
        "trend_30d": {"new_experiences": 0, "new_sessions": 0},
    })

    with patch("src.cli._get_bus", AsyncMock(return_value=mock_bus)):
        from src.cli import cmd_stats
        await cmd_stats([])

    captured = capsys.readouterr()
    assert "效果对比" in captured.out
    assert "知识库状态" in captured.out
    assert "检索质量" in captured.out
    assert "经验价值分布" in captured.out
    assert "时间趋势" in captured.out


def test_get_stats_command_has_scope_filters():
    from src.application.commands import GetStatsCommand
    cmd = GetStatsCommand(
        since_days=7,
        project_id="proj-001",
        business_id="biz-001",
        team_id="team-001",
        compare=True,
    )
    assert cmd.project_id == "proj-001"
    assert cmd.business_id == "biz-001"
    assert cmd.team_id == "team-001"
    assert cmd.compare is True
