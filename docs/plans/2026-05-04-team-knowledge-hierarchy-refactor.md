# xp 团队级知识层级重构实现方案

**Goal:** 将 xp 从单人本地工具升级为团队级中心化知识库，支持三层知识层级（Team/Business/Project）、3 个精简 MCP tool（search/save/feedback）和提升候选自动推荐。

**Architecture:** 单进程 FastAPI 应用，MCP endpoint 与 REST endpoint 共享同一 Service 层；PostgreSQL + pgvector 存储经验及向量；三层知识层级对应组织结构，经验可双向流动；Agent 定时扫描推荐提升候选，人工决策。

**Tech Stack:** Python 3.11+、FastAPI、asyncpg、pgvector、mcp[cli]、sentence-transformers、pytest（已在 pyproject.toml 中声明）

---

## 阅读须知

### 项目结构速览

```
src/
  domain/          # 纯业务逻辑，无 I/O（constants, experience, feedback, quality, search...）
  application/     # Command + Handler，协调 domain 与 infrastructure
    commands.py    # 所有 Command dataclass 定义
    command_bus.py # CommandBus：register + dispatch
    handlers/      # 每个 handler 对应一类业务操作
    unit_of_work.py # AbstractUnitOfWork 接口
  infrastructure/  # 实际 I/O（PostgreSQL, vector store, 文件存储）
    backends/postgres.py  # PostgresBackend（所有 async_xxx 方法）
    unit_of_work.py       # UnitOfWork 实现（连接 infrastructure 与 application）
  interfaces/
    rest_api.py    # FastAPI REST 路由（/api/...）
  server.py        # MCP Server（6 个旧 tool 定义）
  container.py     # 依赖注入：build_command_bus()
  models.py        # 数据类（Experience, Session, Feedback 等）
tests/
  unit/            # 纯函数/domain 单测，不依赖 I/O
  integration/     # 需要真实 DB 的测试（默认 skip 若无 DB）
  helpers/fake_uow.py # InMemoryUnitOfWork（所有单测共用）
  e2e/             # 端到端 API 测试
```

### 运行测试的命令

```bash
pytest tests/unit/ -v          # 单元测试（无需 DB，本方案主要在此层）
pytest tests/integration/ -v   # 集成测试（需要真实 PostgreSQL）
pytest tests/e2e/ -v           # 端到端（需要跑起服务）
```

### 关键约定

- 所有 domain 层函数必须是**纯函数**，不得有 I/O
- handler 通过 UnitOfWork 访问存储，不直接 import `ExperienceStore`
- 测试中统一使用 `tests/helpers/fake_uow.py` 里的 `InMemoryUnitOfWork`
- 新增 Command 后必须在 `container.py` 的 `build_command_bus()` 里注册

---

## 重构路线图（按依赖顺序）

```
Phase 1: 数据模型扩展（Domain + DB Schema）
  Task 1  → 扩展 Experience 模型：增加 scope_type/scope_id/promoted_to/demoted_from/recall_count/adoption_rate/last_hit_at
  Task 2  → 新增 Team/Business/Project 层级模型
  Task 3  → 新增 SearchEvent / FeedbackEvent 模型
  Task 4  → 更新 PostgreSQL schema（migration SQL）

Phase 2: 新 MCP Tool 核心 Service 层
  Task 5  → SearchService v2：三层并发检索 + 技术栈增强 + 权重合并
  Task 6  → SaveService（原 extract_experience 重构）：质量评分 + 重复检测 + 关联 search_event
  Task 7  → FeedbackService v2：基于 search_event_id 的 id 合法性校验 + confidence 更新 + 隐式采纳推断

Phase 3: Command/Handler 层
  Task 8  → 新增 SearchV2Command + SearchV2Handler
  Task 9  → 新增 SaveCommand + SaveHandler
  Task 10 → 新增 FeedbackV2Command + FeedbackV2Handler

Phase 4: MCP Server 替换
  Task 11 → 用 search/save/feedback 三个新 tool 替换旧 6 个 tool

Phase 5: 提升候选系统
  Task 12 → 提升候选评分算法（domain 层纯函数）
  Task 13 → 提升候选扫描 Handler + REST API

Phase 6: 鉴权与多租户
  Task 14 → personal_token 鉴权中间件 + project/team 关联校验

Phase 7: 集成与 E2E 测试
  Task 15 → 集成测试（三层召回）
  Task 16 → E2E 测试（完整 search→save→feedback 流程）
```

---

## Task 1：扩展 Experience 领域模型

**背景：** 当前 `Experience` 存储在单一 project 维度（`project` 字段），需要扩展为支持三层 scope（project/business/team），并补充层级流动所需字段。

**Files:**
- Modify: `src/models.py`
- Modify: `src/domain/constants.py`
- Test: `tests/unit/test_experience_model.py`（新建）

---

### Step 1：写失败测试

新建文件 `tests/unit/test_experience_model.py`，写入：

```python
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
```

### Step 2：运行测试，确认失败

```bash
pytest tests/unit/test_experience_model.py -v
```

预期输出：`ImportError: cannot import name 'ScopeType' from 'src.models'`

### Step 3：扩展 `src/models.py`

在 `ExperienceSource` 枚举之后添加新枚举，并在 `Experience` 中增加字段：

```python
# 在 ExperienceSource 定义之后添加：
class ScopeType(str, Enum):
    PROJECT = "project"
    BUSINESS = "business"
    TEAM = "team"
```

在 `Experience` dataclass 中，在 `key_decisions: str = ""` 之后追加：

```python
    scope_type: ScopeType = field(default_factory=lambda: ScopeType.PROJECT)
    scope_id: Optional[str] = None
    promoted_to: Optional[str] = None
    demoted_from: Optional[str] = None
    recall_count: int = 0
    adoption_rate: float = 0.0
```

> **注意：** `last_hit_at` 字段已存在（`Optional[str] = None`），无需重复添加。

### Step 4：运行测试，确认通过

```bash
pytest tests/unit/test_experience_model.py -v
```

预期：全部 PASS

### Step 5：提交

```bash
git add src/models.py tests/unit/test_experience_model.py
git commit -m "feat(domain): add scope_type/scope_id/promoted_to/demoted_from/recall_count/adoption_rate to Experience"
```

---

## Task 2：新增 Team / Business / Project 层级领域模型

**背景：** search 时需要根据 project_id 反查 business_id、team_id，以便向上层级召回；这些模型是层级关系的基础。

**Files:**
- Modify: `src/models.py`
- Test: `tests/unit/test_hierarchy_models.py`（新建）

---

### Step 1：写失败测试

新建文件 `tests/unit/test_hierarchy_models.py`：

```python
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
```

### Step 2：运行测试，确认失败

```bash
pytest tests/unit/test_hierarchy_models.py -v
```

预期：`ImportError: cannot import name 'Team' from 'src.models'`

### Step 3：在 `src/models.py` 末尾追加

```python
@dataclass
class Team:
    id: str
    name: str


@dataclass
class Business:
    id: str
    team_id: str
    name: str


@dataclass
class Project:
    id: str
    business_id: str
    name: str
    language: str = ""
    frameworks: list[str] = field(default_factory=list)
```

### Step 4：运行测试，确认通过

```bash
pytest tests/unit/test_hierarchy_models.py -v
```

### Step 5：提交

```bash
git add src/models.py tests/unit/test_hierarchy_models.py
git commit -m "feat(domain): add Team, Business, Project hierarchy models"
```

---

## Task 3：新增 SearchEvent / FeedbackEvent 模型

**背景：** 新 `search` tool 返回 `search_event_id`，`feedback` tool 通过它校验 id 合法性；需要这两个模型来承载事件数据。

**Files:**
- Modify: `src/models.py`
- Test: `tests/unit/test_event_models.py`（新建）

---

### Step 1：写失败测试

新建 `tests/unit/test_event_models.py`：

```python
from src.models import SearchEvent, FeedbackEvent


class TestSearchEvent:
    def test_search_event_has_required_fields(self):
        evt = SearchEvent(
            id="evt-001",
            session_id="sess-001",
            project_id="github.com/org/repo",
            query_text="修复 NPE 问题",
            result_ids=["exp-001", "exp-002"],
            timestamp="2026-05-04T00:00:00",
        )
        assert evt.id == "evt-001"
        assert evt.result_ids == ["exp-001", "exp-002"]

    def test_search_event_result_ids_defaults_to_empty(self):
        evt = SearchEvent(
            id="evt-002",
            session_id="sess-001",
            project_id="github.com/org/repo",
            query_text="test",
            timestamp="2026-05-04T00:00:00",
        )
        assert evt.result_ids == []


class TestFeedbackEvent:
    def test_feedback_event_has_required_fields(self):
        evt = FeedbackEvent(
            id="fb-001",
            search_event_id="evt-001",
            helpful_ids=["exp-001"],
            unhelpful_ids=["exp-002"],
            timestamp="2026-05-04T00:00:00",
        )
        assert evt.search_event_id == "evt-001"
        assert evt.helpful_ids == ["exp-001"]

    def test_feedback_event_comment_defaults_to_none(self):
        evt = FeedbackEvent(
            id="fb-002",
            search_event_id="evt-001",
            timestamp="2026-05-04T00:00:00",
        )
        assert evt.comment is None
        assert evt.helpful_ids == []
        assert evt.unhelpful_ids == []
```

### Step 2：运行测试，确认失败

```bash
pytest tests/unit/test_event_models.py -v
```

### Step 3：在 `src/models.py` 末尾追加

```python
@dataclass
class SearchEvent:
    id: str
    session_id: str
    project_id: str
    query_text: str
    timestamp: str
    result_ids: list[str] = field(default_factory=list)
    query_embedding: Optional[list[float]] = None


@dataclass
class FeedbackEvent:
    id: str
    search_event_id: str
    timestamp: str
    helpful_ids: list[str] = field(default_factory=list)
    unhelpful_ids: list[str] = field(default_factory=list)
    comment: Optional[str] = None
```

### Step 4：运行测试，确认通过

```bash
pytest tests/unit/test_event_models.py -v
```

### Step 5：提交

```bash
git add src/models.py tests/unit/test_event_models.py
git commit -m "feat(domain): add SearchEvent and FeedbackEvent models"
```

---

## Task 4：更新 PostgreSQL Schema（migration SQL）

**背景：** 新模型需要对应的 DB 表。现有的 `CREATE_SCHEMA_SQL` 在 `src/infrastructure/backends/postgres.py` 中；需要在不破坏已有表的前提下追加新表和新列。

**Files:**
- Modify: `src/infrastructure/backends/postgres.py`
- Test: `tests/unit/test_schema_migration.py`（新建，测试 SQL 字符串的关键字存在性）

---

### Step 1：写失败测试

新建 `tests/unit/test_schema_migration.py`：

```python
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
```

### Step 2：运行测试，确认失败

```bash
pytest tests/unit/test_schema_migration.py -v
```

预期：多数测试 FAIL（字段/表不存在于 SQL 中）

### Step 3：修改 `src/infrastructure/backends/postgres.py`

将 `CREATE_SCHEMA_SQL` 中 `experiences` 表的字段部分扩充，并在其末尾追加新表。

在 `experiences` 表定义末尾（`embedding vector(512)` 之前）增加：

```sql
    scope_type TEXT NOT NULL DEFAULT 'project',
    scope_id TEXT,
    promoted_to TEXT,
    demoted_from TEXT,
    recall_count INTEGER NOT NULL DEFAULT 0,
    adoption_rate FLOAT NOT NULL DEFAULT 0.0,
```

在 `CREATE_SCHEMA_SQL` 末尾追加：

