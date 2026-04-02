# 贡献指南

欢迎参与 XP (eXPerience) 知识库管理工具的开发！

我们采用 **TDD (测试驱动开发)** 和 **DDD (领域驱动设计)** 方法进行迭代。在提交 PR 之前，请务必阅读本指南及项目的规范文档。

## 核心规范阅读

开始开发前，请仔细阅读：
- [项目代码规范 (`docs/specs/project-conventions.md`)](docs/specs/project-conventions.md)：包含目录结构、代码风格、依赖注入等要求。
- [测试验收标准 (`docs/specs/test-acceptance.md`)](docs/specs/test-acceptance.md)：包含四层测试分离原则、禁止 Mock 的规定等。

## 环境准备

本项目要求 **Python 3.9+**。

```bash
# 1. 克隆代码
git clone https://github.com/your-org/xp.git
cd xp

# 2. 安装依赖（含开发依赖）
pip install -e ".[dev]"

# 3. 运行全量测试，确保环境正常
python -m pytest tests/ -v
```

## 开发工作流

1. **选择任务**：参考项目的计划文档（位于 `docs/plans/`），或从 Issue 列表中认领任务。
2. **创建分支**：基于 `main` 分支创建功能分支（命名规范：`feat/xxx`, `fix/xxx`, `refactor/xxx`）。
3. **编写测试**：遵循 TDD 原则，先在 `tests/` 中编写失败的测试用例。**注意：禁止在单元测试中使用 mock，请使用 FakeProvider 或 InMemoryUoW**。
4. **实现代码**：编写业务代码使测试通过。
5. **代码验证**：
   ```bash
   # 运行所有测试（过滤掉需要外部依赖的测试）
   python -m pytest tests/ -q -k "not server and not postgres"
   
   # 检查类型和风格（推荐）
   ruff check src/ tests/
   ```
6. **提交变更**：使用标准的 Conventional Commits 格式（如 `feat: add xxx`, `fix: xxx`, `refactor: xxx`）。

## 提交 Pull Request

1. 确保你的代码通过了所有测试。
2. 如果你的 PR 引入了新功能，请确保相应的集成测试或端到端测试已添加。
3. 描述你解决的问题或实现的特性，并关联对应的 Issue 或 Plan 文档。
4. 等待 Code Review 并根据反馈进行修改。

感谢你让 XP 变得更好！
