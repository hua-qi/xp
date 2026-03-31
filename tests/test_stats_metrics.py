import pytest
from src.storage import MetricsStore


def test_get_stats_new_fields_exist(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")

    store = MetricsStore()
    stats = store.get_stats()

    assert "avg_result_count" in stats
    assert "query_adoption_rate" in stats
    assert "top_adopted_experiences" in stats
    assert isinstance(stats["top_adopted_experiences"], list)
    assert "zombie_count_db" in stats
    assert "ab_test_groups" in stats
    assert "treatment" in stats["ab_test_groups"]
    assert "control" in stats["ab_test_groups"]
    assert "new_sessions_30d" in stats


def test_knowledge_get_stats_new_fields(tmp_path, monkeypatch):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")

    from src.storage import ExperienceStore, MetricsStore
    from src.knowledge import KnowledgeService

    service = KnowledgeService(ExperienceStore(), MetricsStore())
    stats = service.get_stats()

    assert "archived_count" in stats
    assert "type_distribution" in stats
    assert isinstance(stats["type_distribution"], dict)
    assert "avg_confidence" in stats
    assert "zombie_count" in stats
    assert "top_miss_queries" in stats
    assert "trend_30d" in stats
    assert "new_experiences" in stats["trend_30d"]
    assert "new_sessions" in stats["trend_30d"]


def test_cmd_stats_no_crash(tmp_path, monkeypatch, capsys):
    import src.storage as storage_mod
    monkeypatch.setattr(storage_mod, "XP_HOME", tmp_path)
    monkeypatch.setattr(storage_mod, "METRICS_DB", tmp_path / "metrics.db")
    monkeypatch.setattr(storage_mod, "KNOWLEDGE_FILE", tmp_path / "knowledge.json")

    from src.cli import cmd_stats
    cmd_stats([])

    captured = capsys.readouterr()
    assert "效果对比" in captured.out
    assert "知识库状态" in captured.out
    assert "检索质量" in captured.out
    assert "经验价值分布" in captured.out
    assert "时间趋势" in captured.out