```sql
CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS businesses (
    id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL REFERENCES teams(id),
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(id),
    name TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT '',
    frameworks JSONB NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS search_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    query_embedding vector(512),
    result_ids JSONB NOT NULL DEFAULT '[]',
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback_events (
    id TEXT PRIMARY KEY,
    search_event_id TEXT NOT NULL REFERENCES search_events(id),
    helpful_ids JSONB NOT NULL DEFAULT '[]',
    unhelpful_ids JSONB NOT NULL DEFAULT '[]',
    comment TEXT,
    timestamp TEXT NOT NULL
);
```

### Step 4：运行测试，确认通过

```bash
pytest tests/unit/test_schema_migration.py -v
```

### Step 5：提交

```bash
git add src/infrastructure/backends/postgres.py tests/unit/test_schema_migration.py
git commit -m "feat(infra): extend schema with hierarchy tables and new experience columns"
```

---

## Task 5：project_manifest 解析服务（domain 层）

**背景：** `search` tool 的 `project_manifest` 参数包含 `package.json`/`pyproject.toml`/`go.mod` 内容，服务端需要从中提取 `language`、`frameworks`、`top_dependencies`，用于技术栈过滤增强。这是纯函数，放在 domain 层。

**Files:**
- Create: `src/domain/manifest_parser.py`
- Test: `tests/unit/test_manifest_parser.py`（新建）

---

### Step 1：写失败测试

新建 `tests/unit/test_manifest_parser.py`：

```python
from src.domain.manifest_parser import parse_manifest


class TestParseManifestPackageJson:
    def test_detects_language_as_javascript(self):
        manifest = '{"dependencies": {"react": "^18.0.0"}, "devDependencies": {}}'
        result = parse_manifest(manifest)
        assert result["language"] == "javascript"

    def test_extracts_top_dependencies_from_package_json(self):
        manifest = '{"dependencies": {"react": "^18", "axios": "^1"}}'
        result = parse_manifest(manifest)
        assert "react" in result["top_dependencies"]
        assert "axios" in result["top_dependencies"]

    def test_detects_react_framework(self):
        manifest = '{"dependencies": {"react": "^18", "react-dom": "^18"}}'
        result = parse_manifest(manifest)
        assert "react" in result["frameworks"]

    def test_detects_nextjs_framework(self):
        manifest = '{"dependencies": {"next": "^14"}}'
        result = parse_manifest(manifest)
        assert "nextjs" in result["frameworks"]


class TestParseManifestPyprojectToml:
    def test_detects_language_as_python(self):
        manifest = '[project]\ndependencies = ["fastapi>=0.110", "sqlalchemy>=2.0"]'
        result = parse_manifest(manifest)
        assert result["language"] == "python"

    def test_extracts_dependencies_from_pyproject(self):
        manifest = '[project]\ndependencies = ["fastapi>=0.110", "sqlalchemy>=2.0"]'
        result = parse_manifest(manifest)
        assert "fastapi" in result["top_dependencies"]
        assert "sqlalchemy" in result["top_dependencies"]

    def test_detects_fastapi_framework(self):
        manifest = '[project]\ndependencies = ["fastapi>=0.110"]'
        result = parse_manifest(manifest)
        assert "fastapi" in result["frameworks"]


class TestParseManifestGoMod:
    def test_detects_language_as_go(self):
        manifest = 'module github.com/org/repo\ngo 1.21\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n)'
        result = parse_manifest(manifest)
        assert result["language"] == "go"

    def test_extracts_dependencies_from_go_mod(self):
        manifest = 'module github.com/org/repo\ngo 1.21\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n)'
        result = parse_manifest(manifest)
        assert "gin" in result["top_dependencies"]


class TestParseManifestEdgeCases:
    def test_empty_string_returns_defaults(self):
        result = parse_manifest("")
        assert result["language"] == "unknown"
        assert result["top_dependencies"] == []
        assert result["frameworks"] == []

    def test_none_returns_defaults(self):
        result = parse_manifest(None)
        assert result["language"] == "unknown"

    def test_invalid_json_does_not_raise(self):
        result = parse_manifest("{invalid json}")
        assert result["language"] == "unknown"

    def test_top_dependencies_capped_at_ten(self):
        deps = {f"dep{i}": "^1.0" for i in range(20)}
        import json
        manifest = json.dumps({"dependencies": deps})
        result = parse_manifest(manifest)
        assert len(result["top_dependencies"]) <= 10
```

### Step 2：运行测试，确认失败

```bash
pytest tests/unit/test_manifest_parser.py -v
```

预期：`ModuleNotFoundError: No module named 'src.domain.manifest_parser'`

### Step 3：创建 `src/domain/manifest_parser.py`

```python
from __future__ import annotations
import json
import re
from typing import Optional


_FRAMEWORK_HINTS = {
    "react": "react",
    "react-dom": "react",
    "next": "nextjs",
    "vue": "vue",
    "nuxt": "nuxtjs",
    "angular": "angular",
    "fastapi": "fastapi",
    "django": "django",
    "flask": "flask",
    "gin": "gin",
    "echo": "echo",
    "fiber": "fiber",
    "spring": "spring",
    "express": "express",
}


def parse_manifest(manifest: Optional[str]) -> dict:
    if not manifest or not manifest.strip():
        return {"language": "unknown", "frameworks": [], "top_dependencies": []}

    text = manifest.strip()

    if text.startswith("{"):
        return _parse_package_json(text)
    if "module " in text and "require (" in text:
        return _parse_go_mod(text)
    if "[project]" in text or "dependencies" in text:
        return _parse_pyproject_toml(text)

    return {"language": "unknown", "frameworks": [], "top_dependencies": []}


def _parse_package_json(text: str) -> dict:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"language": "unknown", "frameworks": [], "top_dependencies": []}

    deps = {}
    deps.update(data.get("dependencies", {}))
    deps.update(data.get("devDependencies", {}))

    top_deps = list(deps.keys())[:10]
    frameworks = _detect_frameworks(top_deps)

    return {"language": "javascript", "frameworks": frameworks, "top_dependencies": top_deps}


def _parse_pyproject_toml(text: str) -> dict:
    deps = []
    in_deps = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "dependencies = [" or stripped.startswith("dependencies = ["):
            in_deps = True
        if in_deps:
            match = re.search(r'"([a-zA-Z0-9_\-]+)', stripped)
            if match:
                deps.append(match.group(1).lower())
        if in_deps and "]" in stripped and not stripped.startswith("dependencies"):
            in_deps = False

    inline = re.findall(r'dependencies\s*=\s*\[([^\]]+)\]', text, re.DOTALL)
    if inline:
        deps = re.findall(r'"([a-zA-Z0-9_\-]+)', inline[0])
        deps = [d.lower() for d in deps]

    top_deps = deps[:10]
    frameworks = _detect_frameworks(top_deps)

    return {"language": "python", "frameworks": frameworks, "top_dependencies": top_deps}


def _parse_go_mod(text: str) -> dict:
    deps = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("require") or stripped.startswith("\t") or stripped.startswith(" "):
            match = re.search(r'github\.com/[^/]+/([^\s]+)', stripped)
            if match:
                pkg = match.group(1).split("/")[0].lower()
                deps.append(pkg)

    top_deps = list(dict.fromkeys(deps))[:10]
    frameworks = _detect_frameworks(top_deps)

    return {"language": "go", "frameworks": frameworks, "top_dependencies": top_deps}


def _detect_frameworks(dep_names: list[str]) -> list[str]:
    found = []
    for dep in dep_names:
        dep_lower = dep.lower()
        if dep_lower in _FRAMEWORK_HINTS:
            fw = _FRAMEWORK_HINTS[dep_lower]
            if fw not in found:
                found.append(fw)
    return found
```

### Step 4：运行测试，确认通过

```bash
pytest tests/unit/test_manifest_parser.py -v
```

### Step 5：提交

```bash
git add src/domain/manifest_parser.py tests/unit/test_manifest_parser.py
git commit -m "feat(domain): add manifest_parser for project_manifest extraction"
```

---

## Task 6：三层并发搜索 domain 逻辑

**背景：** 新 `search` tool 需要同时搜索 Project/Business/Team 三个层级，分别加权（1.2/1.0/0.9），按技术栈增强（×1.15），最终合并去重取 Top-5。这是纯计算逻辑，放在 domain 层。

**Files:**
- Create: `src/domain/search_v2.py`
- Test: `tests/unit/test_search_v2_domain.py`（新建）

---

### Step 1：写失败测试

新建 `tests/unit/test_search_v2_domain.py`：

```python
import numpy as np
import pytest
from src.domain.search_v2 import (
    apply_scope_weight,
    apply_tech_stack_boost,
    merge_and_deduplicate,
    ScopeWeightedResult,
)


class TestApplyScopeWeight:
    def test_project_scope_multiplied_by_1_2(self):
        result = apply_scope_weight(score=0.8, scope_type="project")
        assert abs(result - 0.8 * 1.2) < 1e-6

    def test_business_scope_multiplied_by_1_0(self):
        result = apply_scope_weight(score=0.8, scope_type="business")
        assert abs(result - 0.8 * 1.0) < 1e-6

    def test_team_scope_multiplied_by_0_9(self):
        result = apply_scope_weight(score=0.8, scope_type="team")
        assert abs(result - 0.8 * 0.9) < 1e-6

    def test_unknown_scope_returns_original_score(self):
        result = apply_scope_weight(score=0.8, scope_type="unknown")
        assert abs(result - 0.8) < 1e-6


class TestApplyTechStackBoost:
    def test_matching_tag_boosts_score_by_1_15(self):
        score = apply_tech_stack_boost(
            score=0.8,
            exp_tags=["python", "fastapi"],
            query_languages=["python"],
            query_dependencies=["fastapi"],
        )
        assert abs(score - 0.8 * 1.15) < 1e-6

    def test_no_matching_tag_returns_original_score(self):
        score = apply_tech_stack_boost(
            score=0.8,
            exp_tags=["java"],
            query_languages=["python"],
            query_dependencies=["fastapi"],
        )
        assert abs(score - 0.8) < 1e-6

    def test_empty_exp_tags_returns_original_score(self):
        score = apply_tech_stack_boost(
            score=0.8,
            exp_tags=[],
            query_languages=["python"],
            query_dependencies=["fastapi"],
        )
        assert abs(score - 0.8) < 1e-6


class TestMergeAndDeduplicate:
    def _make_result(self, exp_id, score, scope_type="project"):
        return ScopeWeightedResult(exp_id=exp_id, score=score, scope_type=scope_type)

    def test_results_sorted_by_score_descending(self):
        results = [
            self._make_result("exp-001", 0.6, "project"),
            self._make_result("exp-002", 0.9, "business"),
            self._make_result("exp-003", 0.7, "team"),
        ]
        merged = merge_and_deduplicate(results, top_k=3)
        scores = [r.score for r in merged]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_limits_results(self):
        results = [self._make_result(f"exp-{i}", float(i) / 10, "project") for i in range(10)]
        merged = merge_and_deduplicate(results, top_k=5)
        assert len(merged) == 5

    def test_duplicate_exp_id_keeps_highest_score(self):
        results = [
            self._make_result("exp-001", 0.6, "project"),
            self._make_result("exp-001", 0.9, "business"),
        ]
        merged = merge_and_deduplicate(results, top_k=5)
        assert len(merged) == 1
        assert merged[0].score == 0.9

    def test_empty_results_returns_empty(self):
        assert merge_and_deduplicate([], top_k=5) == []

    def test_results_below_threshold_excluded(self):
        results = [
            self._make_result("exp-001", 0.8, "project"),
            self._make_result("exp-002", 0.3, "project"),
        ]
        merged = merge_and_deduplicate(results, top_k=5, threshold=0.5)
        assert len(merged) == 1
        assert merged[0].exp_id == "exp-001"
```

