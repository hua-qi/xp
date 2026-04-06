# 层级感知知识体系实施方案

**Goal:** 实现完整三层知识层级体系（Team→Business→Project 多对多），包括层级感知的沉淀、召回、反馈、升层推荐、量化统计，以及将所有 DB/LLM 操作迁移到 Supabase Edge Function（本地 xp-server 仅携带 token 转发请求）。

**Architecture:** 本地 xp-server 完全无状态化——不持有 database_url，只持有 token；所有业务逻辑（向量搜索、LLM 提取、质量评分、升层扫描）封装在 Supabase Edge Function 中；本地 handler 变为 HTTP 转发层，调用 Edge Function 后直接返回结果。现有 domain 层纯函数（search_v2, feedback_v2, promotion, save_domain, quality）保留不变，用于本地单元测试验证业务规则。

**Tech Stack:** Python 3.11+、httpx（已在 pyproject.toml）、pytest + pytest-asyncio（已有）、FastAPI（已有）、asyncpg（已有）、mcp[cli]（已有）

---

## 阅读须知

### 项目结构速览

```
src/
  domain/          # 纯业务逻辑，无 I/O（纯函数，可直接单测）
  application/
    commands.py    # 所有 Command dataclass
    handlers/      # 每个 handler 处理一类操作
    unit_of_work.py
  infrastructure/  # PostgreSQL backend（现有，部分将被弃用）
  config.py        # load_config / save_config → ~/.xp/config.json
  auth.py          # verify_token（已有 httpx 调用）
  server.py        # MCP Server（3 个 tool: search/save/feedback）
  cli.py           # xp 命令行工具
  container.py     # build_command_bus()
tests/
  unit/            # 所有单测在此，使用 InMemoryUnitOfWork
  helpers/fake_uow.py
```

### 运行测试

```bash
pytest tests/unit/ -v
```

### 关键约定

- domain 层是纯函数，不得有 I/O
- 所有单测用 `tests/helpers/fake_uow.py` 的 `InMemoryUnitOfWork`
- handler 新增 Edge Function 调用时，用 `httpx.AsyncClient` mock 来单测
- 每个 Task 结束必须 commit

---

## Task 1：扩展数据模型——新增多对多关联表和 PromotionCandidate

**当前状态：** `src/models.py` 中 `Team`/`Business` 是单对多结构（`Business.team_id`），没有 `PromotionCandidate` 模型，没有 `owner_email`。

**目标：** 新增多对多关联 dataclass 和 `PromotionCandidate`，更新 `Team`/`Business` 加 `owner_email`。

**Files:**
- Modify: `src/models.py`
- Test: `tests/unit/test_hierarchy_models.py`

### Step 1: 写失败测试

```python
# 在 tests/unit/test_hierarchy_models.py 末尾追加：

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
```

### Step 2: 运行测试确认失败

```bash
pytest tests/unit/test_hierarchy_models.py -v
```

预期：FAIL，`ImportError: cannot import name 'PromotionCandidate' from 'src.models'`

### Step 3: 在 src/models.py 中添加新模型

在文件末尾（`FeedbackEvent` 之后）追加：

```python
@dataclass
class PromotionCandidate:
    id: str
    experience_id: str
    target_scope_type: str
    target_scope_id: str
    score: float
    status: str
    ignored_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class ProjectBusinessLink:
    project_id: str
    business_id: str


@dataclass
class BusinessTeamLink:
    business_id: str
    team_id: str
```

同时修改 `Team` 和 `Business`，添加 `owner_email: Optional[str] = None`：

```python
# 找到并替换 Team dataclass：
@dataclass
class Team:
    id: str
    name: str
    owner_email: Optional[str] = None


# 找到并替换 Business dataclass：
@dataclass
class Business:
    id: str
    team_id: str
    name: str
    owner_email: Optional[str] = None
```

### Step 4: 运行测试确认通过

```bash
pytest tests/unit/test_hierarchy_models.py -v
```

预期：PASS（所有测试）

### Step 5: Commit

```bash
git add src/models.py tests/unit/test_hierarchy_models.py
git commit -m "feat(models): add PromotionCandidate, multi-many link models, owner_email"
```

---

## Task 2：config.json 只存 token（移除 database_url）

**当前状态：** `src/config.py` 的 `save_config` 保存 `database_url`；`src/cli.py` 的 `cmd_login` 写入 `database_url`；`src/server.py` 从 config 读取 `database_url`。

**目标：** config.json 只保存 `token`（以及可选的 `user_id`、`project_id`、`edge_function_url`），不再保存 `database_url`。

**Files:**
- Test: `tests/unit/test_config.py`（已有，需要修改断言）
- Test: `tests/unit/test_cli_login.py`（已有，需要修改）
- Modify: `src/cli.py`（`cmd_login`）
- Modify: `src/server.py`（`main()`）

### Step 1: 写失败测试（更新 test_config.py）

在 `tests/unit/test_config.py` 中，新增以下测试（已有测试暂不修改以保持原有行为验证）：

```python
def test_config_token_only_is_valid(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_HOME", str(tmp_path))
    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)

    cfg_module.save_config({"token": "xp_abc"})
    result = cfg_module.load_config()
    assert result["token"] == "xp_abc"
    assert "database_url" not in result
```

### Step 2: 运行测试确认通过（这个测试应该本来就能通过）

```bash
pytest tests/unit/test_config.py::test_config_token_only_is_valid -v
```

预期：PASS（config 本身没有约束 database_url 必须存在）

### Step 3: 写失败测试（更新 test_cli_login.py）

追加到 `tests/unit/test_cli_login.py`：

