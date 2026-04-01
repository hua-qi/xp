# XP 项目整体架构文档

## 一、系统定位

XP 是一个 **AI Agent 经验沉淀与复用工具**，通过 MCP 协议集成到 IDE（Cursor/Claude），自动沉淀任务经验，检索复用。

**核心价值链**:
```
Agent 完成任务 → 自动提取经验 → 人工审核 → 智能检索注入 → 下次直接复用
```

---

## 二、整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        外部接入层                                │
│                                                                  │
│   ┌─────────────────┐           ┌─────────────────────────────┐ │
│   │   IDE Agent     │           │      工程师 CLI              │ │
│   │ (Cursor/Claude) │           │   (xp review/add/stats...)  │ │
│   └────────┬────────┘           └──────────────┬──────────────┘ │
└────────────┼───────────────────────────────────┼────────────────┘
             │ MCP Protocol                       │ argparse
             ▼                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                        接口层                                    │
│   ┌──────────────────────────┐   ┌────────────────────────────┐ │
│   │       server.py          │   │          cli.py             │ │
│   │  MCP Server (7 Tools)    │   │   14 个 CLI 命令            │ │
│   │                          │   │                             │ │
│   │  search_best_practices   │   │  review / add / edit        │ │
│   │  extract_experience      │   │  stats / analyze            │ │
│   │  record_session          │   │  project / sync / watch     │ │
│   │  record_feedback         │   │  import / archive / delete  │ │
│   │  finalize_task           │   │                             │ │
│   │  infer_adoption          │   │                             │ │
│   └──────────────┬───────────┘   └───────────────┬────────────┘ │
└──────────────────┼───────────────────────────────┼──────────────┘
                   │                               │
                   ▼                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                        核心业务层                                │
│                                                                  │
│   ┌────────────────────────────────────────────────────────┐    │
│   │                    knowledge.py                         │    │
│   │                   (1176 行，核心引擎)                   │    │
│   │                                                         │    │
│   │  ┌─────────────┐  ┌─────────────┐  ┌───────────────┐  │    │
│   │  │  提取模块    │  │  检索模块    │  │  质量评分模块  │  │    │
│   │  │             │  │             │  │               │  │    │
│   │  │ 字段验证     │  │ 标签过滤     │  │ 40分:key_dec  │  │    │
│   │  │ 去重检测     │  │ Embedding   │  │ 20分:solution │  │    │
│   │  │ 自动推断     │  │ 余弦相似度   │  │ 15分:files    │  │    │
│   │  │ 质量评分     │  │ 阈值过滤≥.5 │  │ 15分:stack    │  │    │
│   │  │ 向量生成     │  │ TopK 返回   │  │ 10分:去重距离 │  │    │
│   │  └─────────────┘  └─────────────┘  └───────────────┘  │    │
│   │                                                         │    │
│   │  ┌─────────────┐  ┌─────────────┐  ┌───────────────┐  │    │
│   │  │  反馈模块    │  │  A/B 测试   │  │  自动推断模块  │  │    │
│   │  │             │  │             │  │               │  │    │
│   │  │ confidence  │  │ hash分组    │  │ 10+技术栈     │  │    │
│   │  │ 动态更新     │  │ 10%对照组   │  │ 40+场景标签   │  │    │
│   │  │ 自动归档     │  │ 效果对比    │  │ 问题类型推断   │  │    │
│   │  └─────────────┘  └─────────────┘  └───────────────┘  │    │
│   └────────────────────────────────────────────────────────┘    │
│                                                                  │
│   ┌──────────────────────────┐   ┌────────────────────────────┐ │
│   │       embeddings.py      │   │        models.py            │ │
│   │                          │   │                             │ │
│   │  BGE-small-zh-v1.5       │   │  Experience                 │ │
│   │  (384 维, ~90MB)          │   │  Session                    │ │
│   │  本地推理, 离线可用        │   │  Feedback                   │ │
│   │  归一化余弦相似度          │   │  ExperienceMetadata         │ │
│   └────────────┬─────────────┘   └────────────────────────────┘ │
└────────────────┼────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                        存储层（三层）                            │
│                                                                  │
│   Layer 1: 经验数据               Layer 2: 向量索引              │
│   ┌─────────────────────┐        ┌──────────────────────────┐   │
│   │  ~/.xp/knowledge    │        │  ~/.xp/metrics.db        │   │
│   │      .json          │        │  [experience_vectors]    │   │
│   │                     │        │                          │   │
│   │  JSON 结构化存储     │        │  384维 BLOB 压缩          │   │
│   │  ExperienceStore    │        │  1条 = 1.5KB             │   │
│   │  add/get/update/    │        │  VectorStore             │   │
│   │  delete/list        │        │  save/get/delete         │   │
│   └─────────────────────┘        └──────────────────────────┘   │
│                                                                  │
│   Layer 3: 指标与事件                                            │
│   ┌────────────────────────────────────────────────────────┐    │
│   │  ~/.xp/metrics.db                                       │    │
│   │                                                         │    │
│   │  sessions          search_events     review_events      │    │
│   │  feedback          experience_stats  (A/B分组结果)       │    │
│   └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼ (Phase 3 扩展)
┌─────────────────────────────────────────────────────────────────┐
│                      云端层（规划中）                            │
│   Supabase / Weaviate / Elasticsearch / PostgreSQL+pgvector      │
│   cloud_providers.py / backends/postgres.py                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、核心数据模型

