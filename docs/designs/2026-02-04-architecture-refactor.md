# XP 架构重构设计文档

> 版本：v1.0 · 日期：2026-02-04  
> 状态：已审阅，待实施

---

## 一、背景与动机

### 当前问题

| 问题 | 具体表现 | 影响 |
|------|---------|------|
| 上帝类 | `KnowledgeService` 727 行，20+ 方法，横跨 7 个领域 | 难以理解、测试、维护 |
| 无依赖注入 | 服务在内部直接实例化 I/O 对象 | 测试必须 mock 多个依赖，脆弱 |
| 无事务边界 | JSON / SQLite / Vector 三存储各自独立写入 | 任意步骤失败产生脏数据 |
| 业务逻辑与 I/O 混合 | `extract()` 同时调 LLM + 写存储 | 无法单元测试业务决策 |
| 魔法数字 | `>= 80`、`>= 0.85`、`90天` 散落各处 | 修改阈值需要全局搜索 |

### 优化目标

1. **可测试性第一**：支持 TDD 三层测试（单元、集成、契约）
2. **职责单一**：每个模块只做一件事，单文件不超过 150 行
3. **数据一致性**：三存储要么全部成功，要么全部回滚
4. **可扩展性**：新增用例只需加 Command + Handler，不改现有代码

---

## 二、架构方案：事件驱动 + Unit of Work

### 2.1 为什么选事件驱动

对比 DI 容器方案：

| 维度 | DI 容器 | 事件驱动 + UoW |
|------|---------|---------------|
| 单元测试 | ✅ 好（mock 注入点）| ✅ 极好（business logic 无 I/O，天然可测）|
| 集成测试 | ✅ 好 | ✅ 极好（内存事件总线 + 内存存储）|
| 契约测试 | ⚠️ 需手动维护 | ✅ 事件 schema 即契约，变更立刻暴露 |
| 数据一致性 | ❌ 未解决 | ✅ UoW 统一提交/回滚 |
| 模块解耦 | ⚠️ 仍有直接引用 | ✅ 物理隔离，发布方不知道订阅方 |

**结论**：业务核心是"经验沉淀 + Agent 召回"（写入-读取型），事件驱动天然契合这一模式，且对 TDD 支持最优。

### 2.2 核心设计原则

```
业务逻辑（domain/）   →  只做决策，发布领域事件，零 I/O
副作用（handlers/）   →  订阅事件，执行存储 / LLM 调用
Unit of Work          →  协调三存储，保证原子性
Command Bus           →  接口层与业务层的唯一连接点
```

---

## 三、架构分层详解

### 3.1 分层图

```
┌─────────────────────────────────────────┐
│  interfaces/   CLI · REST API · MCP     │  只做参数转换
│  → dispatch(Command)                    │
└──────────────────┬──────────────────────┘
                   │ Command
┌──────────────────▼──────────────────────┐
│  application/   CommandBus · Handlers   │  编排层
│  → domain 决策 + UoW 提交               │
└──────────┬──────────────────────────────┘
           │ 调用纯函数           │ 通过注入接口
┌──────────▼──────────┐  ┌───────▼──────────────────┐
│  domain/            │  │  infrastructure/          │
│  纯函数，零 I/O      │  │  存储 · LLM · 后端         │
│  发布领域事件        │  │  实现 domain 定义的接口     │
└─────────────────────┘  └──────────────────────────┘
```

### 3.2 domain 层：纯业务逻辑

**约束**：禁止任何 import 指向 `application/` 或 `infrastructure/`

```
domain/
├── models.py       Experience、Project、Session dataclass
├── events.py       所有领域事件（frozen dataclass）
├── constants.py    所有业务阈值常量
├── experience.py   提取、激活、归档的决策逻辑
├── search.py       搜索排序、A/B 分组策略
├── feedback.py     置信度更新规则
├── quality.py      质量评分算法
└── metadata.py     tech_stack / scene / level 推断
```

### 3.3 领域事件完整定义

```python
# domain/events.py —— 所有事件均为 frozen dataclass

@dataclass(frozen=True)
class ExperienceCreated:
    experience_id: str
    title: str
    content: str
    tech_stack: list[str]
    scene: str
    level: str
    quality_score: int
    project_id: str | None

@dataclass(frozen=True)
class ExperienceActivated:
    experience_id: str
    triggered_by: Literal["auto", "manual"]

@dataclass(frozen=True)
class ExperienceArchived:
    experience_id: str
    reason: str

@dataclass(frozen=True)
class EmbeddingRequested:
    experience_id: str
    text: str

@dataclass(frozen=True)
class FeedbackRecorded:
    experience_id: str
    helpful: bool
    session_id: str | None
    old_confidence: float
    new_confidence: float

@dataclass(frozen=True)
class ExperienceHit:
    experience_id: str
    session_id: str | None
    query: str

@dataclass(frozen=True)
class DuplicateDetected:
    new_experience_id: str
    existing_experience_id: str
    similarity: float
```

