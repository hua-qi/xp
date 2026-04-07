# PyPI 分发与 stdio MCP 接入实施方案

**Goal:** 将 xp 打包为 PyPI 包，让同事通过 `pip install xp-agent` 安装后，`xp login` 一次即可接入团队共享 Supabase 知识库，并通过 `xp-server` 命令启动 stdio MCP。

**Architecture:** 新增 `src/auth.py` 负责读写 `~/.xp/config.json`（token、user_id、team_id、database_url）；`src/server.py` 的 `main()` 改为优先从 config.json 读取 database_url，而非强依赖 `DATABASE_URL` 环境变量；`src/cli.py` 新增 `xp login` 和 `xp admin create-token` 两个子命令。Supabase Edge Function `verify-token` 负责 token 验证并返回连接信息，客户端无需直接持有数据库密码。

**Tech Stack:** Python 3.11+、asyncpg、httpx（HTTP 请求 Edge Function）、pytest + pytest-asyncio（测试）、hatchling（打包）、Supabase Edge Function（Deno/TypeScript）

---

## 前置阅读

在开始之前，先读这些文件了解现有结构：
- `src/config.py` — 当前只有 `XP_HOME` 路径常量
- `src/server.py` `main()` — 当前从 `PROJECT_MANAGER` 读取 project，依赖 `DATABASE_URL` 环境变量
- `src/container.py` `build_command_bus()` — 第 67-70 行，`DATABASE_URL` 读取逻辑
- `src/cli.py` `main()` — 现有子命令分发结构
- `pyproject.toml` — 现有入口点和依赖

---

## Task 1: 扩展 `src/config.py`，实现 config.json 读写

**Files:**
- Modify: `src/config.py`
- Test: `tests/unit/test_config.py`（新建）

### Step 1: 写失败测试

```python
# tests/unit/test_config.py
import json
import pytest
from pathlib import Path


def test_save_and_load_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_HOME", str(tmp_path))
    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)

    cfg_module.save_config({
        "token": "xp_test123",
        "user_id": "alice",
        "team_id": "team-01",
        "database_url": "postgresql://u:p@host/db",
    })

    result = cfg_module.load_config()
    assert result["token"] == "xp_test123"
    assert result["user_id"] == "alice"
    assert result["database_url"] == "postgresql://u:p@host/db"


def test_load_config_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_HOME", str(tmp_path))
    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)

    result = cfg_module.load_config()
    assert result is None


def test_config_file_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_HOME", str(tmp_path))
    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)

    cfg_module.save_config({"token": "x"})
    assert (tmp_path / "config.json").exists()
```

### Step 2: 运行确认失败

```
pytest tests/unit/test_config.py -v
```

预期：`FAILED` - `AttributeError: module 'src.config' has no attribute 'save_config'`

### Step 3: 实现最小代码

将 `src/config.py` 改为：

```python
import json
import os
from pathlib import Path

XP_HOME = Path(os.environ.get("XP_HOME", Path.home() / ".xp"))


def _config_path() -> Path:
    return XP_HOME / "config.json"


def save_config(data: dict) -> None:
    XP_HOME.mkdir(parents=True, exist_ok=True)
    _config_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_config() -> dict | None:
    path = _config_path()
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
```

### Step 4: 运行确认通过

```
pytest tests/unit/test_config.py -v
```

预期：3 个测试全部 `PASSED`

### Step 5: 提交

```
git add src/config.py tests/unit/test_config.py
git commit -m "feat: add save_config/load_config to src/config.py"
```

---

## Task 2: 实现 `src/auth.py`，封装 token 验证逻辑（调用 Edge Function）

**Files:**
- Create: `src/auth.py`
- Test: `tests/unit/test_auth.py`（新建）

> **为什么单独一个文件？** `cli.py` 和 `server.py` 都需要调用，解耦依赖。Edge Function URL 是可配置的（`XP_AUTH_URL` 环境变量），便于测试时 mock。

### Step 1: 写失败测试

```python
# tests/unit/test_auth.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_verify_token_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "database_url": "postgresql://u:p@host/db",
        "user_id": "alice",
        "team_id": "team-01",
    }

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        from src.auth import verify_token
        result = await verify_token("xp_abc123", auth_url="https://example.supabase.co/functions/v1/verify-token")

    assert result["user_id"] == "alice"
    assert result["database_url"].startswith("postgresql://")


@pytest.mark.asyncio
async def test_verify_token_invalid_returns_none():
    mock_response = MagicMock()
    mock_response.status_code = 401

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        from src.auth import verify_token
        result = await verify_token("bad_token", auth_url="https://example.supabase.co/functions/v1/verify-token")

    assert result is None
```