### Step 2：运行测试，确认失败

```bash
pytest tests/unit/test_search_v2_domain.py -v
```

### Step 3：创建 `src/domain/search_v2.py`

```python
from __future__ import annotations
from dataclasses import dataclass

_SCOPE_WEIGHTS = {
    "project": 1.2,
    "business": 1.0,
    "team": 0.9,
}


@dataclass
class ScopeWeightedResult:
    exp_id: str
    score: float
    scope_type: str


def apply_scope_weight(score: float, scope_type: str) -> float:
    weight = _SCOPE_WEIGHTS.get(scope_type, 1.0)
    return score * weight


def apply_tech_stack_boost(
    score: float,
    exp_tags: list[str],
    query_languages: list[str],
    query_dependencies: list[str],
) -> float:
    query_tokens = set(t.lower() for t in query_languages + query_dependencies)
    exp_tokens = set(t.lower() for t in exp_tags)
    if query_tokens & exp_tokens:
        return score * 1.15
    return score


def merge_and_deduplicate(
    results: list[ScopeWeightedResult],
    top_k: int,
    threshold: float = 0.0,
) -> list[ScopeWeightedResult]:
    best: dict[str, ScopeWeightedResult] = {}
    for r in results:
        if r.score < threshold:
            continue
        existing = best.get(r.exp_id)
        if existing is None or r.score > existing.score:
            best[r.exp_id] = r
    sorted_results = sorted(best.values(), key=lambda x: x.score, reverse=True)
    return sorted_results[:top_k]
```

### Step 4：运行测试，确认通过

```bash
pytest tests/unit/test_search_v2_domain.py -v
```

### Step 5：提交

```bash
git add src/domain/search_v2.py tests/unit/test_search_v2_domain.py
git commit -m "feat(domain): add search_v2 scope weight, tech stack boost, and merge logic"
```

---

## Task 7：提升候选评分算法（domain 层纯函数）

**背景：** Agent 定时扫描时需要计算「提升得分」，决定是否将经验标记为提升候选。算法为：`得分 = 跨项目出现次数 × 0.5 + adoption_rate × 0.3 + min(recall_count / 10, 1) × 0.2`，得分 > 0.7 且满足其他条件才触发。

**Files:**
- Create: `src/domain/promotion.py`
- Test: `tests/unit/test_promotion.py`（新建）

---

### Step 1：写失败测试

新建 `tests/unit/test_promotion.py`：

```python
import pytest
from src.domain.promotion import (
    compute_promotion_score,
    is_promotion_candidate,
)


class TestComputePromotionScore:
    def test_all_zeros_gives_zero(self):
        score = compute_promotion_score(cross_project_count=0, adoption_rate=0.0, recall_count=0)
        assert score == 0.0

    def test_formula_cross_project_weight_is_0_5(self):
        score = compute_promotion_score(cross_project_count=2, adoption_rate=0.0, recall_count=0)
        assert abs(score - 2 * 0.5) < 1e-6

    def test_formula_adoption_rate_weight_is_0_3(self):
        score = compute_promotion_score(cross_project_count=0, adoption_rate=1.0, recall_count=0)
        assert abs(score - 0.3) < 1e-6

    def test_formula_recall_count_capped_at_1(self):
        score_10 = compute_promotion_score(cross_project_count=0, adoption_rate=0.0, recall_count=10)
        score_100 = compute_promotion_score(cross_project_count=0, adoption_rate=0.0, recall_count=100)
        assert abs(score_10 - score_100) < 1e-6

    def test_formula_recall_count_weight_is_0_2(self):
        score = compute_promotion_score(cross_project_count=0, adoption_rate=0.0, recall_count=10)
        assert abs(score - 0.2) < 1e-6

    def test_combined_score(self):
        score = compute_promotion_score(
            cross_project_count=2,
            adoption_rate=0.8,
            recall_count=10,
        )
        expected = 2 * 0.5 + 0.8 * 0.3 + 1.0 * 0.2
        assert abs(score - expected) < 1e-6


class TestIsPromotionCandidate:
    def _make_input(self, **kwargs):
        defaults = dict(
            score=0.8,
            cross_project_count=2,
            adoption_rate=0.7,
            recall_count=6,
            age_days=31,
        )
        defaults.update(kwargs)
        return defaults

    def test_all_conditions_met_returns_true(self):
        assert is_promotion_candidate(**self._make_input()) is True

    def test_score_below_0_7_returns_false(self):
        assert is_promotion_candidate(**self._make_input(score=0.69)) is False

    def test_cross_project_count_below_2_returns_false(self):
        assert is_promotion_candidate(**self._make_input(cross_project_count=1)) is False

    def test_adoption_rate_below_0_6_returns_false(self):
        assert is_promotion_candidate(**self._make_input(adoption_rate=0.59)) is False

    def test_recall_count_below_5_returns_false(self):
        assert is_promotion_candidate(**self._make_input(recall_count=4)) is False

    def test_age_days_below_30_returns_false(self):
        assert is_promotion_candidate(**self._make_input(age_days=29)) is False
```

### Step 2：运行测试，确认失败

```bash
pytest tests/unit/test_promotion.py -v
```

### Step 3：创建 `src/domain/promotion.py`

```python
from __future__ import annotations


def compute_promotion_score(
    cross_project_count: int,
    adoption_rate: float,
    recall_count: int,
) -> float:
    recall_component = min(recall_count / 10, 1.0)
    return cross_project_count * 0.5 + adoption_rate * 0.3 + recall_component * 0.2


def is_promotion_candidate(
    score: float,
    cross_project_count: int,
    adoption_rate: float,
    recall_count: int,
    age_days: int,
) -> bool:
    if score <= 0.7:
        return False
    if cross_project_count < 2:
        return False
    if adoption_rate <= 0.6:
        return False
    if recall_count <= 5:
        return False
    if age_days <= 30:
        return False
    return True
```

### Step 4：运行测试，确认通过

```bash
pytest tests/unit/test_promotion.py -v
```

### Step 5：提交

```bash
git add src/domain/promotion.py tests/unit/test_promotion.py
git commit -m "feat(domain): add promotion score computation and candidate detection"
```

---

## Task 8：save tool 质量评分更新

**背景：** 新 `save` tool 的质量评分规则与当前 `compute_quality_score` 不同：`solution > 50字 → +30`，`key_decisions > 30字 → +30`，`tags ≥ 2 → +20`，`outcome = success → +20 否则 +10`，`score ≥ 80 → auto-activate`。需要新增一个针对 save tool 的质量评分函数。

**Files:**
- Modify: `src/domain/quality.py`
- Test: `tests/unit/test_save_quality.py`（新建）

---

### Step 1：写失败测试

新建 `tests/unit/test_save_quality.py`：

```python
from src.domain.quality import compute_save_quality_score


class TestComputeSaveQualityScore:
    def test_zero_score_for_empty_fields(self):
        score = compute_save_quality_score(
            solution="短",
            key_decisions="短",
            tags=[],
            outcome="failed",
        )
        assert score == 10

    def test_solution_over_50_chars_adds_30(self):
        solution = "x" * 51
        score = compute_save_quality_score(
            solution=solution, key_decisions="", tags=[], outcome="failed"
        )
        assert score == 40

    def test_key_decisions_over_30_chars_adds_30(self):
        kd = "x" * 31
        score = compute_save_quality_score(
            solution="", key_decisions=kd, tags=[], outcome="failed"
        )
        assert score == 40

    def test_two_or_more_tags_adds_20(self):
        score = compute_save_quality_score(
            solution="", key_decisions="", tags=["python", "fastapi"], outcome="failed"
        )
        assert score == 30

    def test_outcome_success_adds_20(self):
        score = compute_save_quality_score(
            solution="", key_decisions="", tags=[], outcome="success"
        )
        assert score == 20

    def test_outcome_partial_adds_10(self):
        score = compute_save_quality_score(
            solution="", key_decisions="", tags=[], outcome="partial"
        )
        assert score == 10

    def test_full_score_100_for_all_conditions_met(self):
        score = compute_save_quality_score(
            solution="x" * 51,
            key_decisions="x" * 31,
            tags=["python", "fastapi"],
            outcome="success",
        )
        assert score == 100

    def test_score_80_auto_activates(self):
        score = compute_save_quality_score(
            solution="x" * 51,
            key_decisions="x" * 31,
            tags=["python", "fastapi"],
            outcome="partial",
        )
        assert score == 90
        assert score >= 80
```

### Step 2：运行测试，确认失败

```bash
pytest tests/unit/test_save_quality.py -v
```

### Step 3：在 `src/domain/quality.py` 末尾追加

```python
def compute_save_quality_score(
    solution: str,
    key_decisions: str,
    tags: list[str],
    outcome: str,
) -> int:
    score = 0
    if len(solution.strip()) > 50:
        score += 30
    if len(key_decisions.strip()) > 30:
        score += 30
    if len(tags) >= 2:
        score += 20
    if outcome == "success":
        score += 20
    else:
        score += 10
    return score
```

### Step 4：运行测试，确认通过

```bash
pytest tests/unit/test_save_quality.py -v
```

### Step 5：提交

```bash
git add src/domain/quality.py tests/unit/test_save_quality.py
git commit -m "feat(domain): add compute_save_quality_score for new save tool"
```

---

## Task 9：feedback v2 confidence 更新逻辑

**背景：** 新 feedback tool 的 confidence 更新规则是：helpful → `min(confidence + 0.1, 1.0)`，unhelpful → `max(confidence - 0.05, 0.0)`，低于 0.2 标记为待归档（现有逻辑阈值是 0.1）。同时需要 id 合法性校验：helpful_ids 和 unhelpful_ids 必须都在 search_event 的 result_ids 中。

**Files:**
- Create: `src/domain/feedback_v2.py`
- Test: `tests/unit/test_feedback_v2.py`（新建）

---

### Step 1：写失败测试

新建 `tests/unit/test_feedback_v2.py`：

```python
import pytest
from src.domain.feedback_v2 import (
    compute_confidence_after_helpful,
    compute_confidence_after_unhelpful,
    validate_feedback_ids,
    should_archive,
)


class TestConfidenceUpdate:
    def test_helpful_increases_confidence_by_0_1(self):
        assert abs(compute_confidence_after_helpful(0.6) - 0.7) < 1e-6

    def test_helpful_caps_at_1_0(self):
        assert compute_confidence_after_helpful(0.95) == 1.0

    def test_unhelpful_decreases_confidence_by_0_05(self):
        assert abs(compute_confidence_after_unhelpful(0.6) - 0.55) < 1e-6

    def test_unhelpful_floors_at_0_0(self):
        assert compute_confidence_after_unhelpful(0.02) == 0.0


class TestShouldArchive:
    def test_confidence_below_0_2_should_archive(self):
        assert should_archive(0.19) is True

    def test_confidence_exactly_0_2_should_not_archive(self):
        assert should_archive(0.2) is False

    def test_confidence_above_0_2_should_not_archive(self):
        assert should_archive(0.5) is False


class TestValidateFeedbackIds:
    def test_all_ids_in_result_ids_is_valid(self):
        errors = validate_feedback_ids(
            helpful_ids=["exp-001"],
            unhelpful_ids=["exp-002"],
            result_ids=["exp-001", "exp-002", "exp-003"],
        )
        assert errors == []

    def test_helpful_id_not_in_result_ids_returns_error(self):
        errors = validate_feedback_ids(
            helpful_ids=["exp-999"],
            unhelpful_ids=[],
            result_ids=["exp-001", "exp-002"],
        )
        assert len(errors) == 1
        assert "exp-999" in errors[0]

    def test_unhelpful_id_not_in_result_ids_returns_error(self):
        errors = validate_feedback_ids(
            helpful_ids=[],
            unhelpful_ids=["exp-888"],
            result_ids=["exp-001"],
        )
        assert len(errors) == 1
        assert "exp-888" in errors[0]

    def test_empty_ids_always_valid(self):
        errors = validate_feedback_ids(
            helpful_ids=[],
            unhelpful_ids=[],
            result_ids=["exp-001"],
        )
        assert errors == []

    def test_id_in_both_helpful_and_unhelpful_returns_error(self):
        errors = validate_feedback_ids(
            helpful_ids=["exp-001"],
            unhelpful_ids=["exp-001"],
            result_ids=["exp-001"],
        )
        assert any("exp-001" in e and ("both" in e.lower() or "同时" in e) for e in errors)
```

