import pytest


def test_migration_tests_removed():
    pytest.skip("Local file migration no longer supported; PostgreSQL is the only backend")