### Step 2: 运行确认失败

```
pytest tests/unit/test_auth.py -v
```

预期：`FAILED` - `ModuleNotFoundError: No module named 'src.auth'`

### Step 3: 检查 httpx 是否已安装

```
python -c "import httpx; print(httpx.__version__)"
```

如果报错，在 `pyproject.toml` 的 `dependencies` 中加入 `"httpx>=0.27.0"`，然后运行 `uv sync`。

### Step 4: 实现最小代码

新建 `src/auth.py`：

```python
import os
from typing import Any

import httpx

DEFAULT_AUTH_URL = os.environ.get(
    "XP_AUTH_URL",
    "https://your-project.supabase.co/functions/v1/verify-token",
)


async def verify_token(token: str, auth_url: str = DEFAULT_AUTH_URL) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(auth_url, json={"token": token})
    if response.status_code == 200:
        return response.json()
    return None
```

### Step 5: 运行确认通过

```
pytest tests/unit/test_auth.py -v
```

预期：2 个测试全部 `PASSED`

### Step 6: 提交

```
git add src/auth.py tests/unit/test_auth.py
git commit -m "feat: add auth.py with verify_token"
```

---

## Task 3: 新增 `xp login` 子命令

**Files:**
- Modify: `src/cli.py`
- Test: `tests/unit/test_cli_login.py`（新建）

### Step 1: 写失败测试

```python
# tests/unit/test_cli_login.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_login_success_writes_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_HOME", str(tmp_path))

    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)

    verify_result = {
        "database_url": "postgresql://u:p@host/db",
        "user_id": "alice",
        "team_id": "team-01",
    }

    with patch("src.cli.verify_token", new=AsyncMock(return_value=verify_result)), \
         patch("builtins.input", return_value="xp_abc123"):
        from src.cli import cmd_login
        await cmd_login([])

    config = cfg_module.load_config()
    assert config is not None
    assert config["token"] == "xp_abc123"
    assert config["user_id"] == "alice"


@pytest.mark.asyncio
async def test_login_invalid_token_prints_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XP_HOME", str(tmp_path))

    with patch("src.cli.verify_token", new=AsyncMock(return_value=None)), \
         patch("builtins.input", return_value="bad_token"):
        from src.cli import cmd_login
        await cmd_login([])

    captured = capsys.readouterr()
    assert "无效" in captured.out or "失败" in captured.out
```

### Step 2: 运行确认失败

```
pytest tests/unit/test_cli_login.py -v
```

预期：`FAILED` - `cannot import name 'cmd_login' from 'src.cli'`

### Step 3: 在 `src/cli.py` 顶部 import 区域加入

在 `from dotenv import load_dotenv` 之后加一行：

```python
from .auth import verify_token
```

然后在 `cmd_sync` 函数之后（`async def cmd_migrate` 之前）新增函数：

```python
async def cmd_login(args):
    print("\n" + "=" * 60)
    print("  xp login")
    print("=" * 60)
    token = input("请输入 token（管理员提供）: ").strip()
    if not token:
        print("错误: token 不能为空")
        return

    print("验证中...")
    result = await verify_token(token)
    if result is None:
        print("验证失败：token 无效或已撤销，请联系管理员。")
        return

    from .config import save_config
    save_config({
        "token": token,
        "user_id": result["user_id"],
        "team_id": result["team_id"],
        "database_url": result["database_url"],
    })
    print(f"登录成功！")
    print(f"  用户: {result['user_id']}")
    print(f"  团队: {result['team_id']}")
    print(f"\n现在可以在 Claude Desktop 中配置 xp-server 了。")
```

在 `main()` 的 `elif cmd == "sync":` 分支之后加：

```python
    elif cmd == "login":
        await cmd_login(rest)
```

同时在 `main()` 帮助文本中添加一行：

```python
        print("  xp login               登录并写入本地配置")
```

### Step 4: 运行确认通过

```
pytest tests/unit/test_cli_login.py -v
```

预期：2 个测试全部 `PASSED`

### Step 5: 提交

```
git add src/cli.py tests/unit/test_cli_login.py
git commit -m "feat: add xp login command"
```