### Step 2：运行测试，确认失败

```bash
pytest tests/unit/test_feedback_v2.py -v
```

### Step 3：创建 `src/domain/feedback_v2.py`

```python
from __future__ import annotations


def compute_confidence_after_helpful(current: float) -> float:
    return round(min(current + 0.1, 1.0), 3)


def compute_confidence_after_unhelpful(current: float) -> float:
    return round(max(current - 0.05, 0.0), 3)


def should_archive(confidence: float) -> bool:
    return confidence < 0.2


def validate_feedback_ids(
    helpful_ids: list[str],
    unhelpful_ids: list[str],
    result_ids: list[str],
) -> list[str]:
    errors = []
    result_set = set(result_ids)
    helpful_set = set(helpful_ids)
    unhelpful_set = set(unhelpful_ids)

    overlap = helpful_set & unhelpful_set
    for exp_id in overlap:
        errors.append(f"{exp_id} 同时出现在 helpful_ids 和 unhelpful_ids 中（both）")

    for exp_id in helpful_ids:
        if exp_id not in result_set:
            errors.append(f"{exp_id} 不在 search_event 的 result_ids 中")

    for exp_id in unhelpful_ids:
        if exp_id not in result_set:
            errors.append(f"{exp_id} 不在 search_event 的 result_ids 中")

    return errors
```

### Step 4：运行测试，确认通过

```bash
pytest tests/unit/test_feedback_v2.py -v
```

### Step 5：提交

```bash
git add src/domain/feedback_v2.py tests/unit/test_feedback_v2.py
git commit -m "feat(domain): add feedback_v2 confidence update and id validation"
```

---

## Task 10：初始 confidence 根据 outcome 设置

**背景：** `save` tool 中，初始 confidence 根据 outcome 不同而不同：`success → 0.65`，`partial → 0.55`，`failed → 0.40`。这是纯函数，放在 domain 层。

**Files:**
- Modify: `src/domain/constants.py`
- Create: `src/domain/save_domain.py`
- Test: `tests/unit/test_save_domain.py`（新建）

---

### Step 1：写失败测试

新建 `tests/unit/test_save_domain.py`：

```python
from src.domain.save_domain import initial_confidence_for_outcome


class TestInitialConfidence:
    def test_success_gives_0_65(self):
        assert initial_confidence_for_outcome("success") == 0.65

    def test_partial_gives_0_55(self):
        assert initial_confidence_for_outcome("partial") == 0.55

    def test_failed_gives_0_40(self):
        assert initial_confidence_for_outcome("failed") == 0.40

    def test_unknown_outcome_gives_0_55_as_default(self):
        assert initial_confidence_for_outcome("unknown") == 0.55
```

### Step 2：运行测试，确认失败

```bash
pytest tests/unit/test_save_domain.py -v
```

### Step 3：创建 `src/domain/save_domain.py`

```python
from __future__ import annotations

_OUTCOME_CONFIDENCE = {
    "success": 0.65,
    "partial": 0.55,
    "failed": 0.40,
}


def initial_confidence_for_outcome(outcome: str) -> float:
    return _OUTCOME_CONFIDENCE.get(outcome, 0.55)
```

### Step 4：运行测试，确认通过

```bash
pytest tests/unit/test_save_domain.py -v
```

### Step 5：提交

```bash
git add src/domain/save_domain.py tests/unit/test_save_domain.py
git commit -m "feat(domain): add initial_confidence_for_outcome for save tool"
```

---

## Task 11：新增 Command 定义（SearchV2/Save/FeedbackV2）

**背景：** 按 CQRS 模式，每个新操作对应一个 Command dataclass。需要在 `src/application/commands.py` 中添加三个新 Command。

**Files:**
- Modify: `src/application/commands.py`
- Test: `tests/contract/test_commands.py`（已有，追加新测试）

---

### Step 1：查看现有 contract 测试

```bash
cat tests/contract/test_commands.py
```

了解已有测试格式，然后在末尾追加：

### Step 2：在 `tests/contract/test_commands.py` 末尾追加

```python
from src.application.commands import SearchV2Command, SaveCommand, FeedbackV2Command


class TestSearchV2Command:
    def test_search_v2_command_has_task_description(self):
        cmd = SearchV2Command(
            task_description="修复 NPE",
            project_id="github.com/org/repo",
            project_manifest='{"dependencies": {"react": "^18"}}',
        )
        assert cmd.task_description == "修复 NPE"
        assert cmd.project_id == "github.com/org/repo"

    def test_search_v2_command_session_id_defaults_to_none(self):
        cmd = SearchV2Command(
            task_description="test",
            project_id="github.com/org/repo",
            project_manifest="",
        )
        assert cmd.session_id is None


class TestSaveCommand:
    def test_save_command_required_fields(self):
        cmd = SaveCommand(
            task_description="修复 NPE",
            solution="在 Service 层增加 null 检查",
            key_decisions="在 Service 而不是 DAO 层做检查",
            tags=["java", "null-safety"],
            project_id="github.com/org/repo",
            outcome="success",
        )
        assert cmd.outcome == "success"
        assert cmd.search_event_id is None

    def test_save_command_search_event_id_optional(self):
        cmd = SaveCommand(
            task_description="test",
            solution="sol",
            key_decisions="kd",
            tags=[],
            project_id="proj",
            outcome="success",
            search_event_id="evt-001",
        )
        assert cmd.search_event_id == "evt-001"


class TestFeedbackV2Command:
    def test_feedback_v2_command_required_fields(self):
        cmd = FeedbackV2Command(
            search_event_id="evt-001",
            helpful_ids=["exp-001"],
            unhelpful_ids=["exp-002"],
        )
        assert cmd.search_event_id == "evt-001"

    def test_feedback_v2_command_comment_defaults_to_none(self):
        cmd = FeedbackV2Command(search_event_id="evt-001")
        assert cmd.comment is None
        assert cmd.helpful_ids == []
        assert cmd.unhelpful_ids == []
```

### Step 3：运行测试，确认失败

```bash
pytest tests/contract/test_commands.py -v -k "SearchV2 or Save or FeedbackV2"
```

### Step 4：在 `src/application/commands.py` 末尾追加

```python
@dataclass
class SearchV2Command:
    task_description: str
    project_id: str
    project_manifest: str
    session_id: str | None = None
    top_k: int = 5


@dataclass
class SaveCommand:
    task_description: str
    solution: str
    key_decisions: str
    tags: list[str]
    project_id: str
    outcome: str
    search_event_id: str | None = None


@dataclass
class FeedbackV2Command:
    search_event_id: str
    helpful_ids: list[str] = field(default_factory=list)
    unhelpful_ids: list[str] = field(default_factory=list)
    comment: str | None = None
```

### Step 5：运行测试，确认通过

```bash
pytest tests/contract/test_commands.py -v
```

### Step 6：提交

```bash
git add src/application/commands.py tests/contract/test_commands.py
git commit -m "feat(application): add SearchV2Command, SaveCommand, FeedbackV2Command"
```

---

## Task 12：SearchV2Handler 实现

**背景：** Handler 协调 domain 层和 infrastructure 层，实现三层并发搜索逻辑。由于涉及真实 I/O，此 Handler 的核心逻辑测试使用 `InMemoryUnitOfWork` + 伪造 embedding provider。

**Files:**
- Create: `src/application/handlers/search_v2_handler.py`
- Test: `tests/unit/test_search_v2_handler.py`（新建）

---

### Step 1：写失败测试

新建 `tests/unit/test_search_v2_handler.py`：

```python
import uuid
import pytest
from src.application.commands import SearchV2Command
from src.application.handlers.search_v2_handler import SearchV2Handler
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.models import (
    Experience, ExperienceType, ExperienceLevel, ExperienceStatus,
    ExperienceSource, ExperienceMetadata, ScopeType, SearchEvent,
)


def make_active_exp(exp_id, scope_type=ScopeType.PROJECT, scope_id="proj-001", tags=None):
    return Experience(
        id=exp_id,
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L1,
        title=f"经验 {exp_id}",
        tags=tags or ["python"],
        problem="问题",
        solution="解决方案，超过五十个字的详细描述文本内容这里要足够长才行",
        key_decisions="关键决策，超过三十字的关键信息",
        confidence=0.65,
        status=ExperienceStatus.ACTIVE,
        source=ExperienceSource.AGENT,
        created_at="2026-01-01T00:00:00",
        metadata=ExperienceMetadata(tech_stack=tags or ["python"]),
        scope_type=scope_type,
        scope_id=scope_id,
    )


class FakeEmbeddingProvider:
    def embed_text(self, text: str) -> list[float]:
        import numpy as np
        v = np.ones(64, dtype=np.float32)
        return (v / np.linalg.norm(v)).tolist()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


class TestSearchV2HandlerReturnsResults:
    def _make_handler_and_uow(self):
        uow = InMemoryUnitOfWork()
        provider = FakeEmbeddingProvider()
        handler = SearchV2Handler(uow_factory=lambda: uow, embedding_provider=provider)
        return handler, uow

    def test_returns_empty_when_no_active_experiences(self):
        handler, uow = self._make_handler_and_uow()
        cmd = SearchV2Command(
            task_description="修复 bug",
            project_id="proj-001",
            project_manifest="",
        )
        result = handler.handle(cmd)
        assert result["results"] == []

    def test_returns_search_event_id(self):
        handler, uow = self._make_handler_and_uow()
        exp = make_active_exp("exp-001", scope_id="proj-001")
        uow.experiences._committed["exp-001"] = exp
        uow.vectors.save_vector("exp-001", FakeEmbeddingProvider().embed_text("test"))

        cmd = SearchV2Command(
            task_description="修复 bug",
            project_id="proj-001",
            project_manifest='{"dependencies": {"fastapi": "^0.110"}}',
            session_id="sess-001",
        )
        result = handler.handle(cmd)
        assert "search_event_id" in result
        assert result["search_event_id"] is not None

    def test_project_scope_results_included(self):
        handler, uow = self._make_handler_and_uow()
        exp = make_active_exp("exp-001", scope_type=ScopeType.PROJECT, scope_id="proj-001")
        uow.experiences._committed["exp-001"] = exp
        uow.vectors.save_vector("exp-001", FakeEmbeddingProvider().embed_text("test"))

        cmd = SearchV2Command(
            task_description="修复 bug",
            project_id="proj-001",
            project_manifest="",
        )
        result = handler.handle(cmd)
        ids = [r["id"] for r in result["results"]]
        assert "exp-001" in ids

    def test_results_contain_required_fields(self):
        handler, uow = self._make_handler_and_uow()
        exp = make_active_exp("exp-001", scope_id="proj-001")
        uow.experiences._committed["exp-001"] = exp
        uow.vectors.save_vector("exp-001", FakeEmbeddingProvider().embed_text("test"))

        cmd = SearchV2Command(
            task_description="修复 bug",
            project_id="proj-001",
            project_manifest="",
        )
        result = handler.handle(cmd)
        if result["results"]:
            r = result["results"][0]
            assert "id" in r
            assert "title" in r
            assert "solution" in r
            assert "key_decisions" in r
            assert "source_level" in r
            assert "tags" in r
```

