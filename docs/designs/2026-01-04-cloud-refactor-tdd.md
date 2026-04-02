# XP 云端化重构设计方案

**Date:** 2026-01-04
**Status:** Design

---

## 背景与问题

当前 XP 是单机架构：每个工程师本地有一份 `~/.xp/knowledge.json`，经验互相隔离，无法团队共享。目标是改造为**团队共享的中心化服务**。

关键洞察：**MCP 云端化后本地 cache 毫无意义**。原因是：断网 → 远端 LLM 也访问不到 → AI 根本跑不起来 → cache 无用。因此本地零状态，一切在云端。

---

## 目标架构

### 整体拓扑

```
工程师本地（零进程、零数据文件）
  Cursor / Claude Desktop
       │ MCP over SSE (HTTPS)
       │ Authorization: Bearer <team-token>
       ▼
  xp-server（团队共用，内网或公网部署）
       │
  ┌────┴──────────────────────────────────┐
  │  接口层 (FastAPI)                      │
  │  /mcp/sse        ← MCP over SSE 入口  │
  │  /api/*          ← REST（CLI 直调）   │
  ├───────────────────────────────────────┤
  │  领域层                                │
  │  ExtractionService  SearchService     │
  │  FeedbackService    QualityScorer     │
  │  MetadataInferrer   ABTestService     │
  ├───────────────────────────────────────┤
  │  基础设施层                            │
  │  EmbeddingService (BGE 模型在服务端)  │
  │  ExperienceRepo   VectorRepo          │
  │  MetricsRepo                          │
  ├───────────────────────────────────────┤
  │  PostgreSQL + pgvector                │
  └───────────────────────────────────────┘

CLI (xp 命令) → HTTP client → /api/*
本地不再有任何 Python 进程或数据文件
```

### IDE 配置变化

```json
// 现在（本地进程）
{ "command": "python", "args": ["src/server.py"] }

// 改造后（远程 SSE）
{ "url": "https://xp.your-team.com/mcp/sse",
  "headers": { "Authorization": "Bearer <team-token>" } }
```

---

## 代码结构重组

### knowledge.py 拆分（核心改造）

现有 1176 行的"上帝类"拆分为：

```
src/
├── domain/
│   ├── extraction.py      # ExtractionService
│   │   职责：字段校验、重复检测、元数据推断、质量评分、写入
│   │   依赖：QualityScorer, MetadataInferrer（注入）
│   │
│   ├── search.py          # SearchService
│   │   职责：向量化查询、余弦相似度、过滤排序、A/B 分组
│   │   依赖：EmbeddingService, VectorRepo（注入）
│   │
│   ├── feedback.py        # FeedbackService
│   │   职责：反馈记录、信心度更新、自动归档、adoption 推断
│   │
│   ├── quality.py         # QualityScorer（纯函数，无依赖）
│   │   职责：质量评分计算
│   │
│   ├── metadata.py        # MetadataInferrer（纯函数，无依赖）
│   │   职责：tech_stack / scene / type / level 推断
│   │
│   └── abtest.py          # ABTestService（纯函数）
│       职责：hash(session_id) % 10 分组
│
├── infra/
│   ├── embedding.py       # EmbeddingService（BGE or OpenAI）
│   └── repos/
│       ├── experience_repo.py
│       ├── vector_repo.py
│       └── metrics_repo.py
│
└── interfaces/
    ├── mcp_server.py      # FastAPI + MCP SSE handler
    ├── rest_api.py        # FastAPI REST routes
    └── cli.py             # HTTP client CLI
```

**拆分原则**：
- `quality.py` 和 `metadata.py` 是**纯函数**，无 IO，测试最容易
- Service 类依赖注入 Repo，可以 mock
- 接口层不包含任何业务逻辑

---

## REST API 设计

```
POST   /api/experiences              # 提取经验
GET    /api/experiences/search       # 检索经验（?q=&top_k=&tags=&session_id=）
GET    /api/experiences              # 列表（?status=pending，供 CLI review）
PATCH  /api/experiences/:id          # review 操作（activate/archive/edit）
POST   /api/sessions                 # 记录会话
POST   /api/feedback                 # 反馈
POST   /api/infer-adoption           # 自动推断采纳情况
GET    /api/stats                    # 统计（?since=7d）
```

**认证**：`Authorization: Bearer <team-token>`，整个团队共用一个 token，写在 IDE MCP 配置里。

---

## PostgreSQL 表结构

