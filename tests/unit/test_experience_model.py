import pytest
from src.models import Experience, ExperienceType, ExperienceLevel, ExperienceStatus, ExperienceSource, ExperienceMetadata, ScopeType


def make_experience(**kwargs):
    defaults = dict(
        id="exp-001",
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L1,
        title="测试经验",
        tags=["python"],
        problem="问题描述",
        solution="解决方案，超过五十个字的详细描述以满足质量评分要求才行",
        key_decisions="关键决策，超过三十个字的描述以满足质量评分要求",
        confidence=0.65,
        status=ExperienceStatus.ACTIVE,
        source=ExperienceSource.AGENT,
        created_at="2026-05-04T00:00:00",
        metadata=ExperienceMetadata(),
    )
    defaults.update(kwargs)
    return Experience(**defaults)


class TestScopeType:
    def test_scope_type_enum_has_three_values(self):
        assert ScopeType.PROJECT.value == "project"
        assert ScopeType.BUSINESS.value == "business"
        assert ScopeType.TEAM.value == "team"


class TestExperienceNewFields:
    def test_experience_has_scope_type_field(self):
        exp = make_experience()
        assert exp.scope_type == ScopeType.PROJECT

    def test_experience_has_scope_id_field(self):
        exp = make_experience(scope_id="github.com/org/repo")
        assert exp.scope_id == "github.com/org/repo"

    def test_experience_scope_id_defaults_to_none(self):
        exp = make_experience()
        assert exp.scope_id is None

    def test_experience_has_promoted_to_field(self):
        exp = make_experience(promoted_to="exp-002")
        assert exp.promoted_to == "exp-002"

    def test_experience_promoted_to_defaults_to_none(self):
        exp = make_experience()
        assert exp.promoted_to is None

    def test_experience_has_demoted_from_field(self):
        exp = make_experience(demoted_from="exp-000")
        assert exp.demoted_from == "exp-000"

    def test_experience_demoted_from_defaults_to_none(self):
        exp = make_experience()
        assert exp.demoted_from is None

    def test_experience_has_recall_count_field(self):
        exp = make_experience(recall_count=5)
        assert exp.recall_count == 5

    def test_experience_recall_count_defaults_to_zero(self):
        exp = make_experience()
        assert exp.recall_count == 0

    def test_experience_has_adoption_rate_field(self):
        exp = make_experience(adoption_rate=0.72)
        assert exp.adoption_rate == 0.72

    def test_experience_adoption_rate_defaults_to_zero(self):
        exp = make_experience()
        assert exp.adoption_rate == 0.0
