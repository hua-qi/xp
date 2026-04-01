# XP 多人共享经验改造技术方案

## 1. 目标

支持团队多人使用 MCP 和 XP 工具，实现经验沉淀和共享：
- 多人通过 IDE (Claude/Cursor/Windsurf) 使用 MCP 协议共享经验库
- 统一的 Web 服务部署在云端
- 保留现有的 Embedding 向量检索方案

## 2. 整体架构

```
                    ┌──────────────────────────┐
                    │      快手 K8s 集群        │
                    │  ┌────────────────────┐  │
                    │  │   xp-server        │  │  ← MCP over SSE
                    │  │  - Embedding 检索  │  │
                    │  └────────┬───────────┘  │
                    │           │              │
                    │  ┌────────┴───────────┐  │
                    │  │   PostgreSQL (KDB) │  │  ← 托管数据库
                    │  │  - 纯文本字段       │  │
                    │  └────────────────────┘  │
                    └───────────┬──────────────┘
                                │ HTTPS/SSE
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
   ┌────┴────┐            ┌────┴────┐            ┌────┴────┐
   │ Claude  │            │ Cursor  │            │ Windsurf│
   │ MCP配置  │            │ MCP配置  │            │ MCP配置  │
   └─────────┘            └─────────┘            └─────────┘

xp-cli 管理工具 (pip install)
├── xp review    # 审核经验
├── xp add       # 手动添加
├── xp list      # 查看经验
└── xp stats     # 统计数据
```

## 3. 架构决策

### 3.1 前后端分离 (C/S 架构)

| 模式 | 说明 |
|------|------|
| **xp-server** | 云端 MCP 服务，处理经验检索、存储、管理 |
| **xp-cli** | 本地管理工具，用于 review/add/list/stats |
| **MCP Client** | IDE 内置，通过 SSE 连接 xp-server |

### 3.2 为什么不保持纯本地？

- 多人共享需要中心化存储
- MCP 协议天然支持远程服务（SSE transport）
- 经验审核、权限控制需要服务端支持

## 4. 组件设计

### 4.1 xp-server (K8s 部署)

**职责**：
- 提供 MCP 协议接口（SSE transport）
- 经验检索（Embedding 向量检索）
- 经验存储（PostgreSQL）
- 用户身份识别

**技术栈**：
- Python + FastAPI/Sanic
- MCP SDK (SSE transport)
- PostgreSQL 连接池

**K8s 资源配置**：
```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: xp-server
spec:
  replicas: 2
  selector:
    matchLabels:
      app: xp-server
  template:
    spec:
      containers:
      - name: xp-server
        image: xp-server:latest
        env:
        - name: DATABASE_URL
          value: "postgresql://user:pass@kdb-host:5432/xp"
        ports:
        - containerPort: 8000
---
apiVersion: v1
kind: Service
metadata:
  name: xp-server
spec:
  selector:
    app: xp-server
  ports:
  - port: 80
    targetPort: 8000
```

### 4.2 PostgreSQL (KDB)

**选择 KDB 而非容器云自托管的原因**：

| 维度 | KDB | 容器云自托管 |
|------|-----|--------------|
| 运维成本 | 零运维，自动备份 | 需自行维护 |
| 可靠性 | 高可用、自动故障转移 | 需自行配置 |
| 性能 | 专业调优 | 依赖容器资源 |
| 扩展性 | 一键扩缩容 | 手动调整 |

**数据表结构**：

```sql
-- 经验表
CREATE TABLE experiences (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    problem TEXT NOT NULL,
    solution TEXT NOT NULL,
    tech_stack TEXT[],
    problem_type TEXT,
    scene TEXT[],
    keywords TEXT[],
    status TEXT DEFAULT 'pending',  -- pending/active/archived
    source TEXT DEFAULT 'agent',     -- agent/manual
    created_by TEXT,
    project TEXT DEFAULT 'default',
    related_files TEXT[],
    file_hashes JSONB,
    reject_reason TEXT,
    last_hit_at TIMESTAMP,
    stale_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 全文检索索引（可选，用于备选检索方案）
CREATE INDEX idx_fts ON experiences 
USING GIN (to_tsvector('chinese', 
    COALESCE(title,'') || ' ' || 
    COALESCE(problem,'') || ' ' || 
    COALESCE(solution,'')
));

-- 经验统计表
CREATE TABLE experience_stats (
    experience_id TEXT PRIMARY KEY,
    hit_count INTEGER DEFAULT 0,
    adopted_count INTEGER DEFAULT 0,
    rejected_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    last_adopted_at TIMESTAMP,
    adoption_rate REAL DEFAULT 0.0
);

-- 会话记录表
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    task_description TEXT NOT NULL,
    experience_ids_injected TEXT[],
    iteration_count INTEGER NOT NULL,
    had_error_correction BOOLEAN NOT NULL,
    user_accepted BOOLEAN NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 反馈记录表
CREATE TABLE feedback (
    id SERIAL PRIMARY KEY,
    experience_id TEXT NOT NULL,
    adopted BOOLEAN NOT NULL,
    reason TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 搜索事件记录
CREATE TABLE search_events (
    id SERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    result_count INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 审核事件记录
CREATE TABLE review_events (
    id SERIAL PRIMARY KEY,
    experience_id TEXT NOT NULL,
    action TEXT NOT NULL,  -- confirmed/rejected
    reject_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 4.3 xp-cli

**发布方式**：`pip install xp-cli`

**两种工作模式**：

```bash
# 本地模式（单人使用，向后兼容）
xp review --local