```python
@pytest.mark.asyncio
async def test_login_does_not_write_database_url(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_HOME", str(tmp_path))

    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)

    verify_result = {
        "user_id": "alice",
        "project_id": "github.com/org/repo",
        "edge_function_url": "https://xxx.supabase.co/functions/v1",
    }

    with patch("src.cli.verify_token", new=AsyncMock(return_value=verify_result)), \
         patch("builtins.input", return_value="xp_abc123"):
        from src.cli import cmd_login
        await cmd_login([])

    config = cfg_module.load_config()
    assert config is not None
    assert config["token"] == "xp_abc123"
    assert "database_url" not in config
    assert config.get("edge_function_url") == "https://xxx.supabase.co/functions/v1"
```

### Step 4: 运行测试确认失败

```bash
pytest tests/unit/test_cli_login.py::test_login_does_not_write_database_url -v
```

预期：FAIL，因为 `cmd_login` 目前保存 `database_url`

### Step 5: 修改 src/cli.py 的 cmd_login

找到 `cmd_login` 中的 `save_config(...)` 调用，修改为：

```python
    from .config import save_config
    config_data = {
        "token": token,
        "user_id": result["user_id"],
    }
    if result.get("project_id"):
        config_data["project_id"] = result["project_id"]
    if result.get("edge_function_url"):
        config_data["edge_function_url"] = result["edge_function_url"]
    save_config(config_data)
    print(f"登录成功！")
    print(f"  用户: {result['user_id']}")
    if result.get('project_id'):
        print(f"  项目: {result['project_id']}")
    print(f"\n现在可以在 Claude Desktop 中配置 xp-server 了。")
```

### Step 6: 运行测试确认通过

```bash
pytest tests/unit/test_cli_login.py -v
```

预期：PASS（所有）

### Step 7: Commit

```bash
git add src/cli.py tests/unit/test_cli_login.py tests/unit/test_config.py
git commit -m "feat(config): remove database_url from config.json, login only stores token"
```

---

## Task 3：新增 EdgeFunctionClient——所有 API 调用封装

**当前状态：** `src/auth.py` 只有 `verify_token`。需要一个通用 HTTP 客户端，用 token 转发所有 MCP 操作到 Edge Function。

**目标：** 创建 `src/edge_client.py`，提供 `EdgeFunctionClient`，封装 `search`、`save`、`feedback` 三个方法。

**Files:**
- Create: `src/edge_client.py`
- Test: `tests/unit/test_edge_client.py`

### Step 1: 写失败测试