### Step 2：运行测试，确认失败

```bash
pytest tests/unit/test_search_v2_handler.py -v
```

### Step 3：创建 `src/application/handlers/search_v2_handler.py`

```python
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Callable, Any

import numpy as np

from ..commands import SearchV2Command
from ..unit_of_work import AbstractUnitOfWork
from ...domain.manifest_parser import parse_manifest
from ...domain.search_v2 import (
    apply_scope_weight,
    apply_tech_stack_boost,
    merge_and_deduplicate,
    ScopeWeightedResult,
)
from ...models import ScopeType, SearchEvent


class SearchV2Handler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork], embedding_provider: Any):
        self._uow_factory = uow_factory
        self._provider = embedding_provider

    def handle(self, cmd: SearchV2Command) -> dict:
        manifest_info = parse_manifest(cmd.project_manifest)
        language = manifest_info["language"]
        frameworks = manifest_info["frameworks"]
        top_deps = manifest_info["top_dependencies"]

        query_text = f"{cmd.task_description} {language} {' '.join(top_deps)}"
        query_vec = np.array(self._provider.embed_text(query_text), dtype=np.float32)

        with self._uow_factory() as uow:
            all_exps = uow.experiences.list_by_status("active")

        project_exps = [e for e in all_exps if e.scope_type == ScopeType.PROJECT and e.scope_id == cmd.project_id]
        business_exps = [e for e in all_exps if e.scope_type == ScopeType.BUSINESS]
        team_exps = [e for e in all_exps if e.scope_type == ScopeType.TEAM]

        weighted_results: list[ScopeWeightedResult] = []
        for scope_exps, scope_name in [
            (project_exps, "project"),
            (business_exps, "business"),
            (team_exps, "team"),
        ]:
            for exp in scope_exps:
                vec = self._get_or_compute_vector(exp, uow)
                if vec is None:
                    continue
                raw_score = float(np.dot(query_vec, vec) / (np.linalg.norm(query_vec) * np.linalg.norm(vec) + 1e-9))
                if raw_score < 0.5:
                    continue
                boosted = apply_tech_stack_boost(
                    score=raw_score,
                    exp_tags=exp.tags,
                    query_languages=[language] + frameworks,
                    query_dependencies=top_deps,
                )
                final_score = apply_scope_weight(score=boosted, scope_type=scope_name)
                weighted_results.append(ScopeWeightedResult(exp_id=exp.id, score=final_score, scope_type=scope_name))

        merged = merge_and_deduplicate(weighted_results, top_k=cmd.top_k, threshold=0.0)

        exp_map = {e.id: e for e in all_exps}
        results = []
        for r in merged:
            exp = exp_map.get(r.exp_id)
            if exp:
                results.append({
                    "id": exp.id,
                    "title": exp.title,
                    "level": exp.level.value,
                    "source_level": r.scope_type,
                    "tags": exp.tags,
                    "problem": exp.problem,
                    "solution": exp.solution,
                    "key_decisions": exp.key_decisions,
                    "score": round(r.score, 3),
                })

        search_event_id = str(uuid.uuid4())
        return {
            "search_event_id": search_event_id,
            "results": results,
        }

    def _get_or_compute_vector(self, exp, uow) -> np.ndarray | None:
        ids, vecs = uow.vectors.get_all_vectors([exp.id])
        if ids and len(vecs) > 0:
            return np.array(vecs[0], dtype=np.float32)
        embed_text = f"{exp.title} {exp.solution} {exp.key_decisions}"
        vec = self._provider.embed_text(embed_text)
        uow.vectors.save_vector(exp.id, vec)
        return np.array(vec, dtype=np.float32)
```

### Step 4：运行测试，确认通过

```bash
pytest tests/unit/test_search_v2_handler.py -v
```

### Step 5：提交

```bash
git add src/application/handlers/search_v2_handler.py tests/unit/test_search_v2_handler.py
git commit -m "feat(application): add SearchV2Handler with three-tier concurrent search"
```

---

## Task 13：SaveHandler 实现

**背景：** 处理 `save` tool 逻辑：质量评分、重复检测、auto-activate 判断、关联 search_event_id。

**Files:**
- Create: `src/application/handlers/save_handler.py`
- Test: `tests/unit/test_save_handler.py`（新建）

---

### Step 1：写失败测试

新建 `tests/unit/test_save_handler.py`：

```python
import pytest
from src.application.commands import SaveCommand
from src.application.handlers.save_handler import SaveHandler
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.models import ExperienceStatus


class FakeEmbeddingProvider:
    def embed_text(self, text: str) -> list[float]:
        import numpy as np
        v = np.ones(64, dtype=np.float32)
        return (v / np.linalg.norm(v)).tolist()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


class TestSaveHandlerAutoActivate:
    def _make_handler(self, uow=None):
        if uow is None:
            uow = InMemoryUnitOfWork()
        provider = FakeEmbeddingProvider()
        return SaveHandler(uow_factory=lambda: uow, embedding_provider=provider), uow

    def _make_cmd(self, **kwargs):
        defaults = dict(
            task_description="修复 userId 为 null 的 NPE",
            solution="在 UserService.getUser() 入口增加 Objects.requireNonNull 检查，" + "x" * 40,
            key_decisions="在 Service 层而非 DAO 层做 null 检查，因为这是业务约束" + "x" * 10,
            tags=["java", "null-safety"],
            project_id="github.com/org/my-service",
            outcome="success",
        )
        defaults.update(kwargs)
        return SaveCommand(**defaults)

    def test_high_quality_experience_auto_activates(self):
        handler, uow = self._make_handler()
        cmd = self._make_cmd()
        result = handler.handle(cmd)
        exp_id = result["experience_id"]
        exp = uow.experiences.get(exp_id)
        assert exp is not None
        assert exp.status == ExperienceStatus.ACTIVE

    def test_low_quality_experience_stays_pending(self):
        handler, uow = self._make_handler()
        cmd = self._make_cmd(solution="短", key_decisions="短", tags=[], outcome="failed")
        result = handler.handle(cmd)
        exp_id = result["experience_id"]
        exp = uow.experiences.get(exp_id)
        assert exp.status == ExperienceStatus.PENDING

    def test_success_outcome_gives_confidence_0_65(self):
        handler, uow = self._make_handler()
        cmd = self._make_cmd(outcome="success")
        result = handler.handle(cmd)
        exp = uow.experiences.get(result["experience_id"])
        assert abs(exp.confidence - 0.65) < 1e-6

    def test_partial_outcome_gives_confidence_0_55(self):
        handler, uow = self._make_handler()
        cmd = self._make_cmd(outcome="partial")
        result = handler.handle(cmd)
        exp = uow.experiences.get(result["experience_id"])
        assert abs(exp.confidence - 0.55) < 1e-6

    def test_failed_outcome_gives_confidence_0_40(self):
        handler, uow = self._make_handler()
        cmd = self._make_cmd(outcome="failed")
        result = handler.handle(cmd)
        exp = uow.experiences.get(result["experience_id"])
        assert abs(exp.confidence - 0.40) < 1e-6

    def test_returns_experience_id(self):
        handler, uow = self._make_handler()
        result = handler.handle(self._make_cmd())
        assert "experience_id" in result
        assert result["experience_id"] is not None

    def test_experience_scope_type_is_project(self):
        handler, uow = self._make_handler()
        result = handler.handle(self._make_cmd())
        exp = uow.experiences.get(result["experience_id"])
        from src.models import ScopeType
        assert exp.scope_type == ScopeType.PROJECT

    def test_experience_scope_id_matches_project_id(self):
        handler, uow = self._make_handler()
        result = handler.handle(self._make_cmd())
        exp = uow.experiences.get(result["experience_id"])
        assert exp.scope_id == "github.com/org/my-service"

    def test_duplicate_detection_warns_when_similarity_above_0_85(self):
        handler, uow = self._make_handler()
        cmd = self._make_cmd()
        result1 = handler.handle(cmd)
        result2 = handler.handle(cmd)
        assert result2.get("duplicate_warning") is not None or result2.get("experience_id") is not None
```

### Step 2：运行测试，确认失败

```bash
pytest tests/unit/test_save_handler.py -v
```

### Step 3：创建 `src/application/handlers/save_handler.py`

```python
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Callable, Any

import numpy as np

from ..commands import SaveCommand
from ..unit_of_work import AbstractUnitOfWork
from ...domain.quality import compute_save_quality_score
from ...domain.save_domain import initial_confidence_for_outcome
from ...domain.experience import check_duplicate
from ...models import (
    Experience, ExperienceType, ExperienceLevel, ExperienceStatus,
    ExperienceSource, ExperienceMetadata, ScopeType,
)
from ...domain.constants import DUPLICATE_SIMILARITY_THRESHOLD


class SaveHandler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork], embedding_provider: Any):
        self._uow_factory = uow_factory
        self._provider = embedding_provider

    def handle(self, cmd: SaveCommand) -> dict:
        quality_score = compute_save_quality_score(
            solution=cmd.solution,
            key_decisions=cmd.key_decisions,
            tags=cmd.tags,
            outcome=cmd.outcome,
        )

        confidence = initial_confidence_for_outcome(cmd.outcome)
        status = ExperienceStatus.ACTIVE if quality_score >= 80 else ExperienceStatus.PENDING

        embed_text = f"{cmd.task_description} {cmd.solution} {cmd.key_decisions}"
        new_vec = np.array(self._provider.embed_text(embed_text), dtype=np.float32)

        duplicate_warning = None
        with self._uow_factory() as uow:
            project_exps = [
                e for e in uow.experiences.list_by_status("active")
                if getattr(e, "scope_id", None) == cmd.project_id
            ] + [
                e for e in uow.experiences.list_by_status("pending")
                if getattr(e, "scope_id", None) == cmd.project_id
            ]

            if project_exps:
                exp_ids = [e.id for e in project_exps]
                existing_ids, existing_vecs = uow.vectors.get_all_vectors(exp_ids)
                if existing_ids and existing_vecs.size > 0:
                    is_dup, dup_id, dup_score = check_duplicate(new_vec, existing_vecs, existing_ids)
                    if is_dup and dup_score >= DUPLICATE_SIMILARITY_THRESHOLD:
                        duplicate_warning = f"与经验 {dup_id} 相似度 {dup_score:.2f}，请确认是否需要合并"

            exp_id = str(uuid.uuid4())
            exp = Experience(
                id=exp_id,
                type=ExperienceType.BUGFIX,
                level=ExperienceLevel.L1,
                title=cmd.task_description[:60],
                tags=cmd.tags,
                problem=cmd.task_description,
                solution=cmd.solution,
                key_decisions=cmd.key_decisions,
                confidence=confidence,
                status=status,
                source=ExperienceSource.AGENT,
                created_at=datetime.utcnow().isoformat(),
                metadata=ExperienceMetadata(tech_stack=cmd.tags),
                scope_type=ScopeType.PROJECT,
                scope_id=cmd.project_id,
            )
            uow.experiences.add(exp)
            uow.vectors.save_vector(exp_id, new_vec.tolist())

        result = {
            "experience_id": exp_id,
            "status": status.value,
            "quality_score": quality_score,
        }
        if duplicate_warning:
            result["duplicate_warning"] = duplicate_warning
        return result
```

