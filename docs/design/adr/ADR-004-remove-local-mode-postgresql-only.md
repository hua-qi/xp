# ADR-004: 去除本地模式，强制 PostgreSQL 单一路径

**状态**: 已接受  
**日期**: 2026-05-04  
**作者**: 团队

## 背景

ADR-003 完成了 async 调用链重构，并引入了 `UnitOfWork(backend=PostgresBackend(...))` 路径。但为保证过渡平稳，保留了双路径兼容机制：

- 有 `DATABASE_URL` → 走 PostgresUnitOfWork
- 无 `DATABASE_URL` → 回退到旧 SQLite/JSON Adapter（`storage.py`）

这种双路径带来了持续的维护负担：

1. `storage.py`、`infrastructure/stores/` 等遗留文件继续存在，造成死代码堆积
2. 7 个旧 handler 仍直接 `import` storage 对象，绕过 UoW 抽象边界
3. 测试需要同时覆盖两条路径，fixture 复杂度高
4. 新功能（analytics、会话统计）只在 PG 路径实现，两条路径行为不一致
5. 无法实现"UoW 是唯一数据访问入口"的架构约束

## 决策

**完全删除本地模式（SQLite/JSON 路径），仅保留 PostgreSQL 单一路径。**

具体变更：

1. 删除 `src/storage.py`
2. 删除 `src/infrastructure/stores/`（`experience_store.py`、`vector_store.py`、`metrics_store.py`）
3. `container.py`：`DATABASE_URL` 缺失时抛 `RuntimeError`，不再回退
4. `infrastructure/unit_of_work.py`：只保留 `PostgresUnitOfWork`，删除旧 Adapter 路径
5. 所有 handler 完全通过 `UoW` 访问数据，删除直接 `import storage` 的代码
6. `AbstractUnitOfWork` 新增 `analytics: AbstractAnalyticsStore` 抽象属性
7. `_PgAnalyticsStore` 统一实现 stats/session/feedback/search/adoption 分析能力

## 后果

### 正面影响

- **架构边界清晰**：UoW 是唯一数据访问入口，handler 不再感知存储实现
- **代码量减少**：删除约 400 行遗留 Adapter 代码，3 个文件
- **测试简化**：单元测试统一使用 `InMemoryUnitOfWork`，无需区分路径
- **新能力完整**：analytics store 在所有环境下行为一致（内存 or PG）

### 负面影响

- **Breaking Change**：`DATABASE_URL` 从可选变为必须，所有部署必须配置
- **无本地离线模式**：无法在无 DB 环境下运行（开发者需本地 PG 或远程 PG URL）

### 缓解措施

- 提供 `.env.example`，说明如何获取免费 PG（Supabase/Neon/本地 Docker）
- `InMemoryUnitOfWork` 保留在 `tests/helpers/`，单元测试不依赖真实 DB
- `RuntimeError` 消息明确指引用户设置 `DATABASE_URL`

## 替代方案

### 方案 A：继续保留双路径（不选）

维护成本持续增加，两条路径行为分歧，新功能需要重复实现。

### 方案 B：用 SQLite 的 asyncpg 兼容层（不选）

没有成熟方案，且引入额外依赖，不值得。

## 相关文档

- [ADR-003: Async PostgreSQL Migration](ADR-003-async-postgresql-migration.md)
- [功能文档: PostgreSQL 全量迁移](../../features/postgres-async-migration.md)
- [CHANGELOG](../../../CHANGELOG.md)