```
Experience
├── id: UUID
├── type: ExperienceType        # bugfix / feature / pattern
├── level: ExperienceLevel      # L1 架构 / L2 场景 / L3 修复
├── title, problem, solution
├── key_decisions               # 关键！质量评分核心字段
├── confidence: float           # 动态调整，< 0.1 自动归档
├── status: pending/active/archived
├── metadata
│   ├── tech_stack: [react, ts, python...]   # 自动推断，10+ 种
│   ├── scene: [表单, 异步, 路由...]          # 自动推断，40+ 种
│   └── problem_type: str
├── related_files, file_hashes  # Phase 3：失效检测
└── project                     # Phase 3：多项目隔离
```

**Session（会话数据）**:
```
Session
├── session_id: str
├── task_description: str
├── experience_ids_injected: list
├── iteration_count: int
├── had_error_correction: bool
├── user_accepted: bool
├── ab_test_group: str          # "control"(10%) / "treatment"(90%)
└── ab_test_result_shown: bool
```

---

## 四、信息流转流程图

### 4.1 任务执行完整生命周期

```
┌─────────────────────────────────────────────────────────────────┐
│ 阶段 1：任务开始 - 检索注入                                      │
│                                                                  │
│  Agent ──search_best_practices(query)──▶ knowledge.py           │
│                                                ↓                 │
│                                   1. 加载所有 active 经验        │
│                                   2. 计算 query Embedding        │
│                                   3. 余弦相似度排序              │
│                                   4. 过滤 score >= 0.5           │
│                                   5. A/B 分组判断               │
│                                          ↓                      │
│           ◀────── 返回 TopK 经验 (含 experience_ids) ───────    │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│ 阶段 2：任务完成 - 提取沉淀                                      │
│                                                                  │
│  Agent ──extract_experience(...)──▶ knowledge.py                │
│                                          ↓                      │
│                          ┌───────────────────────────────┐      │
│                          │         质量门禁               │      │
│                          │  key_decisions >= 10字 ✓       │      │
│                          │  solution >= 20字 ✓            │      │
│                          │  重复检测 < 0.85 ✓             │      │
│                          └───────────────┬───────────────┘      │
│                                          ↓                      │
│                          ┌───────────────────────────────┐      │
│                          │         自动推断               │      │
│                          │  tech_stack (关键词匹配)        │      │
│                          │  scene (40+ 预定义标签)         │      │
│                          │  problem_type (模式匹配)        │      │
│                          └───────────────┬───────────────┘      │
│                                          ↓                      │
│                          ┌───────────────────────────────┐      │
│                          │         质量评分               │      │
│                          │  key_decisions 内容: 40分      │      │
│                          │  solution 内容:    20分        │      │
│                          │  related_files:   15分         │      │
│                          │  tech_stack:      15分         │      │
│                          │  去重距离:         10分         │      │
│                          └───────────────┬───────────────┘      │
│                                          ↓                      │
│                       score<40 → 拒绝                           │
│                       40-79   → pending (等待人工 review)        │
│                       >=80    → active  (confidence=0.65)        │
│                                          ↓                      │
│              knowledge.json ◀── 写入经验                         │
│              metrics.db     ◀── 写入 Embedding 向量              │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│ 阶段 3：人工审核 (xp review)                                     │
│                                                                  │
│  工程师 ──xp review──▶ cli.py ──▶ knowledge.py                  │
│                                          ↓                      │
│              列出所有 pending 经验（含质量评分）                  │
│                                          ↓                      │
│     [y] 确认 ──▶ status=active,  confidence=0.8                 │
│     [e] 编辑 ──▶ status=active,  confidence=1.0                 │
│     [n] 拒绝 ──▶ status=archived                                │
│     [s] 跳过 ──▶ 保持 pending                                   │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│ 阶段 4：反馈驱动优化                                             │
│                                                                  │
│  Agent ──record_feedback(id, adopted)──▶ knowledge.py           │
│                                          ↓                      │
│       metrics.db.feedback ◀── 记录采纳/拒绝事件                  │
│       metrics.db.experience_stats ◀── 更新统计                  │
│                                          ↓                      │
│       new_confidence = old × 0.9 + adoption_rate × 0.1          │
│                                          ↓                      │
│       confidence < 0.1 ──▶ 自动归档（不再参与检索）              │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 A/B 测试流程

```
search_best_practices(session_id)
         ↓