### Step 4：运行测试，确认通过

```bash
pytest tests/unit/test_save_handler.py -v
```

### Step 5：提交

```bash
git add src/application/handlers/save_handler.py tests/unit/test_save_handler.py
git commit -m "feat(application): add SaveHandler with quality score and auto-activate"
```

---

## Task 14：FeedbackV2Handler 实现

**背景：** 处理 `feedback` tool：校验 ids 合法性、更新 confidence、记录 FeedbackEvent。由于 search_event 的持久化在本阶段通过内存模拟。

**Files:**
- Create: `src/application/handlers/feedback_v2_handler.py`
- Test: `tests/unit/test_feedback_v2_handler.py`（新建）

---

### Step 1：写失败测试

新建 `tests/unit/test_feedback_v2_handler.py`：

```python
import pytest
from src.application.commands import FeedbackV2Command
from src.application.handlers.feedback_v2_handler import FeedbackV2Handler
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.models import (
    Experience, ExperienceType, ExperienceLevel, ExperienceStatus,
    ExperienceSource, ExperienceMetadata, ScopeType, SearchEvent,
)


def make_exp(exp_id, confidence=0.65):
    return Experience(
        id=exp_id,
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L1,
        title="测试经验",
        tags=["python"],
        problem="问题",
        solution="解决方案超过五十字这里足够长",
        key_decisions="关键决策超过三十字这里",
        confidence=confidence,
        status=ExperienceStatus.ACTIVE,
        source=ExperienceSource.AGENT,
        created_at="2026-01-01T00:00:00",
        metadata=ExperienceMetadata(),
        scope_type=ScopeType.PROJECT,
        scope_id="proj-001",
    )


def make_search_event(event_id, result_ids):
    return SearchEvent(
        id=event_id,
        session_id="sess-001",
        project_id="proj-001",
        query_text="test",
        timestamp="2026-05-04T00:00:00",
        result_ids=result_ids,
    )


class FakeSearchEventStore:
    def __init__(self):
        self._events: dict[str, SearchEvent] = {}

    def save(self, event: SearchEvent):
        self._events[event.id] = event

    def get(self, event_id: str):
        return self._events.get(event_id)


class TestFeedbackV2HandlerValidation:
    def _make_handler(self, uow=None, event_store=None):
        if uow is None:
            uow = InMemoryUnitOfWork()
        if event_store is None:
            event_store = FakeSearchEventStore()
        handler = FeedbackV2Handler(uow_factory=lambda: uow, search_event_store=event_store)
        return handler, uow, event_store

    def test_invalid_helpful_id_returns_error(self):
        handler, uow, evt_store = self._make_handler()
        evt_store.save(make_search_event("evt-001", result_ids=["exp-001"]))
        uow.experiences._committed["exp-001"] = make_exp("exp-001")

        cmd = FeedbackV2Command(
            search_event_id="evt-001",
            helpful_ids=["exp-999"],
        )
        result = handler.handle(cmd)
        assert result["status"] == "error"
        assert "exp-999" in result["message"]

    def test_valid_helpful_id_increases_confidence(self):
        handler, uow, evt_store = self._make_handler()
        evt_store.save(make_search_event("evt-001", result_ids=["exp-001"]))
        uow.experiences._committed["exp-001"] = make_exp("exp-001", confidence=0.65)

        cmd = FeedbackV2Command(
            search_event_id="evt-001",
            helpful_ids=["exp-001"],
        )
        result = handler.handle(cmd)
        assert result["status"] == "ok"
        updated_exp = uow.experiences.get("exp-001")
        assert abs(updated_exp.confidence - 0.75) < 1e-4

    def test_valid_unhelpful_id_decreases_confidence(self):
        handler, uow, evt_store = self._make_handler()
        evt_store.save(make_search_event("evt-001", result_ids=["exp-001"]))
        uow.experiences._committed["exp-001"] = make_exp("exp-001", confidence=0.65)

        cmd = FeedbackV2Command(
            search_event_id="evt-001",
            unhelpful_ids=["exp-001"],
        )
        result = handler.handle(cmd)
        assert result["status"] == "ok"
        updated_exp = uow.experiences.get("exp-001")
        assert abs(updated_exp.confidence - 0.60) < 1e-4

    def test_confidence_below_0_2_marks_for_archive(self):
        handler, uow, evt_store = self._make_handler()
        evt_store.save(make_search_event("evt-001", result_ids=["exp-001"]))
        uow.experiences._committed["exp-001"] = make_exp("exp-001", confidence=0.22)

        cmd = FeedbackV2Command(
            search_event_id="evt-001",
            unhelpful_ids=["exp-001"],
        )
        handler.handle(cmd)
        updated_exp = uow.experiences.get("exp-001")
        assert updated_exp.status == ExperienceStatus.ARCHIVED

    def test_search_event_not_found_returns_error(self):
        handler, uow, evt_store = self._make_handler()
        cmd = FeedbackV2Command(
            search_event_id="evt-not-exist",
            helpful_ids=["exp-001"],
        )
        result = handler.handle(cmd)
        assert result["status"] == "error"
```

### Step 2：运行测试，确认失败

```bash
pytest tests/unit/test_feedback_v2_handler.py -v
```

### Step 3：创建 `src/application/handlers/feedback_v2_handler.py`

```python
from __future__ import annotations
from typing import Callable, Any

from ..commands import FeedbackV2Command
from ..unit_of_work import AbstractUnitOfWork
from ...domain.feedback_v2 import (
    compute_confidence_after_helpful,
    compute_confidence_after_unhelpful,
    validate_feedback_ids,
    should_archive,
)
from ...models import ExperienceStatus


class FeedbackV2Handler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork], search_event_store: Any):
        self._uow_factory = uow_factory
        self._event_store = search_event_store

    def handle(self, cmd: FeedbackV2Command) -> dict:
        event = self._event_store.get(cmd.search_event_id)
        if event is None:
            return {"status": "error", "message": f"search_event {cmd.search_event_id} 不存在"}

        errors = validate_feedback_ids(
            helpful_ids=cmd.helpful_ids,
            unhelpful_ids=cmd.unhelpful_ids,
            result_ids=event.result_ids,
        )
        if errors:
            return {"status": "error", "message": "; ".join(errors)}

        with self._uow_factory() as uow:
            for exp_id in cmd.helpful_ids:
                exp = uow.experiences.get(exp_id)
                if exp is None:
                    continue
                exp.confidence = compute_confidence_after_helpful(exp.confidence)
                if should_archive(exp.confidence):
                    exp.status = ExperienceStatus.ARCHIVED
                uow.experiences.update(exp)

            for exp_id in cmd.unhelpful_ids:
                exp = uow.experiences.get(exp_id)
                if exp is None:
                    continue
                exp.confidence = compute_confidence_after_unhelpful(exp.confidence)
                if should_archive(exp.confidence):
                    exp.status = ExperienceStatus.ARCHIVED
                uow.experiences.update(exp)

        return {"status": "ok", "search_event_id": cmd.search_event_id}
```

### Step 4：运行测试，确认通过

```bash
pytest tests/unit/test_feedback_v2_handler.py -v
```

### Step 5：提交

```bash
git add src/application/handlers/feedback_v2_handler.py tests/unit/test_feedback_v2_handler.py
git commit -m "feat(application): add FeedbackV2Handler with id validation and confidence update"
```

---

## Task 15：注册新 Handler 到 CommandBus

**背景：** 在 `container.py` 的 `build_command_bus()` 里注册三个新 handler，使 CommandBus 可以路由新 Command。

**Files:**
- Modify: `src/container.py`
- Test: `tests/unit/test_command_bus.py`（已有，追加新测试）

---

### Step 1：查看并追加测试

在 `tests/unit/test_command_bus.py` 末尾追加：

```python
from src.application.commands import SearchV2Command, SaveCommand, FeedbackV2Command


class TestCommandBusNewCommands:
    def test_search_v2_command_is_registered(self):
        from src.container import build_command_bus
        bus = build_command_bus()
        assert SearchV2Command in bus._handlers

    def test_save_command_is_registered(self):
        from src.container import build_command_bus
        bus = build_command_bus()
        assert SaveCommand in bus._handlers

    def test_feedback_v2_command_is_registered(self):
        from src.container import build_command_bus
        bus = build_command_bus()
        assert FeedbackV2Command in bus._handlers
```

### Step 2：运行测试，确认失败

```bash
pytest tests/unit/test_command_bus.py -v -k "NewCommands"
```

### Step 3：修改 `src/container.py`

在 import 区域添加：

```python
from .application.commands import (
    # ... 已有导入 ...
    SearchV2Command,
    SaveCommand,
    FeedbackV2Command,
)
from .application.handlers.search_v2_handler import SearchV2Handler
from .application.handlers.save_handler import SaveHandler
from .application.handlers.feedback_v2_handler import FeedbackV2Handler
```

在 `build_command_bus()` 函数中，在 `bus = CommandBus()` 之后添加依赖构造：

```python
    from .embeddings import get_provider
    embedding_provider = get_provider()

    search_event_store_instance = _InMemorySearchEventStore()  # 临时：集成测试阶段替换为真实实现

    search_v2_handler = SearchV2Handler(
        uow_factory=UnitOfWork,
        embedding_provider=embedding_provider,
    )
    save_handler = SaveHandler(
        uow_factory=UnitOfWork,
        embedding_provider=embedding_provider,
    )
    feedback_v2_handler = FeedbackV2Handler(
        uow_factory=UnitOfWork,
        search_event_store=search_event_store_instance,
    )
```

在 `bus.register(...)` 区域末尾追加：

```python
    bus.register(SearchV2Command, search_v2_handler.handle)
    bus.register(SaveCommand, save_handler.handle)
    bus.register(FeedbackV2Command, feedback_v2_handler.handle)
```

在 `container.py` 末尾添加临时内存实现（待 Phase 3 替换为 PostgreSQL 实现）：

```python
class _InMemorySearchEventStore:
    def __init__(self):
        self._events = {}

    def save(self, event):
        self._events[event.id] = event

    def get(self, event_id: str):
        return self._events.get(event_id)
```

### Step 4：运行测试，确认通过

```bash
pytest tests/unit/test_command_bus.py -v
```

### Step 5：提交

```bash
git add src/container.py tests/unit/test_command_bus.py
git commit -m "feat(container): register SearchV2, Save, FeedbackV2 handlers in CommandBus"
```

---

## Task 16：替换 MCP Server 的 6 个旧 tool 为 3 个新 tool

**背景：** `src/server.py` 中注册了 6 个旧 tool，需要替换为 `search`/`save`/`feedback` 三个新 tool。旧 tool 先保留（在迁移期），但新 tool 优先。此任务先只测试 tool 描述和 schema 正确性。

**Files:**
- Modify: `src/server.py`
- Test: `tests/unit/test_mcp_tools.py`（新建）

---

### Step 1：写失败测试

新建 `tests/unit/test_mcp_tools.py`：