```sql
experiences (
  id UUID PRIMARY KEY,
  type VARCHAR, level VARCHAR,
  title TEXT, problem TEXT,
  solution TEXT, key_decisions TEXT,
  confidence FLOAT, status VARCHAR,
  project VARCHAR, metadata JSONB,
  tags TEXT[], related_files TEXT[],
  file_hashes JSONB,
  embedding vector(384),   -- pgvector，BGE-small-zh 维度
  created_at TIMESTAMPTZ,
  last_hit_at TIMESTAMPTZ
)

sessions (
  session_id VARCHAR UNIQUE,
  task_description TEXT,
  experience_ids_injected TEXT[],
  iteration_count INT,
  had_error_correction BOOL,
  user_accepted BOOL,
  ab_test_group VARCHAR,
  created_at TIMESTAMPTZ
)

feedback (
  id SERIAL PRIMARY KEY,
  experience_id UUID REFERENCES experiences,
  adopted BOOL, reason TEXT,
  created_at TIMESTAMPTZ
)
```

---

## TDD 重构策略（四周计划）

### Week 1：给现有代码穿安全网（特征测试）

**不改任何逻辑**，只写测试覆盖 `knowledge.py` 的所有现有行为。

```
tests/characterization/
├── test_extraction.py     # extract_experience 所有路径
├── test_search.py         # search 所有路径
├── test_feedback.py       # record_feedback + confidence 更新
├── test_quality_score.py  # 质量评分每个分项
├── test_metadata_infer.py # tech_stack/scene/type/level 推断
└── test_abtest.py         # A/B 分组逻辑
```

Week 1 结束标准：**所有测试绿，knowledge.py 一行未动**。

### Week 2：拆分 knowledge.py

每次只移动一个模块，移完立刻跑全量测试：

```
Step 1: 提取 quality.py        → 写接口测试(红) → 移代码(绿) → 全量测试 ✓
Step 2: 提取 metadata.py       → 同上
Step 3: 提取 SearchService     → 同上
Step 4: 提取 ExtractionService → 同上
Step 5: 提取 FeedbackService   → 同上
```

每个 Step 一次 commit。Week 2 结束：knowledge.py 消失，测试全绿。

### Week 3：建 xp-server，测试先行

```
tests/
├── unit/          # 纯单元，无 IO，mock repo
├── integration/   # 真实 PostgreSQL（Docker 起）
│   ├── test_experience_repo.py
│   ├── test_vector_repo.py
│   └── test_metrics_repo.py
└── e2e/           # 真实 FastAPI + 真实 DB
    ├── test_search_api.py
    ├── test_extract_api.py
    └── test_mcp_sse.py    # 模拟 MCP 客户端
```

### Week 4：数据迁移 + 删旧代码

```
Step 1: 写迁移测试（红）
        → knowledge.json → PostgreSQL 数据完整
        → 向量可检索
        → 统计数据一致
Step 2: 实现迁移脚本（绿）
Step 3: 删旧代码
        → storage.py（Repo 层已替代）
        → cloud_providers.py（方案已放弃）
        → backends/local.py
        → file_watcher.py（Phase 3 残留）
        → 全量测试仍然绿 ✓
```

---

## 改造成本评估

| 模块 | 工作量 | 风险 |
|------|--------|------|
| knowledge.py 拆分 | 3-5 天 | 高（互相调用深，先写测试再动） |
| storage.py 替换为 Repo | 2-3 天 | 中 |
| 新建 xp-server（FastAPI） | 5-7 天 | 低（全新代码） |
| server.py 改 MCP SSE | 1-2 天 | 低 |
| cli.py 改 HTTP client | 1-2 天 | 低 |
| 数据迁移脚本 | 2-3 天 | 中 |
| 测试补全 | 2-3 天 | — |
| **总计（1人）** | **3-4 周** | — |

**最高风险**：Week 1 特征测试是整个重构的地基，必须在动代码前写完。

---

## 废弃的方案

| 方案 | 放弃原因 |
|------|---------|
| 本地 cache | 断网则 LLM 也不可用，cache 无意义 |
| Git 后端同步 | 并发写入冲突无解 |
| Supabase/Weaviate | YAGNI，自建服务更可控 |
| 本地 HTTP Proxy | MCP over SSE 已被主流 IDE 支持，无需 Proxy |

---

## 待确认事项

- [ ] 部署环境：内网服务器 or 公网云服务？
- [ ] team-token 管理方式（静态 token 还是动态下发）
- [ ] BGE 模型在服务端运行的硬件要求（CPU 推理延迟是否可接受）
- [ ] 迁移期间双写策略（新旧并行多长时间）
