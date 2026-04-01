from src.models import ExperienceType, ExperienceLevel
from src.domain.metadata import infer_tech_stack, infer_scene, infer_type, infer_level


class TestInferTechStack:
    def test_react_hooks(self):
        assert "react" in infer_tech_stack("使用 useEffect 实现防抖")

    def test_python_fastapi(self):
        assert "python" in infer_tech_stack("用 fastapi 写 REST 接口")

    def test_empty_text(self):
        assert infer_tech_stack("") == []

    def test_multiple_techs(self):
        result = infer_tech_stack("typescript + react + docker")
        assert "typescript" in result
        assert "react" in result
        assert "docker" in result


class TestInferScene:
    def test_form_scene(self):
        assert "表单" in infer_scene("处理 form validation 逻辑")

    def test_async_scene(self):
        assert "异步" in infer_scene("async fetch 请求处理")

    def test_no_scene(self):
        assert infer_scene("xyzabc123") == []


class TestInferType:
    def test_bugfix(self):
        assert infer_type("修复 bug", "error 处理") == ExperienceType.BUGFIX

    def test_pattern(self):
        assert infer_type("架构模式", "设计规范") == ExperienceType.PATTERN

    def test_default_feature(self):
        assert infer_type("添加新功能", "实现步骤") == ExperienceType.FEATURE


class TestInferLevel:
    def test_l1(self):
        assert infer_level("整体架构设计", "架构选型") == ExperienceLevel.L1

    def test_l3(self):
        assert infer_level("修复 bug", "fix error exception") == ExperienceLevel.L3

    def test_l2_default(self):
        assert infer_level("普通功能", "实现") == ExperienceLevel.L2