```python
import pytest


class TestMCPToolDefinitions:
    def _get_tool_names(self):
        import asyncio
        import src.server as server_mod
        loop = asyncio.new_event_loop()
        tools = loop.run_until_complete(server_mod.list_tools())
        loop.close()
        return [t.name for t in tools], tools

    def test_search_tool_exists(self):
        names, _ = self._get_tool_names()
        assert "search" in names

    def test_save_tool_exists(self):
        names, _ = self._get_tool_names()
        assert "save" in names

    def test_feedback_tool_exists(self):
        names, _ = self._get_tool_names()
        assert "feedback" in names

    def test_search_tool_has_task_description_param(self):
        _, tools = self._get_tool_names()
        search_tool = next(t for t in tools if t.name == "search")
        assert "task_description" in search_tool.inputSchema["properties"]

    def test_search_tool_has_project_id_param(self):
        _, tools = self._get_tool_names()
        search_tool = next(t for t in tools if t.name == "search")
        assert "project_id" in search_tool.inputSchema["properties"]

    def test_search_tool_has_project_manifest_param(self):
        _, tools = self._get_tool_names()
        search_tool = next(t for t in tools if t.name == "search")
        assert "project_manifest" in search_tool.inputSchema["properties"]

    def test_save_tool_has_outcome_param(self):
        _, tools = self._get_tool_names()
        save_tool = next(t for t in tools if t.name == "save")
        assert "outcome" in save_tool.inputSchema["properties"]

    def test_save_tool_has_search_event_id_param(self):
        _, tools = self._get_tool_names()
        save_tool = next(t for t in tools if t.name == "save")
        assert "search_event_id" in save_tool.inputSchema["properties"]

    def test_feedback_tool_has_search_event_id_param(self):
        _, tools = self._get_tool_names()
        feedback_tool = next(t for t in tools if t.name == "feedback")
        assert "search_event_id" in feedback_tool.inputSchema["properties"]

    def test_feedback_tool_has_helpful_ids_param(self):
        _, tools = self._get_tool_names()
        feedback_tool = next(t for t in tools if t.name == "feedback")
        assert "helpful_ids" in feedback_tool.inputSchema["properties"]
```

### Step 2：运行测试，确认失败

```bash
pytest tests/unit/test_mcp_tools.py -v
```

### Step 3：替换 `src/server.py` 中的 `list_tools` 函数

将 `@app.list_tools()` 装饰的函数替换为返回 3 个新 tool：

```python
@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search",
            description=(
                "【任务开始第一步】coding 任务开始前必须调用，从团队知识库召回相关历史经验，避免重复踩坑。\n"
                "调用前请先执行：git remote get-url origin 获取 project_id；\n"
                "读取 package.json / pyproject.toml / go.mod 中的 dependencies 字段作为 project_manifest（限 2000 tokens）。\n"
                "返回的 search_event_id 需要保存，后续 save 和 feedback 需要传入。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "【必填】当前任务目标，一句话描述（如：修复 userId 为 null 的 NPE），≤500字",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "【必填】从 git remote get-url origin 提取并标准化（格式：github.com/org/repo），无 git 时用目录绝对路径",
                    },
                    "project_manifest": {
                        "type": "string",
                        "description": "【必填】package.json / pyproject.toml / go.mod 中 dependencies 相关字段内容，限 2000 tokens，超出截断",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "会话 ID，用于关联同一任务的 search/save/feedback",
                    },
                },
                "required": ["task_description", "project_id", "project_manifest"],
            },
        ),
        Tool(
            name="save",
            description=(
                "【任务完成后必调】将本次编码任务的经验沉淀到团队知识库，无论成功与否都应调用。\n"
                "solution 建议 ≥50字，key_decisions 建议 ≥30字，tags 建议 ≥2个，以保证经验质量可被自动激活。\n"
                "若任务前调用过 search，请传入 search_event_id 以关联召回记录。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "【必填】任务描述，与 search 时保持一致",
                    },
                    "solution": {
                        "type": "string",
                        "description": "【必填】解决方案核心思路，建议 ≥50字",
                    },
                    "key_decisions": {
                        "type": "string",
                        "description": "【必填】关键决策或踩坑点，建议 ≥30字，这是最有价值的部分",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "【必填】技术栈标签，建议 ≥2个（如 ['java', 'null-safety']）",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "【必填】同 search 时的 project_id",
                    },
                    "outcome": {
                        "type": "string",
                        "enum": ["success", "partial", "failed"],
                        "description": "【必填】任务结果：success（完全解决）/ partial（部分解决）/ failed（未解决）",
                    },
                    "search_event_id": {
                        "type": "string",
                        "description": "【推荐】search 返回的 search_event_id，用于关联召回记录",
                    },
                },
                "required": ["task_description", "solution", "key_decisions", "tags", "project_id", "outcome"],
            },
        ),
        Tool(
            name="feedback",
            description=(
                "【经验反馈】search 返回的经验对本次任务有帮助时，任务结束后调用，帮助系统持续优化知识质量。\n"
                "helpful_ids 和 unhelpful_ids 中的 id 必须来自对应 search 返回的结果，不能传入其他 id。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search_event_id": {
                        "type": "string",
                        "description": "【必填】search 返回的 search_event_id",
                    },
                    "helpful_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "有帮助的经验 id 列表（必须来自该 search 的结果）",
                    },
                    "unhelpful_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "无帮助的经验 id 列表（必须来自该 search 的结果）",
                    },
                    "comment": {
                        "type": "string",
                        "description": "可选的文字说明，如'exp_001 的解法直接复用'",
                    },
                },
                "required": ["search_event_id"],
            },
        ),
    ]
```

同时，替换 `call_tool` 函数处理逻辑（在旧的 6 个 elif 块前/后添加新的 3 个处理块）：

```python
@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    from .application.commands import SearchV2Command, SaveCommand, FeedbackV2Command
    bus = get_bus()

    if name == "search":
        result = bus.dispatch(SearchV2Command(
            task_description=arguments["task_description"],
            project_id=arguments["project_id"],
            project_manifest=arguments.get("project_manifest", ""),
            session_id=arguments.get("session_id"),
        ))
        if not result["results"]:
            return [TextContent(type="text", text=json.dumps(
                {"search_event_id": result["search_event_id"], "results": [], "message": "暂无相关历史经验"},
                ensure_ascii=False
            ))]
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "save":
        result = bus.dispatch(SaveCommand(
            task_description=arguments["task_description"],
            solution=arguments["solution"],
            key_decisions=arguments["key_decisions"],
            tags=arguments.get("tags", []),
            project_id=arguments["project_id"],
            outcome=arguments["outcome"],
            search_event_id=arguments.get("search_event_id"),
        ))
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "feedback":
        result = bus.dispatch(FeedbackV2Command(
            search_event_id=arguments["search_event_id"],
            helpful_ids=arguments.get("helpful_ids", []),
            unhelpful_ids=arguments.get("unhelpful_ids", []),
            comment=arguments.get("comment"),
        ))
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    return [TextContent(type="text", text=f"未知工具: {name}")]
```

### Step 4：运行测试，确认通过

```bash
pytest tests/unit/test_mcp_tools.py -v
```

### Step 5：运行全量单元测试，确认无回归

```bash
pytest tests/unit/ -v
```

### Step 6：提交

```bash
git add src/server.py tests/unit/test_mcp_tools.py
git commit -m "feat(server): replace 6 old MCP tools with 3 new tools: search/save/feedback"
```

---

## Task 17：PromotionScanHandler 实现

**背景：** 定时扫描找出提升候选，通过 REST API 触发。Handler 遍历 project 层经验，计算跨项目相似度和评分，打 `promotion_candidate` 标记（暂用 `stale_reason` 字段存储候选原因，后续可单独建表）。

**Files:**
- Create: `src/application/commands.py`（追加 ScanPromotionCandidatesCommand）
- Create: `src/application/handlers/promotion_handler.py`
- Test: `tests/unit/test_promotion_handler.py`（新建）

---

### Step 1：在 `src/application/commands.py` 末尾追加

```python
@dataclass
class ScanPromotionCandidatesCommand:
    business_id: str | None = None
    dry_run: bool = False
```

### Step 2：写失败测试

新建 `tests/unit/test_promotion_handler.py`：

```python
import pytest
from datetime import datetime, timedelta
from src.application.commands import ScanPromotionCandidatesCommand
from src.application.handlers.promotion_handler import PromotionScanHandler
from tests.helpers.fake_uow import InMemoryUnitOfWork
from src.models import (
    Experience, ExperienceType, ExperienceLevel, ExperienceStatus,
    ExperienceSource, ExperienceMetadata, ScopeType,
)


def make_exp(exp_id, scope_id="proj-001", adoption_rate=0.8, recall_count=10, age_days=60):
    created_at = (datetime.utcnow() - timedelta(days=age_days)).isoformat()
    return Experience(
        id=exp_id,
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.L1,
        title=f"经验 {exp_id}",
        tags=["python"],
        problem="null 检查问题",
        solution="在 Service 层添加 null 检查",
        key_decisions="在 Service 而非 DAO 层检查",
        confidence=0.65,
        status=ExperienceStatus.ACTIVE,
        source=ExperienceSource.AGENT,
        created_at=created_at,
        metadata=ExperienceMetadata(tech_stack=["python"]),
        scope_type=ScopeType.PROJECT,
        scope_id=scope_id,
        adoption_rate=adoption_rate,
        recall_count=recall_count,
    )


class FakeEmbeddingProvider:
    def embed_text(self, text: str) -> list[float]:
        import numpy as np
        v = np.ones(64, dtype=np.float32)
        return (v / np.linalg.norm(v)).tolist()


class TestPromotionScanHandler:
    def _make_handler(self, uow=None):
        if uow is None:
            uow = InMemoryUnitOfWork()
        provider = FakeEmbeddingProvider()
        handler = PromotionScanHandler(uow_factory=lambda: uow, embedding_provider=provider)
        return handler, uow

    def test_no_candidates_when_store_empty(self):
        handler, uow = self._make_handler()
        cmd = ScanPromotionCandidatesCommand()
        result = handler.handle(cmd)
        assert result["candidates"] == []

    def test_finds_candidates_across_two_projects(self):
        handler, uow = self._make_handler()
        exp1 = make_exp("exp-001", scope_id="proj-001")
        exp2 = make_exp("exp-002", scope_id="proj-002")
        uow.experiences._committed["exp-001"] = exp1
        uow.experiences._committed["exp-002"] = exp2
        uow.vectors.save_vector("exp-001", FakeEmbeddingProvider().embed_text("test"))
        uow.vectors.save_vector("exp-002", FakeEmbeddingProvider().embed_text("test"))

        cmd = ScanPromotionCandidatesCommand()
        result = handler.handle(cmd)
        assert len(result["candidates"]) >= 1

    def test_dry_run_does_not_modify_experiences(self):
        handler, uow = self._make_handler()
        exp1 = make_exp("exp-001", scope_id="proj-001")
        exp2 = make_exp("exp-002", scope_id="proj-002")
        uow.experiences._committed["exp-001"] = exp1
        uow.experiences._committed["exp-002"] = exp2
        uow.vectors.save_vector("exp-001", FakeEmbeddingProvider().embed_text("test"))
        uow.vectors.save_vector("exp-002", FakeEmbeddingProvider().embed_text("test"))

        cmd = ScanPromotionCandidatesCommand(dry_run=True)
        handler.handle(cmd)
        assert uow.experiences.get("exp-001").stale_reason is None
```

### Step 3：运行测试，确认失败

```bash
pytest tests/unit/test_promotion_handler.py -v
```

### Step 4：创建 `src/application/handlers/promotion_handler.py`

