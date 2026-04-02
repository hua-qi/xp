# XP (Experience Processor) - Agent 最佳实践沉淀工具

让 agent 在任何任务中越用越聪明：自动沉淀每次任务的经验，下次遇到相似问题时直接复用。

## 核心特性
- **自动沉淀**：任务完成后自动提取和总结最佳实践
- **智能检索**：基于本地向量搜索，任务开始前自动匹配相关经验
- **人工审核**：通过命令行快速 review 机器总结的经验，保证质量
- **效果追踪**：统计工具使用效果，量化研发效能提升

## 快速开始

```bash
git clone <repo> xp
cd xp
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e .
xp --help
```

详细接入与使用请参考 [5分钟快速上手](QUICK_START.md)。

## 文档索引

- [QUICK_START.md](QUICK_START.md): 安装与快速上手指南
- [CHANGELOG.md](CHANGELOG.md): 版本变更记录
- [docs/](docs/):
  - [guides/user/cli-guide.md](docs/guides/user/cli-guide.md): CLI 命令与 MCP 工具完整参考
  - [guides/dev/DOC_GUIDELINES.md](docs/guides/dev/DOC_GUIDELINES.md): 开发者文档规范
  - [guides/dev/code-standards.md](docs/guides/dev/code-standards.md): 代码规范
  - [guides/dev/test-acceptance.md](docs/guides/dev/test-acceptance.md): 测试验收规范
  - [features/](docs/features/): 各功能模块设计实现