---

## Task 4: 新增 `xp admin create-token` 子命令

**Files:**
- Modify: `src/cli.py`
- Test: `tests/unit/test_cli_admin.py`（新建）

> **说明：** `create-token` 直接写 Supabase `user_tokens` 表。管理员本地需配置 `DATABASE_URL`（指向 Supabase）。普通同事不需要此命令。

### Step 1: 写失败测试

```python
# tests/unit/test_cli_admin.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import secrets


@pytest.mark.asyncio
async def test_admin_create_token_writes_to_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")

    fake_token = "xp_" + secrets.token_urlsafe(16)
    mock_backend = MagicMock()
    mock_backend.execute = AsyncMock()
    mock_backend.acquire = AsyncMock()

    with patch("src.cli._admin_insert_token", new=AsyncMock(return_value=fake_token)) as mock_insert, \
         patch("builtins.input", side_effect=["alice", "team-01"]):
        from src.cli import cmd_admin
        await cmd_admin(["create-token"])

    mock_insert.assert_called_once()
    call_kwargs = mock_insert.call_args
    assert call_kwargs.kwargs["user_id"] == "alice" or call_kwargs.args[0] == "alice"


@pytest.mark.asyncio
async def test_admin_create_token_prints_token(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")

    with patch("src.cli._admin_insert_token", new=AsyncMock(return_value="xp_generated_token")), \
         patch("builtins.input", side_effect=["bob", "team-02"]):
        from src.cli import cmd_admin
        await cmd_admin(["create-token"])

    captured = capsys.readouterr()
    assert "xp_generated_token" in captured.out
```

### Step 2: 运行确认失败

```
pytest tests/unit/test_cli_admin.py -v
```

预期：`FAILED` - `cannot import name 'cmd_admin' from 'src.cli'`

### Step 3: 在 `src/cli.py` 中新增（在 `cmd_login` 之后）

```python
async def _admin_insert_token(user_id: str, team_id: str, database_url: str) -> str:
    import secrets
    import asyncpg
    token = "xp_" + secrets.token_urlsafe(16)
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(
            """
            INSERT INTO user_tokens (token, user_id, team_id, database_url)
            VALUES ($1, $2, $3, $4)
            """,
            token, user_id, team_id, database_url,
        )
    finally:
        await conn.close()
    return token


async def cmd_admin(args):
    if not args or args[0] != "create-token":
        print("用法: xp admin create-token")
        return

    import os
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("错误: 需要设置 DATABASE_URL 环境变量（管理员专用）")
        return

    user_id = input("用户名 (user_id): ").strip()
    if not user_id:
        print("错误: user_id 不能为空")
        return

    team_id = input("团队 (team_id): ").strip()
    if not team_id:
        print("错误: team_id 不能为空")
        return

    token = await _admin_insert_token(user_id=user_id, team_id=team_id, database_url=database_url)
    print(f"\nToken 已生成，请发给用户：\n\n  {token}\n")
    print(f"用户执行 `xp login` 并输入上面的 token 即可接入。")
```

在 `main()` 的命令分发中加入：

```python
    elif cmd == "admin":
        await cmd_admin(rest)
```

并在帮助文本中加：

```python
        print("  xp admin create-token  [管理员] 为用户生成 token")
```

### Step 4: 运行确认通过

```
pytest tests/unit/test_cli_admin.py -v
```

预期：2 个测试全部 `PASSED`

### Step 5: 提交

```
git add src/cli.py tests/unit/test_cli_admin.py
git commit -m "feat: add xp admin create-token command"
```

---

## Task 5: 修改 `src/server.py` `main()`，从 config.json 读取 database_url

**Files:**
- Modify: `src/server.py`
- Test: `tests/unit/test_server_main.py`（新建）

### Step 1: 写失败测试

