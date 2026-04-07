# xp PyPI 分发与 stdio MCP 接入设计

**Date:** 2026-05-04

## Context

xp 当前是一个本地运行的 Agent 经验沉淀工具，MCP server 采用 stdio 协议，用户需要 clone 代码仓库、配置 `DATABASE_URL` 环境变量才能使用。这套流程对非开发者同事门槛过高。

目标：将 xp 打包为 PyPI 包分发，让同事通过 `pip install xp-agent` 安装后，只需一次 `xp login` 和一行 Claude Desktop 配置，即可接入团队共享知识库，同时保留完整的 CLI 功能（`xp stats`、`xp review` 等）。

## Discussion

### 接入方式选型

**HTTP MCP vs stdio MCP**

探索了三种方案：
- **方案 A（最终选择）**：PyPI 包 + stdio MCP，本地拉起进程，共连公共 Supabase
- **方案 B**：PyPI 包 + HTTP MCP，集中部署云端服务，用户只填 URL
- **方案 C**：HTTP + stdio 混合，复杂度最高，不推荐

选择方案 A 的原因：测试阶段改造量最小，stdio 协议不变，核心逻辑零改动，同事体验已足够好。HTTP MCP 可在规模扩大后再升级。

### 存储选型

公司内网仅有 MySQL 8.x，不支持向量类型（MySQL VECTOR 从 9.0 才引入）。xp 的核心能力（搜索、重复检测、采纳推断）依赖向量检索，MySQL 8.x 无法替代 pgvector。

**决策**：使用 Supabase（托管 PostgreSQL + pgvector）作为公共数据库。内部测试阶段数据不敏感，外部云存储可接受。现有 asyncpg 代码无需改动，直连 Supabase 即可。

### 认证设计

对比了三种登录方式：
- CLI 直接输入 token（最终选择）
- OAuth 浏览器跳转
- 管理员分发 token + CLI 填入

**决策**：管理员通过 `xp admin create-token` 生成 token 并发给同事，同事执行 `xp login` 输入 token，写入本地 `~/.xp/config.json`。

### 验证接口

token 验证需要一个端点将 token 转换为 `database_url` + `user_id` + `team_id`，避免直接暴露数据库连接串。

对比了两种方案：
- Supabase Edge Function（serverless，零额外部署）
- 自建 FastAPI `/auth/verify` 路由部署到 Fly.io

**决策**：Supabase Edge Function，零运维成本，与现有 Supabase 基础设施统一。

## Approach

### 用户旅程（3 步接入）

```bash
# 1. 安装
pip install xp-agent

# 2. 登录（管理员发给你的 token）
xp login
# 输入 token：xp_abc123 → 验证成功，写入 ~/.xp/config.json

# 3. 配置 Claude Desktop（一次性，永久生效）
# claude_desktop_config.json：
# { "mcpServers": { "xp": { "command": "xp-server" } } }
```

日常 CLI 使用：`xp stats` / `xp review` / `xp analyze`，无需任何额外配置。

### 管理员操作

```bash
xp admin create-token --user alice --team team-01
# → 生成 token，写入 Supabase user_tokens 表
# → 输出 token 字符串，发给同事
```

## Architecture

### 组件总览

```
同事电脑
├── xp-server（stdio MCP，由 Claude Desktop 拉起）
├── xp CLI（xp login / xp stats / xp review ...）
└── ~/.xp/config.json（token、user_id、team_id、database_url）
        │
        ▼ 启动时读取
xp-server → asyncpg → Supabase（PostgreSQL + pgvector）

xp login → POST Supabase Edge Function /verify-token
         → { database_url, user_id, team_id } → 写入 config.json
```

### 数据库：user_tokens 表

```sql
CREATE TABLE user_tokens (
    token        TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    team_id      TEXT NOT NULL,
    database_url TEXT NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT now(),
    revoked_at   TIMESTAMPTZ       -- NULL 表示有效
);
```

### Supabase Edge Function：verify-token

```
POST /functions/v1/verify-token
Body: { "token": "xp_abc123" }

逻辑：
  查 user_tokens WHERE token = ? AND revoked_at IS NULL
  → 返回 { database_url, user_id, team_id }
  → token 不存在或已撤销 → 401
```

### xp-server 启动逻辑

```
xp-server 启动
    ↓
读取 ~/.xp/config.json
    ├── 不存在 → 打印 "请先运行 xp login" → 退出
    ↓
用 database_url 初始化 PostgresBackend
    ↓
build_command_bus() → stdio MCP 正常运行
```

### pyproject.toml 入口点

```toml
[project.scripts]
xp = "xp.cli:main"
xp-server = "xp.server:main"
```

### 代码改动范围

| 文件 | 改动内容 |
|------|---------|
| `src/config.py`（新增） | 读写 `~/.xp/config.json` 的工具函数 |
| `src/server.py` | `main()` 改为从 config.json 读取 database_url，约 5 行 |
| `src/cli.py` | 新增 `xp login` 子命令、`xp admin create-token` 子命令 |
| `pyproject.toml` | 补充 `xp-server` 入口点 + 包元信息（name、version、classifiers） |
| Supabase | 新建 `user_tokens` 表 + 部署 `verify-token` Edge Function |

**现有 Handler、CommandBus、domain 逻辑、测试全部不动。**

### 后续升级路径

当团队规模扩大、不希望每人本地跑进程时，可升级为 HTTP MCP：
- 将 xp-server 部署为 FastAPI + StreamableHTTPSessionManager
- mcp 1.26.0 已原生支持此模式（`StreamableHTTPSessionManager` 直接挂载到 FastAPI lifespan）
- Claude Desktop 配置从 `command` 改为 `url`，用户无感迁移