hash(session_id) % 10 == 0?
    ├── YES (10%) → 对照组: ab_test_group="control"
    │              返回空经验，不注入
    └── NO  (90%) → 实验组: ab_test_group="treatment"
                   正常检索注入经验
         ↓
record_session(session_id, user_accepted, iteration_count)
         ↓
xp stats → 对比两组效果

                有注入    无注入
平均对话轮数     3.2       5.7
报错率          18%       41%
用户接受率       84%       67%
```

---

## 五、模块依赖关系

```
server.py ──▶ knowledge.py ──▶ storage.py
                │                  ├── ExperienceStore (knowledge.json)
                │                  ├── VectorStore     (metrics.db)
                │                  └── MetricsStore    (metrics.db)
                │
                ├──▶ embeddings.py ──▶ BGE-small-zh / OpenAI API
                └──▶ models.py

cli.py ──▶ knowledge.py (复用同一套业务逻辑)
       └──▶ cloud_providers.py (Phase 3: sync up/down)

backends/postgres.py ──▶ asyncpg (Phase 3: 替换 SQLite)
file_watcher.py      ──▶ watchdog (Phase 3: 文件变更监听)
project_config.py    ──▶ 项目隔离配置
```

---

## 六、各模块详细说明

| 模块 | 行数 | 职责 |
|------|------|------|
| `knowledge.py` | 1176 | 核心引擎：提取/检索/反馈/质量评分/自动推断 |
| `storage.py` | 646 | 三层存储抽象：JSON + SQLite 向量 + SQLite 指标 |
| `cli.py` | 714 | 14 个 CLI 命令交互界面 |
| `server.py` | 458 | MCP Server，7 个工具暴露给 IDE |
| `cloud_providers.py` | 505 | 云同步（Supabase/Weaviate/ES，Phase 3） |
| `backends/postgres.py` | 298 | PostgreSQL 异步后端（Phase 3） |
| `embeddings.py` | 86 | BGE-small-zh-v1.5 向量化，384维 |
| `models.py` | 110 | 5 个数据类定义 |
| `file_watcher.py` | — | 文件变更监听，失效检测（Phase 3） |
| `project_config.py` | — | 多项目配置隔离（Phase 3） |

---

## 七、MCP 工具与 CLI 命令

### MCP Tools（7 个）

| 工具 | 阶段 | 说明 |
|------|------|------|
| `search_best_practices` | Phase 1 | 检索相关历史经验 |
| `extract_experience` | Phase 1 | 提取并沉淀经验 |
| `record_session` | Phase 1 | 记录会话数据（A/B 测试） |
| `record_feedback` | Phase 1 | 记录经验采纳/拒绝反馈 |
| `finalize_task` | Phase 2 | 一键完成（合并提取+记录+推断） |
| `infer_adoption` | Phase 2 | 自动推断经验采纳情况 |

### CLI 命令（14 个）

```bash
xp add                  # 交互式手动添加经验
xp review               # 逐条审核 pending 经验
xp edit <ID>            # 编辑并重新激活经验
xp archive <ID>         # 归档经验
xp delete <ID>          # 永久删除经验
xp import <文件>        # 从 Markdown 文件批量导入
xp stats                # 查看统计数据
xp stats --since 7d     # 查看近 7 天统计
xp analyze              # 质量分析报告（7 类 pattern）
xp project list         # 列出所有项目
xp project switch <名>  # 切换项目
xp watch                # 文件监听（Phase 3）
xp sync up/down         # 云端同步（Phase 3）
```

---

## 八、质量评分系统

| 评分项 | 分值 | 条件 |
|--------|------|------|
| `key_decisions` 内容 | 40 分 | >= 50 字 |
| `solution_summary` 内容 | 20 分 | >= 50 字 |
| `related_files` 非空 | 15 分 | 至少 1 个文件 |
| `tech_stack` 推断成功 | 15 分 | 自动识别到技术栈 |
| 重复距离 | 10 分 | 与已有经验相似度 <= 0.6 |

| 总分 | 处理结果 |
|------|---------|
| < 40 | 直接拒绝 |
| 40–79 | 标记 pending，等待人工审核 |
| >= 80 | 自动激活，confidence = 0.65 |

---

## 九、三层存储架构

| 层级 | 存储位置 | 格式 | 操作类 |
|------|---------|------|--------|
| Layer 1：经验数据 | `~/.xp/knowledge.json` | JSON | `ExperienceStore` |
| Layer 2：向量索引 | `~/.xp/metrics.db[experience_vectors]` | SQLite BLOB | `VectorStore` |
| Layer 3：指标事件 | `~/.xp/metrics.db` | SQLite | `MetricsStore` |

**metrics.db 表结构**:
```sql
sessions              -- 会话记录（含 A/B 分组）
search_events         -- 搜索事件（查询 + 结果数）
review_events         -- 审核事件（action + 拒绝原因）
feedback              -- 反馈记录（experience_id + adopted）
experience_stats      -- 经验统计（hit_count / adopted_count / adoption_rate）
experience_vectors    -- 向量索引（384维 BLOB）
```

---

## 十、技术栈与依赖

| 模块 | 技术 | 用途 |
|------|------|------|
| Embedding | sentence-transformers | BGE-small-zh-v1.5 向量化 |
| 向量相似度 | NumPy | 余弦相似度计算 |
| 存储 | SQLite | 向量索引和指标 |
| CLI | argparse | 命令行交互 |
| MCP | mcp-sdk | IDE 集成协议 |
| LLM | OpenAI API | 可选：生成标题 |
| 异步 | asyncio | 异步操作支持 |
| 云端（规划） | Supabase/Weaviate/ES | Phase 3：多云支持 |

---

## 十一、Phase 规划与进度

### Phase 1（MVP，已完成）
- 经验提取、检索、反馈、会话记录
- 本地 JSON + SQLite 存储
- BGE Embedding 向量检索
- 基础 A/B 测试框架
- CLI 命令行工具

### Phase 2（进行中）
- 质量评分细化
- 自动激活策略（评分 >= 80）
- `xp analyze` 质量分析（7 类 pattern）
- Confidence 动态更新

### Phase 3（计划中）
- 文件监听 + 失效检测
- PostgreSQL + pgvector 存储迁移
- 云端同步（Supabase/Weaviate/Elasticsearch）
- 权限管理（Admin/Writer 角色）
- 多项目隔离支持
- FastAPI 中心化服务

---

## 十二、数据规模估算

| 规模 | 经验数 | 数据量 | 向量存储 |
|------|--------|--------|---------|
| 小团队（10人，6个月） | 200–500 条 | ~10MB | ~750KB |
| 中等团队（50人，1年） | 1000–3000 条 | ~50–150MB | ~1.5–4.5MB |
| 大型团队（100+人） | 10000+ 条 | >500MB | 推荐迁移至 PostgreSQL+pgvector |