# 远程模式（团队协作，连接云端）
xp review --remote https://xp-server.kuaishou.net
```

**配置**：
```yaml
# ~/.xp/config.yaml
mode: remote  # local/remote
server:
  url: https://xp-server.kuaishou.net
  api_key: xxxx-xxxx-xxxx
```

## 5. Embedding 向量检索方案

### 5.1 方案说明

使用 BGE-small-zh-v1.5 本地推理，将经验文本编码为向量后存入 SQLite，检索时计算余弦相似度排序：

```python
from sentence_transformers import SentenceTransformer
import numpy as np

class ExperienceService:
    def __init__(self, db):
        self.db = db
        self._model = SentenceTransformer("BAAI/bge-small-zh-v1.5")

    def search(self, query: str, tech_stack: list[str] = None,
               top_k: int = 5) -> list[dict]:
        query_vec = self._model.encode(query, normalize_embeddings=True)
        candidates = self._load_candidates(tech_stack)
        scores = [np.dot(query_vec, c["vector"]) for c in candidates]
        results = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
        return [r[0] for r in results[:top_k] if r[1] >= 0.5]
```

### 5.2 缓存刷新策略

| 触发条件 | 操作 |
|----------|------|
| Server 启动 | 全量加载向量 |
| 经验审核通过 | 计算并存储向量 |
| 经验被编辑 | 重新计算向量 |
| 经验删除 | 同步清除向量 |

## 6. 改造任务清单

### Phase 1: 服务端改造

- [ ] 重构 `server.py` 支持 SSE transport
- [ ] 实现 PostgreSQL 存储层（`storage_pg.py`）
- [ ] 实现内存 Embedding 向量检索服务
- [ ] 添加用户身份识别（API Key）
- [ ] Dockerfile 和 K8s 配置

### Phase 2: 数据库准备

- [ ] 申请 KDB PostgreSQL 实例
- [ ] 执行初始化 SQL 建表
- [ ] 配置连接池参数

### Phase 3: 客户端改造

- [ ] 改造 `cli.py` 支持 `--remote` 模式
- [ ] 添加配置文件支持（`~/.xp/config.yaml`）
- [ ] 保留 `--local` 模式向后兼容

### Phase 4: 发布部署

- [ ] 构建 Docker 镜像
- [ ] 部署到 K8s
- [ ] 配置域名和 HTTPS
- [ ] 发布 `xp-cli` 到内部 PyPI

### Phase 5: 文档和接入

- [ ] 编写 MCP 配置文档
- [ ] 团队接入指引
- [ ] 监控告警配置

## 7. MCP 客户端配置示例

```json
// ~/.cursor/mcp.json
{
  "xp-server": {
    "type": "sse",
    "url": "https://xp-server.kuaishou.net/sse",
    "headers": {
      "Authorization": "Bearer xxxx-xxxx-xxxx"
    }
  }
}
```

## 8. 安全考虑

| 层面 | 措施 |
|------|------|
| 传输层 | HTTPS + SSE |
| 认证 | API Key / SSO Token |
| 授权 | 项目隔离，经验可见范围控制 |
| 审计 | 记录所有搜索/审核/反馈操作 |
| 数据 | KDB 自动备份，保留 30 天 |

## 9. 性能预估

| 指标 | 预估 | 说明 |
|------|------|------|
| 内存占用 | ~200MB | 10万条经验缓存 |
| 检索延迟 | < 50ms | Embedding 向量计算 |
| 并发支持 | 100+ | K8s 水平扩展 |
| 数据库连接 | 20 | 连接池配置 |

---

*文档版本: v1.0*
*更新日期: 2025-03-26*
