# XP 项目整体规范

> 版本：v1.0 · 日期：2026-02-04

---

## 一、项目简介

XP 是一个知识/经验管理系统，核心功能：
- **经验沉淀**：从 Agent 任务输出中提取可复用的开发经验
- **语义召回**：通过向量搜索为 Agent 提供相关经验
- **持续改进**：通过反馈机制不断提升经验质量

---

## 二、目录结构规范

```
xp/
├── src/
│   ├── domain/                  # 纯业务逻辑，零 I/O，100% 可单元测试
│   │   ├── models.py            # Experience、Project 等核心 dataclass
│   │   ├── events.py            # 所有领域事件定义（模块间契约）
│   │   ├── constants.py         # 所有业务阈值常量
│   │   ├── experience.py        # 提取、激活、归档决策
│   │   ├── search.py            # 搜索排序、A/B 策略
│   │   ├── feedback.py          # 置信度更新规则
│   │   ├── quality.py           # 质量评分规则
│   │   └── metadata.py          # tech_stack / scene / level 推断
│   │
│   ├── application/             # 编排层：协调 domain + 基础设施
│   │   ├── commands.py          # Command 对象（用例入口定义）
│   │   ├── command_bus.py       # Command → Handler 分发器
│   │   ├── unit_of_work.py      # 三存储统一提交/回滚
│   │   └── handlers/            # 每个用例一个 Handler
│   │       ├── experience_handler.py
│   │       ├── search_handler.py
│   │       ├── feedback_handler.py
│   │       ├── analytics_handler.py
│   │       └── project_handler.py
│   │
│   ├── infrastructure/          # 所有 I/O 实现（存储、LLM、外部服务）
│   │   ├── stores/
│   │   │   ├── experience_store.py   # JSON 文件实现
│   │   │   ├── vector_store.py       # 二进制 embedding 实现
│   │   │   └── metrics_store.py      # SQLite 实现
│   │   ├── llm.py               # LLM 调用封装（OpenAI 等）
│   │   └── backends/            # 可插拔存储后端
│   │       ├── base.py          # 抽象接口
│   │       ├── local.py         # 本地文件后端
│   │       └── postgres.py      # PostgreSQL 后端
│   │
│   ├── interfaces/              # 对外入口，只做参数转换，不含业务逻辑
│   │   ├── cli.py               # 命令行接口
│   │   ├── rest_api.py          # FastAPI REST 接口
│   │   └── mcp_server.py        # MCP 协议接口
│   │
│   └── container.py             # 依赖组装（DI 入口，全局唯一）
│
├── tests/
│   ├── unit/                    # 单元测试：零 I/O，零 mock（domain 层）
│   ├── integration/             # 集成测试：InMemory 存储，跑完整流程
│   ├── contract/                # 契约测试：Command schema、事件 schema
│   └── characterization/        # 特征测试：固化现有行为防回归
│
└── docs/
    ├── designs/                 # 设计文档（重大变更必须先写设计文档）
    ├── plans/                   # 实施计划
    └── specs/                   # 规范文档（本文件所在目录）
```

### 目录规范要点

| 规则 | 说明 |
|------|------|
| `domain/` 禁止 import `infrastructure/` | 保证领域逻辑可独立测试 |
| `domain/` 禁止 import `application/` | 领域层不知道编排层存在 |
| `application/` 禁止直接 import `infrastructure/` 具体类 | 只能通过注入的接口使用 |
| `interfaces/` 只能调用 `CommandBus.dispatch()` | 不允许直接调用 Handler 或 domain 函数 |
| 新增用例必须先在 `commands.py` 定义 Command | Command 是用例的唯一入口 |

---

## 三、代码规范

### 3.1 Python 版本与工具

- Python **3.9+**（使用 `list[str]` 而非 `List[str]`，`str | None` 而非 `Optional[str]`）
- 格式化：`black`（行宽 88）
- 类型检查：`mypy --strict`
- Lint：`ruff`
- 测试：`pytest`

### 3.2 导入规范

```python
# src/ 内部一律使用相对导入
from ..domain.models import Experience        # ✅
from src.domain.models import Experience      # ❌

# 标准库 → 第三方库 → 内部模块，空行分隔
import os
import json

import openai

from ..domain.models import Experience
from ..domain.events import ExperienceCreated
```

### 3.3 领域模型规范

