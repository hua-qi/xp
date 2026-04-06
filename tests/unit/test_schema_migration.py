from src.infrastructure.backends.postgres import CREATE_SCHEMA_SQL


class TestSchemaMigration:
    def test_schema_has_teams_table(self):
        assert "CREATE TABLE IF NOT EXISTS teams" in CREATE_SCHEMA_SQL

    def test_schema_has_businesses_table(self):
        assert "CREATE TABLE IF NOT EXISTS businesses" in CREATE_SCHEMA_SQL

    def test_schema_has_projects_table(self):
        assert "CREATE TABLE IF NOT EXISTS projects" in CREATE_SCHEMA_SQL

    def test_schema_has_search_events_table(self):
        assert "CREATE TABLE IF NOT EXISTS search_events" in CREATE_SCHEMA_SQL

    def test_schema_has_feedback_events_table(self):
        assert "CREATE TABLE IF NOT EXISTS feedback_events" in CREATE_SCHEMA_SQL

    def test_experiences_table_has_scope_type_column(self):
        assert "scope_type" in CREATE_SCHEMA_SQL

    def test_experiences_table_has_scope_id_column(self):
        assert "scope_id" in CREATE_SCHEMA_SQL

    def test_experiences_table_has_promoted_to_column(self):
        assert "promoted_to" in CREATE_SCHEMA_SQL

    def test_experiences_table_has_demoted_from_column(self):
        assert "demoted_from" in CREATE_SCHEMA_SQL

    def test_experiences_table_has_recall_count_column(self):
        assert "recall_count" in CREATE_SCHEMA_SQL

    def test_experiences_table_has_adoption_rate_column(self):
        assert "adoption_rate" in CREATE_SCHEMA_SQL


def test_schema_sql_has_project_business_table():
    assert "project_business" in CREATE_SCHEMA_SQL

def test_schema_sql_has_business_team_table():
    assert "business_team" in CREATE_SCHEMA_SQL

def test_schema_sql_has_user_business_table():
    assert "user_business" in CREATE_SCHEMA_SQL

def test_schema_sql_has_promotion_candidates_table():
    assert "promotion_candidates" in CREATE_SCHEMA_SQL

def test_schema_sql_has_owner_email_in_teams():
    assert "owner_email" in CREATE_SCHEMA_SQL
