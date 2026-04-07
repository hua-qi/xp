from pathlib import Path

SCHEMA_FILE = Path("src/infrastructure/backends/mysql_schema.sql")


def test_schema_file_exists():
    assert SCHEMA_FILE.exists()


def test_schema_contains_required_tables():
    sql = SCHEMA_FILE.read_text()
    for table in ["experiences", "sessions", "feedbacks", "conflict_reviews",
                  "correction_requests", "prompt_configs", "experience_stats"]:
        assert table in sql, f"Missing table: {table}"


def test_schema_experiences_has_embedding_column():
    sql = SCHEMA_FILE.read_text()
    assert "embedding" in sql


def test_schema_experiences_has_ab_group_column():
    sql = SCHEMA_FILE.read_text()
    assert "ab_group" in sql