```python
# models.py 中的实体用 frozen=False dataclass（需要状态变更）
# events.py 中的事件用 frozen=True dataclass（事件不可变）

@dataclass(frozen=True)
class ExperienceCreated:
    experience_id: str
    quality_score: int

@dataclass
class Experience:
    id: str
    status: Literal["PENDING", "ACTIVE", "ARCHIVED"]
    # 状态变更只能通过方法，不允许外部直接赋值 .status = ...
    def activate(self) -> list:
        ...
```

### 3.4 Handler 规范

- 每个 Handler 文件不超过 **150 行**
- Handler 只能通过构造函数注入依赖，不允许在方法内实例化任何 I/O 对象
- Handler 方法必须接收 Command 对象，返回结果或事件列表

```python
class ExperienceHandler:
    def __init__(self, uow_factory, llm, metadata_inferrer):  # 注入
        ...

    def handle_create(self, cmd: CreateExperienceCommand):
        with self._uow_factory() as uow:
            ...
        return result
```

### 3.5 Unit of Work 规范

- 每个请求/命令创建一个新的 UoW 实例（不复用）
- 使用 `with` 语句，异常自动回滚
- 事件在 `commit()` 成功后才分发，不允许在 commit 前发布副作用

```python
# ✅ 正确用法
with uow_factory() as uow:
    uow.experiences.add(exp)
    uow.collect_event(ExperienceCreated(...))

# ❌ 错误用法
uow = UnitOfWork()
uow.experiences.add(exp)
uow.commit()             # 忘记处理异常
```

### 3.6 事件规范

- 事件命名：**过去式**，`ExperienceCreated` 而非 `CreateExperience`
- 事件字段：只包含**已知事实**，不含推断或衍生数据
- 新增事件必须同步更新 `events.py` 并补充契约测试

### 3.7 错误处理规范

```python
# domain 层：抛出领域异常（继承自 DomainError）
class DuplicateExperienceError(DomainError):
    def __init__(self, existing_id: str, similarity: float): ...

# application 层：捕获领域异常，转换为 Command 结果
# interfaces 层：捕获所有异常，转换为 HTTP 状态码或 CLI 错误消息

# 禁止在 domain 层静默捕获异常
try:
    ...
except Exception:
    pass    # ❌ 绝对禁止
```

### 3.8 魔法数字规范

所有业务阈值统一定义在 `domain/constants.py`：

```python
QUALITY_SCORE_AUTO_ACTIVATE = 80
DUPLICATE_SIMILARITY_THRESHOLD = 0.85
EXPERIENCE_TTL_DAYS = 90
SEARCH_DEFAULT_LIMIT = 10
CONFIDENCE_HELPFUL_DELTA = 0.1
CONFIDENCE_UNHELPFUL_DELTA = -0.05
```

---

## 四、测试规范

### 4.1 测试分层

| 层级 | 位置 | 特征 | 速度 |
|------|------|------|------|
| 单元测试 | `tests/unit/` | 零 I/O，零 mock，只测 domain 纯函数 | < 1ms/个 |
| 集成测试 | `tests/integration/` | InMemory 存储，跑完整 Handler 流程 | < 100ms/个 |
| 契约测试 | `tests/contract/` | 固化 Command/Event schema | < 10ms/个 |
| 特征测试 | `tests/characterization/` | 固化现有外部行为，防回归 | 允许较慢 |

### 4.2 测试命名规范

```python
# 格式：test_<场景>_<期望结果>
def test_high_quality_experience_auto_activates(): ...
def test_duplicate_experience_raises_error(): ...
def test_rollback_on_vector_store_failure(): ...
```

### 4.3 运行命令

```bash
# 全量（跳过需要外部服务的测试）
python3 -m pytest tests/ -q -k "not server and not postgres"

# 只跑单元测试（TDD 开发时使用）
python3 -m pytest tests/unit/ -q

# 只跑集成测试
python3 -m pytest tests/integration/ -q
```

---

## 五、Git 规范

### Commit 格式

```
<type>: <description>

type:
  feat     新功能
  fix      Bug 修复
  refactor 重构（不改变外部行为）
  test     新增或修改测试
  docs     文档变更
  chore    构建/工具链变更
```

### 分支规范

- `main`：始终保持可运行，全量测试绿
- `feat/<name>`：新功能
- `refactor/<name>`：重构（每个阶段一个分支）

### 重构阶段分支命名

```
refactor/phase1-skeleton
refactor/phase2-domain-logic
refactor/phase3-unit-of-work
refactor/phase4-command-bus
refactor/phase5-delete-god-object
```
