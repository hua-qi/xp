# 团队级知识层级体系与经验流动

## 概述

xp 采用三层知识层级，对应组织结构，将 coding 最佳实践从项目级别逐步沉淀为业务级别和团队级别，实现跨项目、跨业务的知识共享与复用。

## 设计思路

### 层级结构

```
Team（团队）—— 最抽象，跨业务通用
  └── Business（业务）—— 中等抽象，某业务下共享
        └── Project（项目 = Git 仓库）—— 最具体，单个 repo 内共享
```

三层层级与组织结构对应：
- 一个团队下有多个业务
- 一个业务下有多个项目（代码仓库）
- 经验随着层级递增，越来越抽象与通用

### 经验归属原则

- **Project 经验**：由 agent 在 git 仓库内自动沉淀，同一仓库所有成员共享，内容最具体
- **Business 经验**：由人工从 Project 层遴选提升，在业务下所有项目中共享
- **Team 经验**：由人工从 Business 层遴选提升，在整个团队中共享，最为抽象通用

### 经验双向流动

经验不是固定在某一层级，支持人工**双向迁移**：

```
Project ←→ Business ←→ Team
  （提升）      （提升）
  （降级）      （降级）
```

- **提升**：把较具体的经验抽象化表达，推广到更高层级
- **降级**：把通用原则具体化，落地到某个 Business 或 Project
- 迁移后，原经验**保留**，在目标层级创建新副本
- 通过 `promoted_to` / `demoted_from` 字段关联，便于溯源

## 实现细节

### 提升候选算法

Agent 定时扫描（每天/每周），通过多维度评分发现应该被提升的经验：

```
提升得分 = 跨项目出现次数 × 0.5
         + adoption_rate × 0.3
         + min(recall_count / 10, 1) × 0.2
```

**触发提升候选的条件（全部满足）**：
1. 同 Business 下 ≥ 2 个不同 Project 存在语义相似经验（向量相似度 > 0.85）
2. `adoption_rate > 0.6` 且 `recall_count > 5`（有足够的使用数据）
3. `created_at > 30 天前`（排除不稳定的新经验）
4. 综合得分 > 0.7

满足条件后，系统将经验标记为「提升候选」，通知相应的 business owner 或 team admin 审核。Agent 推荐时会附上理由，例如：「该经验在 3 个项目中均有相似记录，采纳率 72%，建议提升到 Business 层」。

### 人工操作

| 操作 | 执行者 | 行为 |
|------|--------|------|
| 确认提升 | business owner / team admin | 经验写入上层（可编辑表达），原经验保留，打标 `promoted_to` |
| 手动降级 | business owner / team admin | 经验移至下层（可编辑表达），原经验保留，打标 `demoted_from` |
| 删除 | 对应层级的 owner | 永久删除该层的经验，不影响其他层级的副本 |

### 召回策略

Agent 搜索时，**三个层级并发检索**，按加权相似度合并返回：

```
Project 搜索结果 × 1.2
Business 搜索结果 × 1.0
Team 搜索结果 × 0.9
→ 合并排序，去重（同一经验的不同层级副本只保留最高分）
→ 取 Top-5 返回
```

Project 层权重略高，因为最具体、最相关。

### 数据模型

```python
Experience:
    scope_type: project | business | team   # 所属层级
    scope_id: str                           # 层级对应的 id
    promoted_to: UUID | None                # 提升副本的 id
    demoted_from: UUID | None               # 降级副本的 id
    recall_count: int                       # 被召回次数
    adoption_rate: float                    # 采纳率
    last_hit_at: datetime                   # 最后召回时间

PromotionCandidate:
    id: str
    experience_id: str
    target_scope_type: str                  # "business" | "team"
    target_scope_id: str
    score: float
    status: str                             # "pending" | "promoted" | "ignored"
    ignored_at: Optional[str]

Project:
    id: str                    # 标准化的 git remote URL
    business_id: UUID          # 仅用于单对多回退兼容
    name: str
    language: str              # 从 project_manifest 解析
    frameworks: list[str]      # 从 project_manifest 解析

# 多对多关联（Project ↔ Business 多对多，Business ↔ Team 多对多）
ProjectBusinessLink:
    project_id: str
    business_id: str

BusinessTeamLink:
    business_id: str
    team_id: str

Business:
    id: UUID
    team_id: UUID              # 保留单对多字段用于兼容
    name: str
    owner_email: Optional[str]

Team:
    id: UUID
    name: str
    owner_email: Optional[str]
```

### 层级展开逻辑

`resolve_scope_ids`（`src/domain/search_v2.py`）给定 `project_id` 和多对多映射，返回各层的 scope_id 列表：

```python
resolve_scope_ids(
    project_id="proj-001",
    project_to_businesses={"proj-001": ["biz-001", "biz-002"]},
    business_to_teams={"biz-001": ["team-001"], "biz-002": ["team-001"]},
)
# → {"project": ["proj-001"], "business": ["biz-001", "biz-002"], "team": ["team-001"]}
# team 自动去重
```

### 升层目标判断

`determine_promotion_target`（`src/domain/promotion.py`）根据评分和跨越范围判断应升至哪层：

```
score > 0.7 且 cross_project_count ≥ 2：
    cross_business_count ≥ 2 → "team"
    否则 → "business"
score ≤ 0.7 或 cross_project_count < 2 → None（不升层）
```

### 权限模型

```
personal_token → 解析 user_id → 所属 team_id

search / save：project 成员可操作
人工 review / 提升 / 降级：business owner 或 team admin
```

## 接口与使用

提升候选的查看和操作通过 REST API（`/api`）和 CLI 管理命令提供，不通过 MCP tool 暴露（属于管理操作，不应由 agent 自主执行）。

## 相关文件

- `docs/design/adr/ADR-002-team-knowledge-hierarchy-and-centralized-deployment.md` - 架构决策记录
- `docs/features/mcp-tools-v2.md` - 3 个 MCP tool 设计（search 的多层召回逻辑在此详述）
- `docs/designs/2026-05-04-xp-team-knowledge-refactor.md` - 原始设计草稿

---
**文档版本**: v1.1  
**最后更新**: 2026-06-04