```python
# tests/unit/test_server_main.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_server_main_uses_config_json(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_HOME", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    import importlib
    import src.config as cfg_module
    importlib.reload(cfg_module)
    cfg_module.save_config({
        "token": "xp_abc",
        "user_id": "alice",
        "team_id": "team-01",
        "database_url": "postgresql://u:p@host/db",
    })

    captured_dsn = {}

    async def fake_build_bus(**kwargs):
        captured_dsn["dsn"] = kwargs.get("dsn") or "called"
        return MagicMock()

    with patch("src.server.build_command_bus", new=AsyncMock(side_effect=fake_build_bus)), \
         patch("src.server.stdio_server") as mock_stdio:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_stdio.return_value = mock_ctx

        with patch("src.server.app") as mock_app:
            mock_app.run = AsyncMock()
            mock_app.create_initialization_options = MagicMock(return_value={})
            import src.server as server_module
            importlib.reload(server_module)
            await server_module.main()

    assert fake_build_bus.called


@pytest.mark.asyncio
async def test_server_main_exits_when_no_config_and_no_env(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XP_HOME", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    import importlib
    import src.server as server_module
    importlib.reload(server_module)

    with pytest.raises(SystemExit):
        await server_module.main()

    captured = capsys.readouterr()
    assert "xp login" in captured.out
```

### Step 2: 运行确认失败

```
pytest tests/unit/test_server_main.py::test_server_main_exits_when_no_config_and_no_env -v
```

预期：`FAILED` - server 当前在无 `DATABASE_URL` 时抛出 `RuntimeError`，而非有友好提示的 `SystemExit`

### Step 3: 修改 `src/server.py` 的 `main()` 函数

将现有 `main()` 替换为：

```python
async def main():
    global _bus
    import os
    import sys
    from .config import load_config
    from .project_config import ProjectManager

    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        config = load_config()
        if config is None:
            print("请先运行 xp login 完成登录配置。", file=sys.stderr)
            sys.exit(1)
        database_url = config["database_url"]

    project = ProjectManager().get_current()
    _bus = await build_command_bus(project=project, dsn=database_url)

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())
```

### Step 4: 修改 `src/container.py` 的 `build_command_bus()`，接受可选 `dsn` 参数

当前签名是 `async def build_command_bus(project: str = "default")`，改为：

```python
async def build_command_bus(project: str = "default", dsn: str | None = None) -> CommandBus:
    import os
    from .infrastructure.backends.postgres import PostgresBackend

    resolved_dsn = dsn or os.environ.get("DATABASE_URL")
    if not resolved_dsn:
        raise RuntimeError("DATABASE_URL environment variable is required")

    backend = PostgresBackend(dsn=resolved_dsn)
    # ... 其余代码不变
```

### Step 5: 运行确认通过

```
pytest tests/unit/test_server_main.py -v
```

预期：测试通过（至少 `test_server_main_exits_when_no_config_and_no_env` PASSED）

### Step 6: 运行完整单元测试确保没有回归

```
pytest tests/unit/ -v --tb=short
```

预期：全部通过

### Step 7: 提交

```
git add src/server.py src/container.py tests/unit/test_server_main.py
git commit -m "feat: server reads database_url from config.json, falls back to env"
```

---

## Task 6: 更新 `pyproject.toml` 包元信息

**Files:**
- Modify: `pyproject.toml`
- Test: `tests/unit/test_pyproject.py`（新建）

### Step 1: 写失败测试

```python
# tests/unit/test_pyproject.py
import tomllib
from pathlib import Path


def test_package_name_is_xp_agent():
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    assert data["project"]["name"] == "xp-agent"


def test_xp_server_entrypoint_exists():
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    scripts = data["project"]["scripts"]
    assert "xp-server" in scripts
    assert scripts["xp-server"] == "src.server:main"


def test_xp_entrypoint_exists():
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    scripts = data["project"]["scripts"]
    assert "xp" in scripts
    assert scripts["xp"] == "src.cli:main"


def test_httpx_in_dependencies():
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    deps = data["project"]["dependencies"]
    assert any("httpx" in d for d in deps)
```

### Step 2: 运行确认失败

```
pytest tests/unit/test_pyproject.py -v
```

预期：`test_package_name_is_xp_agent` FAILED（当前 name 是 `xp`）

### Step 3: 修改 `pyproject.toml`

