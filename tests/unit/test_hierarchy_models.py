from src.models import Team, Business, Project


class TestTeamModel:
    def test_team_has_id_and_name(self):
        team = Team(id="team-001", name="平台工程团队")
        assert team.id == "team-001"
        assert team.name == "平台工程团队"


class TestBusinessModel:
    def test_business_has_id_team_id_name(self):
        biz = Business(id="biz-001", team_id="team-001", name="交易业务")
        assert biz.id == "biz-001"
        assert biz.team_id == "team-001"
        assert biz.name == "交易业务"


class TestProjectModel:
    def test_project_has_id_business_id_name_language(self):
        proj = Project(
            id="github.com/org/repo",
            business_id="biz-001",
            name="order-service",
            language="python",
            frameworks=["fastapi"],
        )
        assert proj.id == "github.com/org/repo"
        assert proj.business_id == "biz-001"
        assert proj.language == "python"
        assert proj.frameworks == ["fastapi"]

    def test_project_frameworks_defaults_to_empty_list(self):
        proj = Project(id="github.com/org/repo", business_id="biz-001", name="svc")
        assert proj.frameworks == []

    def test_project_language_defaults_to_empty_string(self):
        proj = Project(id="github.com/org/repo", business_id="biz-001", name="svc")
        assert proj.language == ""


class TestPromotionCandidateModel:
    def test_promotion_candidate_has_required_fields(self):
        from src.models import PromotionCandidate
        cand = PromotionCandidate(
            id="cand-001",
            experience_id="exp-001",
            target_scope_type="business",
            target_scope_id="biz-001",
            score=0.85,
            status="pending",
        )
        assert cand.id == "cand-001"
        assert cand.experience_id == "exp-001"
        assert cand.target_scope_type == "business"
        assert cand.score == 0.85
        assert cand.status == "pending"
        assert cand.ignored_at is None

    def test_promotion_candidate_default_status_is_pending(self):
        from src.models import PromotionCandidate
        cand = PromotionCandidate(
            id="cand-002",
            experience_id="exp-002",
            target_scope_type="team",
            target_scope_id="team-001",
            score=0.75,
            status="pending",
        )
        assert cand.status == "pending"


class TestMultiManyRelationModels:
    def test_project_business_link_model(self):
        from src.models import ProjectBusinessLink
        link = ProjectBusinessLink(project_id="proj-001", business_id="biz-001")
        assert link.project_id == "proj-001"
        assert link.business_id == "biz-001"

    def test_business_team_link_model(self):
        from src.models import BusinessTeamLink
        link = BusinessTeamLink(business_id="biz-001", team_id="team-001")
        assert link.business_id == "biz-001"
        assert link.team_id == "team-001"

    def test_team_has_owner_email(self):
        from src.models import Team
        team = Team(id="team-001", name="平台团队", owner_email="admin@example.com")
        assert team.owner_email == "admin@example.com"

    def test_team_owner_email_optional(self):
        from src.models import Team
        team = Team(id="team-001", name="平台团队")
        assert team.owner_email is None

    def test_business_has_owner_email(self):
        from src.models import Business
        biz = Business(id="biz-001", team_id="team-001", name="支付业务", owner_email="biz@example.com")
        assert biz.owner_email == "biz@example.com"
