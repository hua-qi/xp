# XP 项目测试验收文档

> 版本：v1.0 · 日期：2026-02-04

---

## 一、测试策略总览

本项目采用 **TDD 三层测试体系**，每一层有明确职责，不允许跨层替代。

```
单元测试（Unit）             → 验证业务决策逻辑是否正确
集成测试（Integration）      → 验证完整用例流程是否通畅
契约测试（Contract）         → 验证模块间接口是否稳定
特征测试（Characterization） → 固化外部可见行为，防止回归
```

---

## 二、单元测试验收标准

### 2.1 覆盖范围

`tests/unit/` 只测试 `src/domain/` 下的纯函数，**禁止任何 I/O 和 mock**。

| 模块 | 必须覆盖的测试点 |
|------|----------------|
| `domain/quality.py` | 质量分计算：内容长度、技术栈完整性、场景明确性各维度 |
| `domain/metadata.py` | tech_stack 推断、scene 推断、level 推断 |
| `domain/feedback.py` | 置信度增量计算：helpful=True / False / 边界值 |
| `domain/experience.py` | 状态机转换：PENDING→ACTIVE、ACTIVE→ARCHIVED、非法转换抛异常 |
| `domain/search.py` | 相似度排序、A/B 分组逻辑、limit 边界 |

### 2.2 验收标准

- [ ] 所有 `tests/unit/` 测试通过，**零 mock，零 I/O**
- [ ] 单个测试执行时间 < 1ms
- [ ] `domain/` 层代码覆盖率 ≥ 90%
- [ ] 每个业务规则（含边界条件）至少有 1 个对应测试

### 2.3 示例测试结构

```python
# tests/unit/test_quality.py

def test_quality_score_empty_content_returns_zero():
    score = compute_quality_score(content="", metadata=minimal_meta())
    assert score == 0

def test_quality_score_full_content_exceeds_threshold():
    score = compute_quality_score(content=RICH_CONTENT, metadata=full_meta())
    assert score >= 80

def test_quality_score_missing_tech_stack_penalized():
    score_with = compute_quality_score(CONTENT, meta_with_tech_stack())
    score_without = compute_quality_score(CONTENT, meta_without_tech_stack())
    assert score_with > score_without
```

---

## 三、集成测试验收标准

### 3.1 覆盖范围

`tests/integration/` 测试完整的 Handler 流程，使用 `InMemoryUnitOfWork`，**不访问真实文件系统、数据库、LLM**。

| 用例 | Handler | 必须验证 |
|------|---------|---------|
| 创建经验（高质量） | ExperienceHandler | Experience 已存入、EmbeddingRequested 已发布、状态为 ACTIVE |
| 创建经验（低质量） | ExperienceHandler | Experience 已存入、状态为 PENDING、无 ExperienceActivated 事件 |
| 创建重复经验 | ExperienceHandler | DuplicateDetected 事件已发布、新 Experience 未存入 |
| 语义搜索 | SearchHandler | 返回结果按相关性排序、ExperienceHit 事件已发布 |
| 记录有效反馈 | FeedbackHandler | 置信度上升、FeedbackRecorded 事件已发布 |
| 记录无效反馈 | FeedbackHandler | 置信度下降（不低于 0）|
| 手动激活经验 | ExperienceHandler | 状态变为 ACTIVE、ExperienceActivated(triggered_by="manual") |
| 归档经验 | ExperienceHandler | 状态变为 ARCHIVED、ExperienceArchived 事件已发布 |
| 质量分析 | AnalyticsHandler | 返回包含 7 项指标的报告，无异常 |
| 存储回滚（VectorStore 失败） | ExperienceHandler | Experience 未存入（主数据也回滚）|

### 3.2 验收标准

- [ ] 所有 `tests/integration/` 测试通过
- [ ] 单个测试执行时间 < 100ms
- [ ] Happy path 全覆盖（见上表）
- [ ] 至少 3 个错误/边界场景测试（重复、回滚、低质量）
- [ ] 使用 `InMemoryUnitOfWork`，不依赖真实存储

### 3.3 InMemoryUnitOfWork 规范