### 3.4 application 层：编排与协调

#### Command 定义

```python
# application/commands.py

@dataclass
class CreateExperienceCommand:
    task_output: str
    project_id: str | None = None
    session_id: str | None = None

@dataclass
class SearchExperienceCommand:
    query: str
    tech_stack: list[str] = field(default_factory=list)
    limit: int = 10
    session_id: str | None = None

@dataclass
class RecordFeedbackCommand:
    experience_id: str
    helpful: bool
    session_id: str | None = None

@dataclass
class ActivateExperienceCommand:
    experience_id: str

@dataclass
class ArchiveExperienceCommand:
    experience_id: str
    reason: str

@dataclass
class AnalyzeQualityCommand:
    project_id: str | None = None

@dataclass
class CreateProjectCommand:
    name: str

@dataclass
class StartSessionCommand:
    project_id: str | None = None
```

#### Handler 边界

| Handler | 职责 | 依赖 | 行数上限 |
|---------|------|------|---------|
| `ExperienceHandler` | 提取、激活、归档 | uow + llm + metadata + quality | 150 |
| `SearchHandler` | 语义搜索、命中记录 | uow + vector + search domain | 100 |
| `FeedbackHandler` | 记录反馈、更新置信度 | uow + feedback domain | 80 |
| `AnalyticsHandler` | 质量分析、统计报告 | uow（只读） | 120 |
| `ProjectHandler` | 项目/会话 CRUD | uow | 80 |

#### Command Bus

```python
# application/command_bus.py

class CommandBus:
    def __init__(self):
        self._handlers: dict[type, Callable] = {}

    def register(self, command_type: type, handler_fn: Callable) -> None:
        self._handlers[command_type] = handler_fn

    def dispatch(self, command) -> Any:
        handler = self._handlers.get(type(command))
        if handler is None:
            raise UnregisteredCommandError(type(command))
        return handler(command)
```

### 3.5 Unit of Work：三存储原子提交

#### 回滚策略

| 存储 | 写入方式 | 回滚方式 |
|------|----------|----------|
| ExperienceStore (JSON) | 写临时文件，commit 时原子 rename | 丢弃临时文件 |
| VectorStore (二进制) | 追加写，记录 commit 前 offset | 截断到 offset |
| MetricsStore (SQLite) | SQLite 原生事务 | `conn.rollback()` |

#### 提交顺序

```
1. ExperienceStore.flush()      主数据，失败则整体终止
2. VectorStore.flush()          向量数据，失败则补偿重试
3. MetricsStore.flush()         指标数据，失败则补偿重试
4. dispatch_events()            全部写成功后才发布事件
```

#### 接口定义

```python
class AbstractUnitOfWork(ABC):
    experiences: AbstractExperienceStore
    vectors: AbstractVectorStore
    metrics: AbstractMetricsStore

    def collect_event(self, event) -> None: ...
    def __enter__(self) -> "AbstractUnitOfWork": ...
    def __exit__(self, exc_type, exc_val, exc_tb) -> None: ...
```

### 3.6 container.py：唯一组装点

```python
# src/container.py

def build_container(config: Config) -> CommandBus:
    backend = get_backend(config)

    experience_store = ExperienceStore(backend)
    vector_store     = VectorStore(backend)
    metrics_store    = MetricsStore(backend)

    def uow_factory():
        return UnitOfWork(experience_store, vector_store, metrics_store)

    llm              = OpenAILLM(config.openai_api_key)
    metadata         = MetadataInferrer(llm)

    experience_handler = ExperienceHandler(uow_factory, llm, metadata)
    search_handler     = SearchHandler(uow_factory, vector_store)
    feedback_handler   = FeedbackHandler(uow_factory)
    analytics_handler  = AnalyticsHandler(uow_factory)
    project_handler    = ProjectHandler(uow_factory)

    bus = CommandBus()
    bus.register(CreateExperienceCommand,   experience_handler.handle_create)
    bus.register(ActivateExperienceCommand, experience_handler.handle_activate)
    bus.register(ArchiveExperienceCommand,  experience_handler.handle_archive)
    bus.register(SearchExperienceCommand,   search_handler.handle_search)
    bus.register(RecordFeedbackCommand,     feedback_handler.handle_feedback)
    bus.register(AnalyzeQualityCommand,     analytics_handler.handle_analyze)
    bus.register(CreateProjectCommand,      project_handler.handle_create)
    bus.register(StartSessionCommand,       project_handler.handle_start_session)

    return bus
```

---

## 四、关键流程数据流

### 4.1 创建经验（主流程）