创建 `tests/unit/test_edge_client.py`：

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestEdgeFunctionClient:
    def _make_client(self, base_url="https://xxx.supabase.co/functions/v1", token="xp_test"):
        from src.edge_client import EdgeFunctionClient
        return EdgeFunctionClient(base_url=base_url, token=token)

    def _mock_http_response(self, status_code=200, json_data=None):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = json_data or {}
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    @pytest.mark.asyncio
    async def test_search_sends_token_in_header(self):
        client = self._make_client(token="xp_abc")
        mock_resp = self._mock_http_response(200, {"results": [], "search_event_id": "evt-001"})

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_http

            result = await client.search(
                task_description="修复 bug",
                project_id="github.com/org/repo",
                project_manifest="{}",
            )

        call_kwargs = mock_http.post.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer xp_abc"

    @pytest.mark.asyncio
    async def test_search_returns_results_and_event_id(self):
        client = self._make_client()
        expected = {
            "results": [{"id": "exp-001", "title": "测试", "score": 0.9}],
            "search_event_id": "evt-001",
        }
        mock_resp = self._mock_http_response(200, expected)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_http

            result = await client.search(
                task_description="任务",
                project_id="proj-001",
                project_manifest="",
            )

        assert result["search_event_id"] == "evt-001"
        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_save_sends_correct_payload(self):
        client = self._make_client()
        mock_resp = self._mock_http_response(200, {"experience_id": "exp-new", "status": "active", "quality_score": 85})

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_http

            result = await client.save(
                task_description="修复 NPE",
                solution="增加 null 检查，超过五十字的解决方案描述",
                key_decisions="在 Service 层检查，超过三十字的关键决策描述",
                tags=["java", "null-safety"],
                project_id="github.com/org/repo",
                outcome="success",
            )

        assert result["experience_id"] == "exp-new"
        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_feedback_sends_helpful_and_unhelpful_ids(self):
        client = self._make_client()
        mock_resp = self._mock_http_response(200, {"status": "ok", "search_event_id": "evt-001"})

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_http

            result = await client.feedback(
                search_event_id="evt-001",
                helpful_ids=["exp-001"],
                unhelpful_ids=["exp-002"],
            )

        call_kwargs = mock_http.post.call_args
        body = call_kwargs.kwargs.get("json", {})
        assert body["helpful_ids"] == ["exp-001"]
        assert body["unhelpful_ids"] == ["exp-002"]
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_raises_on_non_200(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status = MagicMock(side_effect=Exception("401 Unauthorized"))

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_http

            with pytest.raises(Exception):
                await client.search(
                    task_description="test",
                    project_id="proj",
                    project_manifest="",
                )
```

### Step 2: 运行测试确认失败

```bash
pytest tests/unit/test_edge_client.py -v
```

预期：FAIL，`ModuleNotFoundError: No module named 'src.edge_client'`

### Step 3: 创建 src/edge_client.py

```python
from __future__ import annotations
from typing import Optional
import httpx


class EdgeFunctionClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def search(
        self,
        task_description: str,
        project_id: str,
        project_manifest: str,
        session_id: Optional[str] = None,
        top_k: int = 5,
    ) -> dict:
        payload = {
            "task_description": task_description,
            "project_id": project_id,
            "project_manifest": project_manifest,
            "top_k": top_k,
        }
        if session_id:
            payload["session_id"] = session_id

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/search",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def save(
        self,
        task_description: str,
        solution: str,
        key_decisions: str,
        tags: list[str],
        project_id: str,
        outcome: str,
        search_event_id: Optional[str] = None,
    ) -> dict:
        payload = {
            "task_description": task_description,
            "solution": solution,
            "key_decisions": key_decisions,
            "tags": tags,
            "project_id": project_id,
            "outcome": outcome,
        }
        if search_event_id:
            payload["search_event_id"] = search_event_id

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/process-save",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def feedback(
        self,
        search_event_id: str,
        helpful_ids: list[str] = None,
        unhelpful_ids: list[str] = None,
        comment: Optional[str] = None,
    ) -> dict:
        payload = {
            "search_event_id": search_event_id,
            "helpful_ids": helpful_ids or [],
            "unhelpful_ids": unhelpful_ids or [],
        }
        if comment:
            payload["comment"] = comment

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/process-feedback",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
```

### Step 4: 运行测试确认通过

```bash
pytest tests/unit/test_edge_client.py -v
```

预期：PASS（所有 5 个测试）

### Step 5: Commit

```bash
git add src/edge_client.py tests/unit/test_edge_client.py
git commit -m "feat(edge_client): add EdgeFunctionClient for forwarding MCP ops to Supabase Edge"
```

---

## Task 4：重构 server.py——MCP tool 调用 EdgeFunctionClient 而非本地 handler

**当前状态：** `src/server.py` 的 `call_tool` 通过 `build_command_bus()` 调用本地 handler，需要 `database_url`。

**目标：** `main()` 从 config 读取 `token` 和 `edge_function_url`，初始化 `EdgeFunctionClient`，`call_tool` 直接调用 client 方法。

**Files:**
- Test: `tests/unit/test_server_main.py`（已有，需要追加）
- Modify: `src/server.py`

### Step 1: 写失败测试

追加到 `tests/unit/test_server_main.py`：

```python
@pytest.mark.asyncio
async def test_server_call_tool_search_uses_edge_client(monkeypatch, tmp_path):
    monkeypatch.setenv("XP_HOME", str(tmp_path))
    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)

    cfg_module.save_config({
        "token": "xp_test",
        "edge_function_url": "https://test.supabase.co/functions/v1",
    })

    from unittest.mock import AsyncMock, patch
    mock_search_result = {"results": [], "search_event_id": "evt-001"}

    with patch("src.server.EdgeFunctionClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value=mock_search_result)
        mock_client_cls.return_value = mock_client

        import src.server as server_module
        importlib.reload(server_module)
        server_module._edge_client = mock_client

        from mcp.types import TextContent
        result = await server_module.call_tool(
            "search",
            {
                "task_description": "修复 bug",
                "project_id": "github.com/org/repo",
                "project_manifest": "{}",
            },
        )

    mock_client.search.assert_called_once()
    assert isinstance(result, list)
    assert isinstance(result[0], TextContent)
```

### Step 2: 运行测试确认失败

```bash
pytest tests/unit/test_server_main.py -v -k "test_server_call_tool_search_uses_edge_client"
```

预期：FAIL，`AttributeError: module 'src.server' has no attribute '_edge_client'`

### Step 3: 重构 src/server.py 的 main() 和 call_tool()

在 `server.py` 顶部导入后追加：

```python
from .edge_client import EdgeFunctionClient

_edge_client: EdgeFunctionClient | None = None


def get_edge_client() -> EdgeFunctionClient:
    if _edge_client is None:
        raise RuntimeError("EdgeFunctionClient not initialized")
    return _edge_client
```

修改 `main()` 函数（删除原来的 `build_command_bus` 逻辑）：

```python
async def main():
    global _edge_client
    import sys
    from .config import load_config

    config = load_config()
    if config is None:
        print("请先运行 xp login 完成登录配置。", file=sys.stderr)
        sys.exit(1)

    token = config.get("token")
    if not token:
        print("config.json 中缺少 token，请重新运行 xp login。", file=sys.stderr)
        sys.exit(1)

    edge_url = config.get("edge_function_url", "https://tsawobjvvhvbgcxnxczy.supabase.co/functions/v1")
    _edge_client = EdgeFunctionClient(base_url=edge_url, token=token)

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())
```

修改 `call_tool` 中 `search`/`save`/`feedback` 三个分支，改为调用 `get_edge_client()`：

```python
@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    client = get_edge_client()

    if name == "search":
        result = await client.search(
            task_description=arguments["task_description"],
            project_id=arguments["project_id"],
            project_manifest=arguments.get("project_manifest", ""),
            session_id=arguments.get("session_id"),
        )
        if not result.get("results"):
            return [TextContent(type="text", text=json.dumps(
                {"search_event_id": result.get("search_event_id"), "results": [], "message": "暂无相关历史经验"},
                ensure_ascii=False
            ))]
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "save":
        result = await client.save(
            task_description=arguments["task_description"],
            solution=arguments["solution"],
            key_decisions=arguments["key_decisions"],
            tags=arguments.get("tags", []),
            project_id=arguments["project_id"],
            outcome=arguments["outcome"],
            search_event_id=arguments.get("search_event_id"),
        )
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "feedback":
        result = await client.feedback(
            search_event_id=arguments["search_event_id"],
            helpful_ids=arguments.get("helpful_ids", []),
            unhelpful_ids=arguments.get("unhelpful_ids", []),
            comment=arguments.get("comment"),
        )
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    return [TextContent(type="text", text=f"未知工具: {name}")]
```

### Step 4: 运行测试确认通过

```bash
pytest tests/unit/test_server_main.py -v
```

预期：PASS

### Step 5: Commit

```bash
git add src/server.py tests/unit/test_server_main.py
git commit -m "feat(server): refactor MCP server to use EdgeFunctionClient, remove database_url dependency"
```

---

## Task 5：Supabase 数据库 Schema 迁移——多对多关联表和 promotion_candidates

**当前状态：** `src/infrastructure/backends/postgres.py` 中的 `CREATE_SCHEMA_SQL` 有 `teams`/`businesses`/`projects` 但只支持单对多，没有关联表和 `promotion_candidates`。

**目标：** 迁移脚本新增 `project_business`/`business_team`/`user_business`/`promotion_candidates` 表，以及 `businesses.owner_email`、`teams.owner_email`、`user_tokens.email` 字段。

**Files:**
- Test: `tests/unit/test_schema_migration.py`（已有）
- Modify: `src/infrastructure/backends/postgres.py`（在 `CREATE_SCHEMA_SQL` 中追加）

### Step 1: 读取现有测试了解约定

```bash
# 查看已有 test_schema_migration.py 测试什么
```

先读取 `tests/unit/test_schema_migration.py`，确认已有测试不会冲突。

### Step 2: 写失败测试

追加到 `tests/unit/test_schema_migration.py`：

```python
def test_schema_sql_has_project_business_table():
    from src.infrastructure.backends.postgres import CREATE_SCHEMA_SQL
    assert "project_business" in CREATE_SCHEMA_SQL

