import pytest
from src.models import ExperienceType, ExperienceLevel


class TestTechStackInfer:
    def test_react_detected(self, svc):
        result = svc._infer_tech_stack("使用 useEffect 实现防抖")
        assert "react" in result

    def test_python_detected(self, svc):
        result = svc._infer_tech_stack("用 fastapi 写接口")
        assert "python" in result

    def test_no_match_returns_empty(self, svc):
        result = svc._infer_tech_stack("完全无关的文本xyzabc")
        assert result == []

    def test_multiple_techs(self, svc):
        result = svc._infer_tech_stack("用 typescript 和 react 写组件，部署用 docker")
        assert "react" in result
        assert "typescript" in result
        assert "docker" in result


class TestSceneInfer:
    def test_form_scene(self, svc):
        result = svc._infer_scene("处理表单 validation 逻辑")
        assert "表单" in result

    def test_async_scene(self, svc):
        result = svc._infer_scene("使用 async/await 处理 fetch 请求")
        assert "异步" in result

    def test_no_match_empty(self, svc):
        result = svc._infer_scene("完全无关内容zyxwvuts")
        assert result == []


class TestTypeInfer:
    def test_bugfix_type(self, svc):
        result = svc._infer_type("修复一个 bug", "error 处理")
        assert result == ExperienceType.BUGFIX

    def test_pattern_type(self, svc):
        result = svc._infer_type("设计模式", "architecture 规范")
        assert result == ExperienceType.PATTERN

    def test_default_feature(self, svc):
        result = svc._infer_type("新增功能", "实现步骤")
        assert result == ExperienceType.FEATURE


class TestLevelInfer:
    def test_l1_architecture(self, svc):
        result = svc._infer_level("整体架构设计", "架构选型")
        assert result == ExperienceLevel.L1

    def test_l3_bugfix(self, svc):
        result = svc._infer_level("修复 bug", "fix error")
        assert result == ExperienceLevel.L3

    def test_l2_default(self, svc):
        result = svc._infer_level("添加功能", "实现步骤")
        assert result == ExperienceLevel.L2