```toml
[project]
name = "xp-agent"
version = "0.3.0"
description = "团队 Agent 最佳实践沉淀工具，支持 stdio MCP 接入 Claude Desktop"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
keywords = ["mcp", "agent", "knowledge-base", "llm"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Programming Language :: Python :: 3.11",
    "License :: OSI Approved :: MIT License",
]
dependencies = [
    "mcp[cli]>=1.0.0",
    "python-dotenv>=1.0.0",
    "sentence-transformers>=2.2.0",
    "numpy>=1.24.0",
    "asyncpg>=0.29.0",
    "fastapi>=0.110.0",
    "uvicorn>=0.29.0",
    "pgvector>=0.2.0",
    "httpx>=0.27.0",
    "pytest-asyncio>=1.3.0",
]

[project.scripts]
xp = "src.cli:main"
xp-server = "src.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

### Step 4: 运行确认通过

```
pytest tests/unit/test_pyproject.py -v
```

预期：4 个测试全部 `PASSED`

### Step 5: 验证包可构建

```
python -m build --wheel --no-isolation 2>&1 | tail -5
```

预期：`Successfully built xp_agent-0.3.0-py3-none-any.whl`

### Step 6: 提交

```
git add pyproject.toml tests/unit/test_pyproject.py
git commit -m "chore: rename package to xp-agent, add httpx dep, update metadata"
```

---

## Task 7: 部署 Supabase Edge Function `verify-token`

> **说明：** 这是纯 Supabase 侧的工作，不涉及 Python 代码，无法通过 Python 单元测试覆盖。用 `curl` 手动验证。

**Files:**
- Create: `supabase/functions/verify-token/index.ts`（如果使用 Supabase CLI 管理）

### Step 1: 在 Supabase 控制台执行建表 SQL

```sql
CREATE TABLE IF NOT EXISTS user_tokens (
    token        TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    team_id      TEXT NOT NULL,
    database_url TEXT NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT now(),
    revoked_at   TIMESTAMPTZ
);
```

### Step 2: 创建 Edge Function 代码

新建文件 `supabase/functions/verify-token/index.ts`：

```typescript
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  const { token } = await req.json();
  if (!token) {
    return new Response(JSON.stringify({ error: "token required" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );

  const { data, error } = await supabase
    .from("user_tokens")
    .select("database_url, user_id, team_id")
    .eq("token", token)
    .is("revoked_at", null)
    .single();

  if (error || !data) {
    return new Response(JSON.stringify({ error: "invalid token" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});
```

### Step 3: 部署

```
supabase functions deploy verify-token --no-verify-jwt
```

### Step 4: 手动冒烟测试

先插入一条测试 token：

```sql
INSERT INTO user_tokens (token, user_id, team_id, database_url)
VALUES ('xp_test_smoke', 'alice', 'team-01', 'postgresql://...');
```

然后验证：

```bash
curl -X POST https://YOUR_PROJECT.supabase.co/functions/v1/verify-token \
  -H "Content-Type: application/json" \
  -d '{"token": "xp_test_smoke"}'
```

预期响应：

```json
{"database_url": "postgresql://...", "user_id": "alice", "team_id": "team-01"}
```

### Step 5: 更新 `src/auth.py` 中的默认 URL

将 `DEFAULT_AUTH_URL` 中的 `your-project` 替换为真实项目 ID，或通过 `.env.example` 文档化：

```
XP_AUTH_URL=https://YOUR_PROJECT.supabase.co/functions/v1/verify-token
```

---

## Task 8: 端到端冒烟测试（本地安装验证）

### Step 1: 本地安装包

```
pip install -e .
```

### Step 2: 测试 xp login 流程

```
xp login
```

按提示输入 Task 7 中创建的 `xp_test_smoke` token，预期输出：

```
登录成功！
  用户: alice
  团队: team-01
```

验证配置已写入：

```
cat ~/.xp/config.json
```

预期看到 `database_url`、`user_id`、`team_id` 字段。

### Step 3: 测试 xp-server 能正常启动

```
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}}}' | xp-server
```

预期：返回 JSON 响应，而非 `请先运行 xp login` 错误。

### Step 4: 测试无 config 时 xp-server 给出友好提示

```
XP_HOME=/tmp/empty_xp_home xp-server
```

预期 stderr 输出：`请先运行 xp login 完成登录配置。`，进程以非 0 退出码退出。

---

## 完成检查清单

- [ ] `pytest tests/unit/test_config.py` — 全部通过
- [ ] `pytest tests/unit/test_auth.py` — 全部通过
- [ ] `pytest tests/unit/test_cli_login.py` — 全部通过
- [ ] `pytest tests/unit/test_cli_admin.py` — 全部通过
- [ ] `pytest tests/unit/test_server_main.py` — 全部通过
- [ ] `pytest tests/unit/test_pyproject.py` — 全部通过
- [ ] `pytest tests/unit/ -v` — 无回归
- [ ] `pip install -e . && xp login` — 端到端流程正常
- [ ] Supabase Edge Function 部署并手动验证通过