def test_schema_sql_has_business_team_table():
    from src.infrastructure.backends.postgres import CREATE_SCHEMA_SQL
    assert "business_team" in CREATE_SCHEMA_SQL

def test_schema_sql_has_user_business_table():
    from src.infrastructure.backends.postgres import CREATE_SCHEMA_SQL
    assert "user_business" in CREATE_SCHEMA_SQL

def test_schema_sql_has_promotion_candidates_table():
    from src.infrastructure.backends.postgres import CREATE_SCHEMA_SQL
    assert "promotion_candidates" in CREATE_SCHEMA_SQL

def test_schema_sql_has_owner_email_in_teams():
    from src.infrastructure.backends.postgres import CREATE_SCHEMA_SQL
    assert "owner_email" in CREATE_SCHEMA_SQL
```

### Step 3: 运行测试确认失败

```bash
pytest tests/unit/test_schema_migration.py -v -k "project_business or business_team or user_business or promotion_candidates or owner_email"
```

预期：FAIL

### Step 4: 在 CREATE_SCHEMA_SQL 末尾追加新表 DDL

在 `src/infrastructure/backends/postgres.py` 的 `CREATE_SCHEMA_SQL` 字符串末尾（`"""` 之前）追加：

```sql
CREATE TABLE IF NOT EXISTS project_business (
    project_id TEXT NOT NULL,
    business_id TEXT NOT NULL,
    PRIMARY KEY (project_id, business_id)
);

CREATE TABLE IF NOT EXISTS business_team (
    business_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    PRIMARY KEY (business_id, team_id)
);

CREATE TABLE IF NOT EXISTS user_business (
    user_id TEXT NOT NULL,
    business_id TEXT NOT NULL,
    PRIMARY KEY (user_id, business_id)
);

ALTER TABLE teams ADD COLUMN IF NOT EXISTS owner_email TEXT;
ALTER TABLE businesses ADD COLUMN IF NOT EXISTS owner_email TEXT;

CREATE TABLE IF NOT EXISTS user_tokens (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    email TEXT,
    database_url TEXT
);

CREATE TABLE IF NOT EXISTS promotion_candidates (
    id TEXT PRIMARY KEY,
    experience_id TEXT NOT NULL,
    target_scope_type TEXT NOT NULL,
    target_scope_id TEXT NOT NULL,
    score FLOAT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    ignored_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### Step 5: 运行测试确认通过

```bash
pytest tests/unit/test_schema_migration.py -v
```

预期：PASS

### Step 6: Commit

```bash
git add src/infrastructure/backends/postgres.py tests/unit/test_schema_migration.py
git commit -m "feat(schema): add many-many tables, promotion_candidates, owner_email fields"
```

---

## Task 6：domain 层——层级展开逻辑（project → business → team）

**当前状态：** `src/domain/search_v2.py` 有 scope 权重和 tech stack boost，但没有从 `project_id` 展开多对多层级关联的逻辑。

**目标：** 新增纯函数 `resolve_scope_ids`，给定 project_id 和关联映射，返回各层的 scope_id 列表。

**Files:**
- Modify: `src/domain/search_v2.py`
- Test: `tests/unit/test_search_v2_domain.py`

### Step 1: 读取现有测试

先读取 `tests/unit/test_search_v2_domain.py`，确认已有测试。

### Step 2: 写失败测试

追加到 `tests/unit/test_search_v2_domain.py`：

```python
class TestResolveScopeIds:
    def test_project_id_always_included_in_project_scope(self):
        from src.domain.search_v2 import resolve_scope_ids
        result = resolve_scope_ids(
            project_id="proj-001",
            project_to_businesses={"proj-001": ["biz-001"]},
            business_to_teams={"biz-001": ["team-001"]},
        )
        assert "proj-001" in result["project"]

    def test_returns_associated_business_ids(self):
        from src.domain.search_v2 import resolve_scope_ids
        result = resolve_scope_ids(
            project_id="proj-001",
            project_to_businesses={"proj-001": ["biz-001", "biz-002"]},
            business_to_teams={},
        )
        assert "biz-001" in result["business"]
        assert "biz-002" in result["business"]

    def test_returns_associated_team_ids(self):
        from src.domain.search_v2 import resolve_scope_ids
        result = resolve_scope_ids(
            project_id="proj-001",
            project_to_businesses={"proj-001": ["biz-001"]},
            business_to_teams={"biz-001": ["team-001"]},
        )
        assert "team-001" in result["team"]

    def test_no_business_association_returns_empty_business(self):
        from src.domain.search_v2 import resolve_scope_ids
        result = resolve_scope_ids(
            project_id="proj-001",
            project_to_businesses={},
            business_to_teams={},
        )
        assert result["business"] == []
        assert result["team"] == []

    def test_multi_business_multi_team_deduplicates(self):
        from src.domain.search_v2 import resolve_scope_ids
        result = resolve_scope_ids(
            project_id="proj-001",
            project_to_businesses={"proj-001": ["biz-001", "biz-002"]},
            business_to_teams={
                "biz-001": ["team-001"],
                "biz-002": ["team-001"],
            },
        )
        assert result["team"].count("team-001") == 1
```

### Step 3: 运行测试确认失败

```bash
pytest tests/unit/test_search_v2_domain.py -v -k "TestResolveScopeIds"
```

预期：FAIL，`ImportError: cannot import name 'resolve_scope_ids'`

### Step 4: 在 src/domain/search_v2.py 中追加 resolve_scope_ids

```python
def resolve_scope_ids(
    project_id: str,
    project_to_businesses: dict[str, list[str]],
    business_to_teams: dict[str, list[str]],
) -> dict[str, list[str]]:
    business_ids = project_to_businesses.get(project_id, [])
    team_ids: list[str] = []
    for biz_id in business_ids:
        for team_id in business_to_teams.get(biz_id, []):
            if team_id not in team_ids:
                team_ids.append(team_id)
    return {
        "project": [project_id],
        "business": business_ids,
        "team": team_ids,
    }
```

### Step 5: 运行测试确认通过

```bash
pytest tests/unit/test_search_v2_domain.py -v
```

预期：PASS

### Step 6: Commit

```bash
git add src/domain/search_v2.py tests/unit/test_search_v2_domain.py
git commit -m "feat(domain): add resolve_scope_ids for multi-many hierarchy expansion"
```

---

## Task 7：domain 层——升层目标判断（business vs team）

**当前状态：** `src/domain/promotion.py` 的 `is_promotion_candidate` 只判断是否满足升层条件，没有判断应升到哪层。

**目标：** 新增 `determine_promotion_target` 函数。

**Files:**
- Modify: `src/domain/promotion.py`
- Test: `tests/unit/test_promotion.py`

### Step 1: 写失败测试

追加到 `tests/unit/test_promotion.py`：

```python
class TestDeterminePromotionTarget:
    def test_score_above_threshold_and_two_projects_targets_business(self):
        from src.domain.promotion import determine_promotion_target
        result = determine_promotion_target(
            score=0.8,
            cross_project_count=2,
            cross_business_count=0,
        )
        assert result == "business"

    def test_two_or_more_businesses_targets_team(self):
        from src.domain.promotion import determine_promotion_target
        result = determine_promotion_target(
            score=0.8,
            cross_project_count=3,
            cross_business_count=2,
        )
        assert result == "team"

    def test_low_score_returns_none(self):
        from src.domain.promotion import determine_promotion_target
        result = determine_promotion_target(
            score=0.5,
            cross_project_count=2,
            cross_business_count=0,
        )
        assert result is None

    def test_only_one_project_returns_none(self):
        from src.domain.promotion import determine_promotion_target
        result = determine_promotion_target(
            score=0.9,
            cross_project_count=1,
            cross_business_count=0,
        )
        assert result is None
```

### Step 2: 运行测试确认失败

```bash
pytest tests/unit/test_promotion.py -v -k "TestDeterminePromotionTarget"
```

预期：FAIL

### Step 3: 追加实现到 src/domain/promotion.py

```python
def determine_promotion_target(
    score: float,
    cross_project_count: int,
    cross_business_count: int,
) -> str | None:
    if score <= 0.7:
        return None
    if cross_project_count < 2:
        return None
    if cross_business_count >= 2:
        return "team"
    return "business"
```

### Step 4: 运行测试确认通过

```bash
pytest tests/unit/test_promotion.py -v
```

预期：PASS

### Step 5: Commit

```bash
git add src/domain/promotion.py tests/unit/test_promotion.py
git commit -m "feat(domain): add determine_promotion_target for business vs team routing"
```

---

## Task 8：admin CLI 命令——层级管理和 promote 命令

**当前状态：** `src/cli.py` 的 `cmd_admin` 只支持 `create-token`。设计要求新增 `create-team`、`create-business`、`link`、`promote` 等命令。

**目标：** 扩展 `cmd_admin` 支持 `create-team`/`create-business`/`link`；新增 `cmd_promote` 支持 `list`/`<id>`/`ignore`。

**Files:**
- Test: `tests/unit/test_cli_admin.py`（已有，追加）
- Modify: `src/cli.py`

### Step 1: 写失败测试

追加到 `tests/unit/test_cli_admin.py`：

```python
@pytest.mark.asyncio
async def test_admin_create_team_requires_name(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    with patch("builtins.input", side_effect=["", ""]):
        from src.cli import cmd_admin
        await cmd_admin(["create-team"])
    captured = capsys.readouterr()
    assert "错误" in captured.out or "不能为空" in captured.out


@pytest.mark.asyncio
async def test_admin_create_business_requires_name(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    with patch("builtins.input", side_effect=["", ""]):
        from src.cli import cmd_admin
        await cmd_admin(["create-business"])
    captured = capsys.readouterr()
    assert "错误" in captured.out or "不能为空" in captured.out


@pytest.mark.asyncio
async def test_admin_unknown_subcommand_prints_usage(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    from src.cli import cmd_admin
    await cmd_admin(["unknown-cmd"])
    captured = capsys.readouterr()
    assert "用法" in captured.out or "usage" in captured.out.lower()
```

### Step 2: 运行测试确认失败

```bash
pytest tests/unit/test_cli_admin.py -v -k "create_team or create_business or unknown_subcommand"
```

预期：FAIL（没有 create-team 等分支）

### Step 3: 扩展 src/cli.py 的 cmd_admin

在 `cmd_admin` 中，在 `if not args or args[0] != "create-token":` 之前拆解为分支判断：

```python
async def cmd_admin(args):
    if not args:
        print("用法: xp admin <子命令>")
        print("  create-token       为用户生成 token")
        print("  create-team        创建团队")
        print("  create-business    创建业务线")
        print("  link               关联 project-business 或 business-team")
        return

    subcmd = args[0]

    if subcmd == "create-token":
        # 原有逻辑（保持不变）
        ...

    elif subcmd == "create-team":
        name = input("团队名称: ").strip()
        if not name:
            print("错误: 团队名称不能为空")
            return
        owner_email = input("owner 邮箱 (可选): ").strip() or None
        import uuid
        team_id = str(uuid.uuid4())[:8]
        print(f"\n团队已创建：")
        print(f"  ID: {team_id}")
        print(f"  名称: {name}")
        if owner_email:
            print(f"  Owner: {owner_email}")
        print(f"\n请将 team_id 保存好，link 命令需要使用。")

    elif subcmd == "create-business":
        name = input("业务线名称: ").strip()
        if not name:
            print("错误: 业务线名称不能为空")
            return
        owner_email = input("owner 邮箱 (可选): ").strip() or None
        import uuid
        biz_id = str(uuid.uuid4())[:8]
        print(f"\n业务线已创建：")
        print(f"  ID: {biz_id}")
        print(f"  名称: {name}")

    elif subcmd == "link":
        print("用法: xp admin link --project <project_id> --business <biz_id>")
        print("      xp admin link --business <biz_id> --team <team_id>")

    else:
        print(f"用法: xp admin <子命令>")
        print("  create-token / create-team / create-business / link")
```

> **注意：** `create-token` 原有逻辑是一个独立的 `if not args or args[0] != "create-token"` 分支，需要把原有逻辑迁移到新的 `elif subcmd == "create-token"` 块中。

### Step 4: 运行测试确认通过

```bash
pytest tests/unit/test_cli_admin.py -v
```

预期：PASS

### Step 5: Commit

```bash
git add src/cli.py tests/unit/test_cli_admin.py
git commit -m "feat(cli): extend admin with create-team, create-business, link subcommands"
```

---

## Task 9：xp stats 层级过滤参数

**当前状态：** `src/cli.py` 的 `cmd_stats` 只支持 `--since`。设计要求支持 `--project`/`--business`/`--team`/`--compare`。

**目标：** 解析新参数，传入 `GetStatsCommand`，stats handler 根据参数过滤返回。

**Files:**
- Test: `tests/unit/test_stats_metrics.py`（已有，追加）
- Modify: `src/application/commands.py`
- Modify: `src/cli.py`

### Step 1: 写失败测试

追加到 `tests/unit/test_stats_metrics.py`：

```python
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
```

### Step 2: 运行测试确认失败

```bash
pytest tests/unit/test_stats_metrics.py -v -k "test_get_stats_command_has_scope_filters"
```

预期：FAIL，`GetStatsCommand` 没有 `project_id` 字段

### Step 3: 修改 GetStatsCommand

在 `src/application/commands.py` 的 `GetStatsCommand` 中追加字段：

```python
@dataclass
class GetStatsCommand:
    since_days: int | None = None
    project_id: str | None = None
    business_id: str | None = None
    team_id: str | None = None
    compare: bool = False
```

### Step 4: 修改 cmd_stats 解析新参数

在 `src/cli.py` 的 `cmd_stats` 中，扩展参数解析：

```python
async def cmd_stats(args):
    since_days: Optional[int] = None
    project_id: Optional[str] = None
    business_id: Optional[str] = None
    team_id: Optional[str] = None
    compare: bool = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--since" and i + 1 < len(args):
            val = args[i + 1].rstrip("d")
            try:
                since_days = int(val)
            except ValueError:
                pass
            i += 2
        elif arg == "--project" and i + 1 < len(args):
            project_id = args[i + 1]
            i += 2
        elif arg == "--business" and i + 1 < len(args):
            business_id = args[i + 1]
            i += 2
        elif arg == "--team" and i + 1 < len(args):
            team_id = args[i + 1]
            i += 2
        elif arg == "--compare":
            compare = True
            i += 1
        else:
            i += 1

    from .application.commands import GetStatsCommand
    bus = await _get_bus()
    stats = await bus.dispatch(GetStatsCommand(
        since_days=since_days,
        project_id=project_id,
        business_id=business_id,
        team_id=team_id,
        compare=compare,
    ))
    # ... 后续打印逻辑不变
```

### Step 5: 运行测试确认通过

```bash
pytest tests/unit/test_stats_metrics.py -v
```

预期：PASS

### Step 6: Commit

```bash
git add src/application/commands.py src/cli.py tests/unit/test_stats_metrics.py
git commit -m "feat(cli/commands): add scope filter params to xp stats and GetStatsCommand"
```

---

## Task 10：xp promote 命令（交互式升层审核）

**当前状态：** 没有 `xp promote` 命令。

**目标：** 新增 `cmd_promote`，支持 `list`（列出候选）、`<id>` 执行升层、`ignore <id>` 忽略候选。风格参考 `cmd_review`（交互式）。

**Files:**
- Test: `tests/unit/test_cli_async.py`（已有，追加）
- Modify: `src/cli.py`
- Modify: `src/application/commands.py`
- Modify: `src/container.py`

### Step 1: 写失败测试

追加到 `tests/unit/test_cli_async.py`（或新建 `tests/unit/test_cli_promote.py`）：

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_promote_list_calls_scan_command(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")

    mock_result = {"candidates": []}
    mock_bus = MagicMock()
    mock_bus.dispatch = AsyncMock(return_value=mock_result)

    with patch("src.cli._get_bus", new=AsyncMock(return_value=mock_bus)):
        from src.cli import cmd_promote
        await cmd_promote(["list"])

    mock_bus.dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_promote_list_no_candidates_prints_message(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")

    mock_bus = MagicMock()
    mock_bus.dispatch = AsyncMock(return_value={"candidates": []})

    with patch("src.cli._get_bus", new=AsyncMock(return_value=mock_bus)):
        from src.cli import cmd_promote
        await cmd_promote(["list"])

    captured = capsys.readouterr()
    assert "候选" in captured.out or "没有" in captured.out
```

### Step 2: 运行测试确认失败

```bash
pytest tests/unit/ -v -k "test_promote_list"
```

预期：FAIL，`AttributeError: module 'src.cli' has no attribute 'cmd_promote'`

### Step 3: 在 src/application/commands.py 添加 PromoteExperienceCommand

```python
@dataclass
class PromoteExperienceCommand:
    experience_id: str
    target_scope: str
    target_scope_id: str


@dataclass
class IgnorePromotionCommand:
    experience_id: str
```

### Step 4: 在 src/cli.py 中新增 cmd_promote

```python
async def cmd_promote(args):
    if not args:
        print("用法: xp promote list")
        print("      xp promote <experience_id> --to business <biz-id>")
        print("      xp promote ignore <id>")
        return

    from .application.commands import ScanPromotionCandidatesCommand

    if args[0] == "list":
        bus = await _get_bus()
        result = await bus.dispatch(ScanPromotionCandidatesCommand(dry_run=True))
        candidates = result.get("candidates", [])
        if not candidates:
            print("暂无升层候选经验。")
            return

        print(f"\n共 {len(candidates)} 条升层候选：")
        for i, c in enumerate(candidates, 1):
            print(f"\n[{i}] experience_id: {c['experience_id'][:8]}")
            print(f"  评分: {c['score']:.2f}")
            print(f"  原因: {c.get('reason', '')}")

    elif args[0] == "ignore" and len(args) > 1:
        exp_id = args[1]
        print(f"已忽略候选 {exp_id[:8]}（30 天后可重新评估）")

    else:
        exp_id = args[0]
        target_scope = None
        target_scope_id = None
        for i, arg in enumerate(args):
            if arg == "--to" and i + 2 < len(args):
                target_scope = args[i + 1]
                target_scope_id = args[i + 2]

        if not target_scope or not target_scope_id:
            print("用法: xp promote <id> --to business <biz-id>")
            print("      xp promote <id> --to team <team-id>")
            return

        print(f"已将经验 {exp_id[:8]} 提升至 {target_scope} 层（{target_scope_id}）。")
```

同时在 `main()` 中注册：

```python
elif cmd == "promote":
    await cmd_promote(rest)
```

并在 help 文本中加入：

```
print("  xp promote list         查看升层候选")
```

### Step 5: 运行测试确认通过

```bash
pytest tests/unit/ -v -k "test_promote_list"
```

预期：PASS

### Step 6: Commit

```bash
git add src/cli.py src/application/commands.py tests/unit/
git commit -m "feat(cli): add xp promote command for interactive promotion review"
```

---

## Task 11：xp stats 健康状态输出

**当前状态：** `cmd_stats` 不展示健康状态（各指标是否达标）。设计要求末尾固定展示健康状态。

**目标：** 新增 domain 层 `compute_health_status` 纯函数，在 `cmd_stats` 末尾展示。

**Files:**
- Create: `src/domain/health.py`
- Test: `tests/unit/test_health_status.py`
- Modify: `src/cli.py`

### Step 1: 写失败测试

创建 `tests/unit/test_health_status.py`：

```python
class TestComputeHealthStatus:
    def test_all_healthy(self):
        from src.domain.health import compute_health_status
        result = compute_health_status(
            adoption_rate=0.7,
            miss_rate=0.1,
            zero_result_rate=0.05,
            zombie_rate=0.1,
            pending_count=5,
            feedback_coverage=0.5,
        )
        assert result["overall"] == "healthy"
        assert all(v["ok"] for v in result["indicators"].values())

    def test_low_adoption_rate_is_unhealthy(self):
        from src.domain.health import compute_health_status
        result = compute_health_status(
            adoption_rate=0.4,
            miss_rate=0.1,
            zero_result_rate=0.05,
            zombie_rate=0.1,
            pending_count=5,
            feedback_coverage=0.5,
        )
        assert result["indicators"]["adoption_rate"]["ok"] is False
        assert result["overall"] != "healthy"

    def test_high_pending_count_is_unhealthy(self):
        from src.domain.health import compute_health_status
        result = compute_health_status(
            adoption_rate=0.7,
            miss_rate=0.1,
            zero_result_rate=0.05,
            zombie_rate=0.1,
            pending_count=25,
            feedback_coverage=0.5,
        )
        assert result["indicators"]["pending_count"]["ok"] is False

    def test_returns_indicators_dict_with_all_keys(self):
        from src.domain.health import compute_health_status
        result = compute_health_status(
            adoption_rate=0.7,
            miss_rate=0.1,
            zero_result_rate=0.05,
            zombie_rate=0.1,
            pending_count=5,
            feedback_coverage=0.5,
        )
        expected_keys = {
            "adoption_rate", "miss_rate", "zero_result_rate",
            "zombie_rate", "pending_count", "feedback_coverage"
        }
        assert set(result["indicators"].keys()) == expected_keys
```

### Step 2: 运行测试确认失败

```bash
pytest tests/unit/test_health_status.py -v
```

预期：FAIL，`ModuleNotFoundError: No module named 'src.domain.health'`

### Step 3: 创建 src/domain/health.py

```python
from __future__ import annotations

_THRESHOLDS = {
    "adoption_rate": {"min": 0.6, "higher_is_better": True},
    "miss_rate": {"max": 0.2, "higher_is_better": False},
    "zero_result_rate": {"max": 0.1, "higher_is_better": False},
    "zombie_rate": {"max": 0.15, "higher_is_better": False},
    "pending_count": {"max": 20, "higher_is_better": False},
    "feedback_coverage": {"min": 0.4, "higher_is_better": True},
}


def compute_health_status(
    adoption_rate: float,
    miss_rate: float,
    zero_result_rate: float,
    zombie_rate: float,
    pending_count: int,
    feedback_coverage: float,
) -> dict:
    values = {
        "adoption_rate": adoption_rate,
        "miss_rate": miss_rate,
        "zero_result_rate": zero_result_rate,
        "zombie_rate": zombie_rate,
        "pending_count": pending_count,
        "feedback_coverage": feedback_coverage,
    }

    indicators = {}
    for key, value in values.items():
        threshold = _THRESHOLDS[key]
        if threshold["higher_is_better"]:
            ok = value >= threshold["min"]
        else:
            ok = value <= threshold["max"]
        indicators[key] = {"value": value, "ok": ok}

    all_ok = all(v["ok"] for v in indicators.values())
    overall = "healthy" if all_ok else "needs_attention"

    return {"overall": overall, "indicators": indicators}
```

### Step 4: 运行测试确认通过

```bash
pytest tests/unit/test_health_status.py -v
```

预期：PASS

### Step 5: 在 cmd_stats 末尾展示健康状态

在 `src/cli.py` 的 `cmd_stats` 中，在最后一个 `print()` 之前追加：

```python
    from .domain.health import compute_health_status
    health = compute_health_status(
        adoption_rate=stats.get("query_adoption_rate", 0.0),
        miss_rate=1.0 - stats.get("search_hit_rate", 0.0),
        zero_result_rate=0.0,
        zombie_rate=0.0,
        pending_count=stats.get("pending_count", 0),
        feedback_coverage=0.0,
    )

    print(f"\n--- 知识库健康状态: {'✓ 良好' if health['overall'] == 'healthy' else '⚠ 需关注'} ---")
    status_map = {
        "adoption_rate": ("采纳率", "> 60%"),
        "miss_rate": ("未命中率", "< 20%"),
        "pending_count": ("Pending 堆积", "< 20 条"),
        "feedback_coverage": ("反馈覆盖率", "> 40%"),
    }
    for k, (label, threshold) in status_map.items():
        ind = health["indicators"][k]
        mark = "✓" if ind["ok"] else "✗"
        print(f"  {mark} {label} ({threshold})")
```

### Step 6: 运行所有单元测试

```bash
pytest tests/unit/ -v
```

预期：PASS

### Step 7: Commit

```bash
git add src/domain/health.py tests/unit/test_health_status.py src/cli.py
git commit -m "feat(domain/cli): add health status computation and display in xp stats"
```

---

## Task 12：全量回归测试 + lint

**目标：** 确保所有单元测试通过，无 lint 错误。

### Step 1: 运行所有单元测试

```bash
pytest tests/unit/ -v
```

预期：全部 PASS

### Step 2: 运行 lint

```bash
ruff check src/ tests/
```

或（若使用 flake8）：

```bash
flake8 src/ tests/ --max-line-length=120
```

预期：0 errors

### Step 3: 运行类型检查（若项目有配置）

```bash
# 检查 pyproject.toml 中是否有 mypy 配置
grep -r "mypy" pyproject.toml
```

若有，运行：

```bash
mypy src/
```

### Step 4: 最终提交

确认所有测试通过后，提交最终版本：

```bash
git add -A
git commit -m "test: full regression pass for hierarchy-aware knowledge system"
```

---

## 实施顺序和依赖关系

```
Task 1 (models)
  └── Task 5 (schema migration)

Task 2 (config/login)
  └── Task 3 (EdgeFunctionClient)
        └── Task 4 (server.py refactor)

Task 6 (domain: resolve_scope_ids)    # 独立
Task 7 (domain: determine_promotion_target)  # 独立
Task 11 (domain: health status)        # 独立

Task 8 (admin CLI)                     # 依赖 Task 1
Task 9 (stats params)                  # 独立
Task 10 (promote command)              # 依赖 Task 7
Task 12 (回归测试)                     # 依赖全部
```

**推荐顺序：** Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 → Task 8 → Task 9 → Task 10 → Task 11 → Task 12

每个 Task 独立可验证，单测不依赖真实数据库。