```python
# tests/helpers/fake_uow.py

class InMemoryUnitOfWork:
    def __init__(self):
        self.experiences = InMemoryExperienceStore()
        self.vectors     = InMemoryVectorStore()
        self.metrics     = InMemoryMetricsStore()
        self.events      = []
        self.committed   = False

    def collect_event(self, event):
        self.events.append(event)

    def __enter__(self): return self
    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self.committed = True
```

---

## 四、契约测试验收标准

### 4.1 覆盖范围

`tests/contract/` 固化 Command 和 Event 的 schema，防止字段变更导致调用方静默失效。

| 契约 | 验证内容 |
|------|---------|
| `CreateExperienceCommand` | 必填字段、字段类型、序列化/反序列化往返一致 |
| `SearchExperienceCommand` | `limit` 默认值为 10、`tech_stack` 默认为空列表 |
| `ExperienceCreated` 事件 | 字段完整性、frozen（不可变）|
| `FeedbackRecorded` 事件 | `new_confidence` 在 [0, 1] 范围内 |
| CLI → Command | `xp extract` 参数正确映射到 `CreateExperienceCommand` |
| REST → Command | `POST /api/experiences` body 正确映射到 `CreateExperienceCommand` |

### 4.2 验收标准

- [ ] 所有 `tests/contract/` 测试通过
- [ ] Command schema 新增必填字段时，契约测试**必须同步更新**（不允许给默认值绕过）
- [ ] Event schema 变更时，所有订阅该事件的 Handler 测试必须同步通过
- [ ] CLI 和 REST 接口的参数映射各有独立契约测试

---

## 五、特征测试验收标准

### 5.1 覆盖范围

`tests/characterization/` 固化当前系统的外部可见行为，主要用于重构期间防止行为回归。

| 测试 | 固化行为 |
|------|---------|
| `test_metadata_infer.py` | 给定文本，推断出的 tech_stack / scene / level 固定 |
| `test_search_ranking.py` | 给定 query + 候选集，返回结果顺序固定 |
| `test_quality_thresholds.py` | 给定标准内容，质量分在预期范围内 |

### 5.2 验收标准

- [ ] 特征测试在重构前后输出**完全一致**
- [ ] 允许使用真实存储（但要使用测试专用临时目录）
- [ ] 重构阶段每个 Phase 完成后必须跑一次特征测试

---

## 六、各阶段测试门控

每个重构阶段合并到 main 前，必须满足对应门控：

| 阶段 | 必须通过的测试 | 禁止退步 |
|------|---------------|---------|
| Phase 1（骨架） | 原有全量测试 | 不允许任何原有测试变红 |
| Phase 2（领域迁移） | 原有全量 + `tests/unit/` 全量 | 单元测试覆盖率 ≥ 90% |
| Phase 3（UoW） | 上述 + `tests/integration/` 回滚测试 | InMemoryUoW happy path 通过 |
| Phase 4（CommandBus） | 上述 + `tests/contract/` 全量 | CLI/REST 契约测试通过 |
| Phase 5（删上帝类） | 全量测试（四层全绿） | 无 KnowledgeService 引用 |

---

## 七、测试运行命令速查

```bash
# 全量（CI 使用，跳过需要外部服务的测试）
python3 -m pytest tests/ -q -k "not server and not postgres"

# 只跑单元测试（TDD 开发循环，最快）
python3 -m pytest tests/unit/ -q

# 只跑集成测试
python3 -m pytest tests/integration/ -q

# 只跑契约测试
python3 -m pytest tests/contract/ -q

# 只跑特征测试
python3 -m pytest tests/characterization/ -q

# 查看覆盖率
python3 -m pytest tests/unit/ --cov=src/domain --cov-report=term-missing
```

---

## 八、禁止事项

- **禁止**在 `tests/unit/` 中使用 `mock.patch` 或任何 mock 框架
- **禁止**在 `tests/unit/` 中访问文件系统、数据库、网络
- **禁止**测试方法超过 30 行（超过说明用例粒度太大，需拆分）
- **禁止**跳过失败的测试（`@pytest.mark.skip`）而不记录原因和 ticket
- **禁止**多个测试共享可变状态（每个测试必须独立）
