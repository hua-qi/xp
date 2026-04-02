# 文档编写规范

本规范用于指导 agent 和开发者在编写、更新文档时保持一致性。

---

## 一、文档目录结构

```
xp/
├── README.md                        # 项目首页，面向所有人，保持简洁
├── QUICK_START.md                   # 5分钟快速上手
├── CHANGELOG.md                     # 版本变更记录
│
├── docs/
│   ├── design/                      # 顶层产品与技术设计文档（宏观系统说明）
│   │   ├── adr/                     # 架构决策记录 (ADR)
│   ├── designs/                     # 历史特性设计草稿（带日期前缀，保留用于对比总结）
│   ├── features/                    # 各个功能模块的设计定稿
│   ├── guides/                      # 指南类文档
│   │   ├── user/                    # 面向使用者的指南
│   │   │   └── cli-guide.md         # CLI 命令完整参考
│   │   └── dev/                     # 面向开发者的指南
│   │       ├── DOC_GUIDELINES.md    # 本文件，项目文档组织与编写规范
│   │       ├── code-standards.md    # 代码及目录规范
│   │       └── test-acceptance.md   # 测试验收规范
│   └── plans/                       # 项目开发、测试与实施计划
│       ├── 2026-*.md                # 各阶段计划
│       └── ops/                     # 运维与工程落地文档
```

---

## 二、何时需要更新文档

| 改动类型 | 必须更新 | 建议更新 |
|---------|---------|---------|
| 修复 bug | `CHANGELOG.md` | 相关功能文档（如果 bug 涉及文档描述有误） |
| 新增小功能 | `CHANGELOG.md` | `docs/guides/` 中对应的使用说明 |
| 新增大功能（影响架构） | `CHANGELOG.md` + `docs/features/` 下新建文档 | `docs/design/ARCHITECTURE.md` |
| 涉及架构决策 | `docs/design/adr/ADR-xxx.md` | `docs/design/ARCHITECTURE.md` |
| 修改 CLI 命令 | `CHANGELOG.md` + `docs/guides/user/cli-guide.md` | `README.md`（如果是核心命令） |
| 数据迁移 | `docs/ops/migration-*.md` | `CHANGELOG.md` |

---

## 三、各类文档的写法规范

### 3.1 CHANGELOG.md

遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 格式：

```markdown
## [版本号] - YYYY-MM-DD

### Added
- 新增了 XXX 功能

### Changed
- 修改了 XXX 行为

### Fixed
- 修复了 XXX bug

### Removed
- 移除了 XXX
```

**规则：**
- 每次 bug fix 或 feature 合并后必须在 `[Unreleased]` 下追加一条
- 发布版本时将 `[Unreleased]` 重命名为对应版本号
- 描述要简洁，一句话说清楚做了什么，不需要写原因

### 3.2 功能模块文档（docs/features/）

每个功能模块文档应包含：

```markdown
# 功能名称

## 概述
一句话说明这个功能是什么、解决什么问题。

## 设计思路
为什么这样设计，核心思路是什么。

## 实现细节
关键实现代码或流程图。

## 接口与使用
如何调用，入参出参说明。

## 相关文件
- `src/domain/experience.py` - 说明
```

### 3.3 架构决策记录（docs/design/adr/ADR-xxx.md）

适用于：技术选型、架构重大变更、废弃旧方案等。

```markdown
# ADR-XXX: 决策标题

**状态**: 已采纳 / 已废弃 / 待定  
**日期**: YYYY-MM-DD

## 背景
为什么需要做这个决策。

## 决策
最终选择了什么方案。

## 备选方案
考虑过哪些方案，为什么没选。

## 结果
这个决策带来了哪些影响。
```

### 3.4 README.md

**只放面向新用户的内容：**
- 项目是什么（1-2 句话）
- 核心特性（表格，最多 7 条）
- 快速开始（3 步以内）
- 常用命令（不超过 10 条）
- 文档索引（链接到各子文档）

不要放：详细命令说明、架构细节、实现代码——这些放到对应子文档中。

---

## 四、文档命名约定

| 位置 | 命名规则 | 示例 |
|------|---------|------|
| 根目录 | 全大写，下划线 | `README.md`, `CHANGELOG.md` |
| docs/design/ | 全大写，下划线 | `ARCHITECTURE.md`, `TECH_SPEC.md` |
| docs/features/ | 小写，连字符 | `pattern-learning.md` |
| docs/guides/ | 小写，连字符 | `cli-guide.md` |
| docs/ops/ | 小写，连字符 | `migration-v2.md` |
| docs/design/adr/ | `ADR-NNN-短标题.md` | `ADR-002-langgraph-adoption.md` |

---

## 五、文档版本信息

每个文档底部可选添加：

```markdown
---
**文档版本**: v1.0  
**最后更新**: YYYY-MM-DD  
```

`design/` 和 `features/` 下的文档建议加，`CHANGELOG.md` 和 `guides/` 不需要。

---

## 六、agent 编写文档时的检查清单

在编写或更新文档前，请确认：

- [ ] 这个改动属于哪种类型（bug fix / 小功能 / 大功能 / 架构决策）？
- [ ] 是否需要更新 `CHANGELOG.md`？
- [ ] 文档放在正确的目录下了吗（参考第一节的目录结构）？
- [ ] 文档命名遵循了第四节的约定吗？
- [ ] 如果修改了 CLI 命令，`docs/guides/user/cli-guide.md` 是否同步更新了？
- [ ] 如果涉及架构变化，`docs/design/ARCHITECTURE.md` 是否需要更新？