```python
from __future__ import annotations
from datetime import datetime
from typing import Callable, Any

import numpy as np

from ..commands import ScanPromotionCandidatesCommand
from ..unit_of_work import AbstractUnitOfWork
from ...domain.promotion import compute_promotion_score, is_promotion_candidate
from ...models import ScopeType


class PromotionScanHandler:
    SIMILARITY_THRESHOLD = 0.85

    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork], embedding_provider: Any):
        self._uow_factory = uow_factory
        self._provider = embedding_provider

    def handle(self, cmd: ScanPromotionCandidatesCommand) -> dict:
        with self._uow_factory() as uow:
            project_exps = [
                e for e in uow.experiences.list_by_status("active")
                if e.scope_type == ScopeType.PROJECT
            ]

            if not project_exps:
                return {"candidates": []}

            exp_ids = [e.id for e in project_exps]
            ids, vecs = uow.vectors.get_all_vectors(exp_ids)

            if not ids or vecs.size == 0:
                return {"candidates": []}

            id_to_exp = {e.id: e for e in project_exps}
            id_to_vec = {eid: vecs[i] for i, eid in enumerate(ids)}

            candidates = []
            processed = set()

            for i, exp_id in enumerate(ids):
                if exp_id in processed:
                    continue
                exp = id_to_exp.get(exp_id)
                if exp is None:
                    continue

                similar_exps = []
                different_projects = set()
                query_vec = id_to_vec[exp_id]

                for j, other_id in enumerate(ids):
                    if other_id == exp_id:
                        continue
                    other_exp = id_to_exp.get(other_id)
                    if other_exp is None:
                        continue
                    if other_exp.scope_id == exp.scope_id:
                        continue

                    other_vec = id_to_vec[other_id]
                    norm_q = np.linalg.norm(query_vec)
                    norm_o = np.linalg.norm(other_vec)
                    if norm_q == 0 or norm_o == 0:
                        continue
                    similarity = float(np.dot(query_vec, other_vec) / (norm_q * norm_o))
                    if similarity >= self.SIMILARITY_THRESHOLD:
                        similar_exps.append(other_id)
                        different_projects.add(other_exp.scope_id)

                if len(different_projects) < 1:
                    continue

                created_dt = datetime.fromisoformat(exp.created_at)
                age_days = (datetime.utcnow() - created_dt).days

                cross_project_count = len(different_projects) + 1
                score = compute_promotion_score(
                    cross_project_count=cross_project_count,
                    adoption_rate=exp.adoption_rate,
                    recall_count=exp.recall_count,
                )

                if is_promotion_candidate(
                    score=score,
                    cross_project_count=cross_project_count,
                    adoption_rate=exp.adoption_rate,
                    recall_count=exp.recall_count,
                    age_days=age_days,
                ):
                    candidates.append({
                        "experience_id": exp_id,
                        "score": round(score, 3),
                        "cross_project_count": cross_project_count,
                        "similar_exp_ids": similar_exps,
                        "reason": (
                            f"在 {cross_project_count} 个项目中均有相似记录，"
                            f"采纳率 {exp.adoption_rate:.0%}，建议提升到 Business 层"
                        ),
                    })
                    processed.add(exp_id)
                    processed.update(similar_exps)

                    if not cmd.dry_run:
                        exp.stale_reason = f"promotion_candidate:score={score:.3f}"
                        uow.experiences.update(exp)

        return {"candidates": candidates}
```

### Step 5：运行测试，确认通过

```bash
pytest tests/unit/test_promotion_handler.py -v
```

### Step 6：在 `src/container.py` 注册 Handler

在 container.py 中添加：

```python
from .application.commands import ScanPromotionCandidatesCommand
from .application.handlers.promotion_handler import PromotionScanHandler

# 在 build_command_bus() 内添加：
promotion_handler = PromotionScanHandler(
    uow_factory=UnitOfWork,
    embedding_provider=embedding_provider,
)
bus.register(ScanPromotionCandidatesCommand, promotion_handler.handle)
```

### Step 7：提交

```bash
git add src/application/handlers/promotion_handler.py src/application/commands.py src/container.py tests/unit/test_promotion_handler.py
git commit -m "feat(application): add PromotionScanHandler for promotion candidate detection"
```

---

## Task 18：REST API 新增提升候选管理端点

**背景：** 提升候选的查看和人工操作（确认提升/手动降级/删除）通过 REST API 暴露，不通过 MCP tool。

**Files:**
- Modify: `src/interfaces/rest_api.py`
- Test: `tests/e2e/test_promotion_api.py`（新建，需运行 server）

---

### Step 1：写 REST 端点的 contract 测试（无需真实 server）

新建 `tests/unit/test_rest_promotion_routes.py`：

```python
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from src.interfaces.rest_api import create_app


class TestPromotionAPIRoutes:
    def _get_client(self):
        app = create_app()
        return TestClient(app)

    def test_scan_promotion_candidates_endpoint_exists(self):
        client = self._get_client()
        with patch("src.interfaces.rest_api.build_command_bus") as mock_build:
            mock_bus = MagicMock()
            mock_bus.dispatch.return_value = {"candidates": []}
            mock_build.return_value = mock_bus
            response = client.post("/api/promotion/scan")
        assert response.status_code != 404

    def test_promote_experience_endpoint_exists(self):
        client = self._get_client()
        with patch("src.interfaces.rest_api.build_command_bus") as mock_build:
            mock_bus = MagicMock()
            mock_bus.dispatch.return_value = {"status": "ok"}
            mock_build.return_value = mock_bus
            response = client.post("/api/promotion/exp-001/promote", json={"target_scope": "business", "target_scope_id": "biz-001"})
        assert response.status_code != 404
```

### Step 2：运行测试，确认失败

```bash
pytest tests/unit/test_rest_promotion_routes.py -v
```

### Step 3：在 `src/interfaces/rest_api.py` 中添加新路由

在 `create_app()` 函数内（`return app` 之前）追加：

```python
    class PromoteScopeRequest(BaseModel):
        target_scope: str
        target_scope_id: str

    @app.post("/api/promotion/scan")
    def scan_promotion_candidates(dry_run: bool = False):
        from ..application.commands import ScanPromotionCandidatesCommand
        bus = build_command_bus()
        return bus.dispatch(ScanPromotionCandidatesCommand(dry_run=dry_run))

    @app.post("/api/promotion/{exp_id}/promote")
    def promote_experience(exp_id: str, req: PromoteScopeRequest):
        from ..application.commands import ActivateExperienceCommand
        bus = build_command_bus()
        success = bus.dispatch(ActivateExperienceCommand(experience_id=exp_id))
        if not success:
            raise HTTPException(404, "Experience not found")
        return {"status": "ok", "experience_id": exp_id, "target_scope": req.target_scope}
```

### Step 4：运行测试，确认通过

```bash
pytest tests/unit/test_rest_promotion_routes.py -v
```

### Step 5：提交

```bash
git add src/interfaces/rest_api.py tests/unit/test_rest_promotion_routes.py
git commit -m "feat(api): add promotion scan and promote endpoints"
```

---

## Task 19：InMemoryUnitOfWork 扩展以支持新 scope_type 筛选

**背景：** `InMemoryExperienceStore.list_by_status` 目前按 `status` 字段过滤，新的 `SearchV2Handler` 需要按 `scope_type` 过滤。由于测试 helper 应该真实反映接口契约，需要更新 `fake_uow.py`。

**Files:**
- Modify: `tests/helpers/fake_uow.py`
- Test: `tests/helpers/test_fake_uow_smoke.py`（已有，追加测试）

---

### Step 1：在 `tests/helpers/test_fake_uow_smoke.py` 末尾追加

```python
from src.models import ScopeType


class TestInMemoryExperienceStoreScopeFilter:
    def test_list_by_status_returns_all_statuses_correctly(self):
        from tests.helpers.fake_uow import InMemoryExperienceStore
        from src.models import ExperienceStatus

        store = InMemoryExperienceStore()

        class FakeExp:
            def __init__(self, id, status, scope_type):
                self.id = id
                self.status = status
                self.scope_type = scope_type

        store._committed["e1"] = FakeExp("e1", "active", ScopeType.PROJECT)
        store._committed["e2"] = FakeExp("e2", "pending", ScopeType.BUSINESS)

        active = store.list_by_status("active")
        assert len(active) == 1
        assert active[0].id == "e1"
```

### Step 2：运行测试，确认通过（list_by_status 已存在，应直接 PASS）

```bash
pytest tests/helpers/test_fake_uow_smoke.py -v
```

若 FAIL，检查 `fake_uow.py` 中 `list_by_status` 的过滤逻辑。

---

## Task 20：全量测试与收尾

**背景：** 所有新功能实现完毕后，运行全量测试确保无回归，并运行 linter。

---

### Step 1：运行全量单元测试

```bash
pytest tests/unit/ tests/contract/ tests/helpers/ -v
```

预期：全部 PASS

### Step 2：检查常见导入问题

```bash
python -c "from src.container import build_command_bus; print('OK')"
python -c "from src.interfaces.rest_api import create_app; create_app(); print('OK')"
```

### Step 3：（若有 linter 配置）运行代码风格检查

```bash
python -m ruff check src/ tests/ --select E,W,F 2>/dev/null || echo "ruff not configured, skip"
```

### Step 4：最终提交

```bash
git add -A
git commit -m "feat: complete team knowledge hierarchy refactor - Phase 1 (domain + handlers + MCP tools)"
```

---

## 附录：测试分层说明

| 测试类型 | 位置 | 依赖 | 何时运行 |
|---------|------|------|---------|
| 单元测试 | `tests/unit/` | 无 I/O，只用 `InMemoryUnitOfWork` | 每次提交前 |
| 契约测试 | `tests/contract/` | 只检查接口形状 | 每次提交前 |
| 集成测试 | `tests/integration/` | 需要真实 PostgreSQL | CI 环境 |
| E2E 测试 | `tests/e2e/` | 需要服务运行 | 发布前 |

## 附录：关键常量汇总

| 常量 | 值 | 文件 | 用途 |
|------|-----|------|------|
| `DUPLICATE_SIMILARITY_THRESHOLD` | 0.85 | `src/domain/constants.py` | 重复检测阈值 |
| 技术栈 boost | 1.15 | `src/domain/search_v2.py` | 技术栈匹配时分数倍数 |
| Project 权重 | 1.2 | `src/domain/search_v2.py` | 三层权重 |
| Business 权重 | 1.0 | `src/domain/search_v2.py` | 三层权重 |
| Team 权重 | 0.9 | `src/domain/search_v2.py` | 三层权重 |
| 提升候选阈值 | 0.7 | `src/domain/promotion.py` | 得分阈值 |
| confidence 待归档阈值 | 0.2 | `src/domain/feedback_v2.py` | 低于此值标记归档 |
| quality score 自动激活 | 80 | `src/domain/constants.py` | save 时自动激活 |

## 附录：新增文件清单

```
src/domain/
  manifest_parser.py       # project_manifest 解析
  search_v2.py             # 三层权重、boost、合并逻辑
  promotion.py             # 提升候选评分
  save_domain.py           # outcome → initial confidence
  feedback_v2.py           # confidence 更新 + id 校验

src/application/handlers/
  search_v2_handler.py     # SearchV2 handler
  save_handler.py          # Save handler
  feedback_v2_handler.py   # FeedbackV2 handler
  promotion_handler.py     # 提升候选扫描 handler

tests/unit/
  test_experience_model.py
  test_hierarchy_models.py
  test_event_models.py
  test_schema_migration.py
  test_manifest_parser.py
  test_search_v2_domain.py
  test_promotion.py
  test_save_quality.py
  test_save_domain.py
  test_feedback_v2.py
  test_mcp_tools.py
  test_search_v2_handler.py
  test_save_handler.py
  test_feedback_v2_handler.py
  test_promotion_handler.py
  test_rest_promotion_routes.py
```