```
CLI: xp extract <output>
  → CreateExperienceCommand(task_output=..., project_id=...)
  → CommandBus.dispatch()
  → ExperienceHandler.handle_create()
      │
      ├── metadata.infer(task_output)          # 纯函数
      ├── quality.compute_score(...)           # 纯函数
      ├── experience.check_duplicate(...)      # 纯函数
      ├── llm.generate_title(task_output)      # I/O，已注入
      │
      ├── Experience.create(...)               # 构造领域对象
      │     └── 若 score >= 80: 内部发布 ExperienceActivated(auto)
      │
      └── with uow:
            uow.experiences.add(exp)
            uow.collect_event(ExperienceCreated(...))
            uow.collect_event(EmbeddingRequested(...))
            # commit → 三存储原子写入 → dispatch events
```

### 4.2 语义搜索（召回流程）

```
MCP/REST: search(query, tech_stack)
  → SearchExperienceCommand
  → SearchHandler.handle_search()
      │
      ├── vector_store.query(embedding)        # 获取候选集
      ├── search.rank(candidates, query)       # 纯函数：重排序
      ├── search.ab_assign(session_id)         # 纯函数：A/B 分组
      │
      └── with uow:
            for exp in results:
                uow.collect_event(ExperienceHit(exp.id, session_id, query))
            # commit → MetricsStore 记录命中
```

### 4.3 反馈更新置信度

```
REST: POST /api/feedback
  → RecordFeedbackCommand
  → FeedbackHandler.handle_feedback()
      │
      ├── exp = uow.experiences.get(id)
      ├── new_conf = feedback.compute_confidence(   # 纯函数
      │       exp.confidence, helpful)
      │
      └── with uow:
            uow.experiences.update_confidence(id, new_conf)
            uow.collect_event(FeedbackRecorded(..., old=exp.confidence, new=new_conf))
```

---

## 五、迁移策略（五阶段）

### 阶段一：建骨架（1-2天）

**目标**：新建目录结构，原有代码不动  
**产出**：空文件骨架、`InMemoryUnitOfWork`、`InMemoryStores`  
**门控**：原有全量测试通过

### 阶段二：迁移领域逻辑（2-3天）

**目标**：将散落在 `KnowledgeService` 中的纯函数迁移到 `domain/`  
**产出**：`domain/` 全量单元测试，覆盖率 ≥ 90%  
**门控**：`tests/unit/` 全绿，零 mock，`KnowledgeService` 只做转发

### 阶段三：引入 Unit of Work（2-3天）

**目标**：替换直接存储调用，实现三存储原子提交  
**产出**：真实 `UnitOfWork`、回滚测试、领域事件发布  
**门控**：InMemoryUoW 集成测试通过，回滚场景覆盖

### 阶段四：建立 Command Bus（2-3天）

**目标**：逐个 Handler 建立，接口层改为 `CommandBus.dispatch()`  
**产出**：5 个 Handler + 契约测试  
**门控**：`tests/contract/` 全绿，CLI/REST/MCP 均通过契约测试

### 阶段五：删除上帝类（0.5天）

**目标**：彻底删除 `KnowledgeService`  
**产出**：无 `KnowledgeService` 引用  
**门控**：四层测试全绿

### 时间线

```
Week 1   阶段一 + 阶段二   骨架 + 领域逻辑迁移
Week 2   阶段三            UoW + 事件
Week 3   阶段四            Handler + CommandBus
Week 4   阶段五            删除上帝类，收尾
```

---

## 六、风险与应对

| 风险 | 概率 | 应对 |
|------|------|------|
| LLM 调用难以在测试中隔离 | 高 | 阶段二建 `FakeLLM`，固定返回值，彻底隔离 |
| VectorStore 二进制 offset 回滚复杂 | 中 | 阶段三优先用 InMemory 验证逻辑，真实回滚最后实现 |
| 阶段中途业务需求变化 | 中 | 每阶段独立可运行，可随时暂停在当前阶段 |
| MetadataInferrer 调 LLM 边界不清晰 | 低 | 阶段二明确：纯规则推断放 domain/，LLM 辅助推断放 infrastructure/ |

---

## 七、成功标准

重构完成后，以下条件必须全部满足：

- [ ] `KnowledgeService` 文件不存在
- [ ] `domain/` 层无任何 I/O 操作（grep `open(` `sqlite` `requests` 结果为空）
- [ ] 单文件行数不超过 150 行（Handler）/ 200 行（其他）
- [ ] `tests/unit/` 覆盖率 ≥ 90%，零 mock
- [ ] `tests/integration/` 10 个核心用例全部通过
- [ ] `tests/contract/` Command + Event schema 全部固化
- [ ] 全量测试（`-k "not server and not postgres"`）通过
- [ ] `domain/constants.py` 包含所有魔法数字，代码中无裸数字阈值
