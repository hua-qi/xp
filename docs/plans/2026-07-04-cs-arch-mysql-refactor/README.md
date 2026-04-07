# CS 架构 + MySQL 重构实现计划

**Goal:** 将 XP 从"本地 MCP stdio + PostgreSQL"迁移为"远端 MCP Streamable HTTP + MySQL"，实现本地零安装、集中管控。

**Architecture:** Agent 通过 HTTPS 直连公司服务器上的 FastAPI MCP Server；MySQL 存储元数据与向量（BLOB）；A/B Test 决定检索策略（A 组：全文检索 + LLM rerank；B 组：BGE-m3 + numpy 余弦相似度）；所有 prompt 存 MySQL 支持热更新。

**Tech Stack:** Python 3.11+、FastAPI、aiomysql、mcp[cli]、sentence-transformers（BGE-m3）、numpy、httpx、pytest、uv

---

## 任务路线图

```
Phase 0: 开发环境准备
  Task 00 → 搭建本地 MySQL + 配置环境变量

Phase 1: 基础层
  Task 01 → 依赖更新（pyproject.toml）
  Task 02 → 配置模块（src/config.py）
  Task 03 → LLM 统一调用层（src/infrastructure/llm.py）
  Task 04 → Embedding 模型切换（src/embeddings.py）

Phase 2: 数据模型
  Task 05 → 领域模型扩展（src/models.py）
  Task 06 → MySQL 建表 SQL（src/infrastructure/backends/mysql_schema.sql）
  Task 07 → MySQL 后端实现（src/infrastructure/backends/mysql.py）

Phase 3: Application 层
  Task 08 → Command 定义更新（src/application/commands.py）
  Task 09 → SaveHandler 重写（src/application/handlers/save_handler.py）
  Task 10 → SearchV2Handler 重写（src/application/handlers/search_v2_handler.py）
  Task 11 → FeedbackV2Handler 重写（src/application/handlers/feedback_v2_handler.py）

Phase 4: 基础设施扩展
  Task 12 → 冲突检测（src/domain/conflict.py）
  Task 13 → 定时任务（src/scheduler.py）
  Task 14 → Prompt 热更新加载器（src/infrastructure/prompt_loader.py）

Phase 5: 传输层
  Task 15 → MCP HTTP Server 重写（src/server.py）
  Task 16 → 容器组装更新（src/container.py）

Phase 6: 测试辅助
  Task 17 → 更新 InMemoryUnitOfWork（tests/helpers/fake_uow.py）
  Task 18 → 端到端联调验证
```

## 文件索引

| 文件 | 内容 |
|------|------|
| [phase0-env.md](./phase0-env.md) | 开发环境搭建 |
| [phase1-foundation.md](./phase1-foundation.md) | 依赖/配置/LLM/Embedding |
| [phase2-data-models.md](./phase2-data-models.md) | 领域模型/MySQL Schema/后端实现 |
| [phase3-application.md](./phase3-application.md) | Command/SaveHandler/SearchV2/FeedbackV2 |
| [phase4-infra.md](./phase4-infra.md) | 冲突检测/定时任务/Prompt 热更新 |
| [phase5-transport.md](./phase5-transport.md) | MCP HTTP Server/容器组装 |
| [phase6-testing.md](./phase6-testing.md) | InMemoryUoW 更新/端到端联调 |
