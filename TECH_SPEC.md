# Agent 最佳实践沉淀工具 - 技术方案

## 定位

面向业务工程师的基础设施工具。业务工程师无需关心向量存储、检索注入等底层细节，只需专注于经验内容的审核。

## 整体架构

```
agent 开始任何任务
        ↓
  [search_best_practices] 检索历史经验
        ↓
    [执行任务]
        ↓
  [extract_experience] 沉淀本次经验
        ↓
  [record_feedback] 反馈经验采纳情况
        ↓
  [record_session] 记录会话效果
        ↓
  [人工 review] 确认/拒绝/编辑候选经验
        ↓
   [检索引擎] ← 任务描述
        ↓
   [动态权重更新] ← 反馈数据
```

## Phase 1：先有（MVP）

目标： 打通"agent 自动提取候选 → 人工确认 → 检索注入"最小闭环，并记录核心指标供工具有效性判断

**适用范围**：XP 适用于 agent 执行任何任务时自动采用或沉淀最佳实践：
- 编写代码：bugfix、功能实现、代码模式
- 生成文档：API 文档、README、技术规范
- Debug 排查：错误定位、问题诊断
- 代码重构：重构、优化、迁移
- 配置环境：Docker、CI/CD、依赖管理
- 代码审查：Review PR/MR、代码评审
- 测试编写：单元测试、集成测试、E2E 测试
- 任何你觉得以后可能再遇到的情况

### 1.1 经验录入：agent 为主

触发时机： agent 每次完成任务后，由 MCP Server 中的 extract_experience tool 触发，让 agent 自己对刚完成的任务做总结提取。只要有任何"原来要这样"、"差点踩坑"、"找到了好方案"的收获，就应该记录。

MCP tool 定义：

```json
{
  "name": "extract_experience",
  "description": "【任务完成后必做】在完成任务后，提取本次任务中值得沉淀的经验",
  "inputSchema": {
    "task_description": "本次任务描述",
    "solution_summary": "解决方案摘要",
    "key_decisions": "关键决策或踩坑点",
    "tags": ["技术栈标签"]
  }
}
```

Agent 调用此 tool 后，系统自动：
- 用 LLM 对输入内容做结构化提取，生成标准经验条目
- 判断粒度层级（L1 模式层 / L2 场景层 / L3 修复层）
- 去重检测：与现有经验做相似度比较，相似度 > 0.9 则合并而非新增
- 写入经验库，状态为 pending

经验数据结构：

```json
{
  "id": "uuid",
  "type": "bugfix | feature | pattern",
  "level": "L1 | L2 | L3",
  "title": "简短标题",
  "tags": ["react", "hooks"],
  "problem": "问题描述",
  "solution": "解决方案（Markdown）",
  "related_files": [],
  "confidence": 0.6,
  "status": "pending | active | archived",
  "source": "agent | manual",
  "created_at": "2026-03-23",
  "metadata": {
    "tech_stack": ["react", "typescript"],
    "problem_type": "bugfix",
    "scene": ["表单", "异步"],
    "keywords": ["useEffect", "infinite loop"]
  }
}
```

说明：
- `metadata` 用于结构化检索，包含技术栈、问题类型、场景标签、关键词
- 关键词结合标签过滤实现高效检索
- `tags` 字段保留向后兼容，实际检索优先使用 `metadata.tech_stack` 和 `metadata.keywords`

### 1.2 人工 review：辅助确认

候选经验生成后，通过 CLI 进入 review 流程：

```bash
xp review        # 列出所有 pending 经验
xp review --id   # 查看单条详情
```

每条经验提供三个操作：
- 确认（y）：直接 active，confidence 初始值 0.8
- 编辑后确认（e）：修改内容后 active，confidence 初始值 1.0
- 拒绝（n）：标记为 archived，记录拒绝原因供后续优化提取质量

冷启动方案： 支持从 markdown 文件批量导入种子数据，绕过 agent 提取直接进入 pending review：

```bash
xp import ./best-practices.md
```

### 1.3 存储

- 经验数据：本地 JSON（`~/.xp/knowledge.json`）
- 检索引擎：**BGE-small-zh Embedding 向量检索**
  - 余弦相似度排序，返回 TopK
  - 检索逻辑：标签过滤 → Embedding 相似度排序 → 返回 TopK
  - 向量索引存储在 SQLite `experience_vectors` 表（binary 压缩），随经验删除同步清除
- 指标数据：本地 SQLite（`~/.xp/metrics.db`），结构简单、易于查询

### 1.4 检索 + 注入

暴露 MCP tool，agent 在生成代码前主动调用：

```json
{
  "name": "search_best_practices",
  "description": "【任务开始第一步】在执行任何任务前，根据当前任务描述检索历史最佳实践",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "任务描述或报错信息"
      },
      "tags": {
        "type": "array",
        "items": {"type": "string"},
        "description": "技术栈标签，用于过滤（可选）"
      },
      "top_k": {
        "type": "integer",
        "description": "返回条数，默认 3",
        "default": 3
      }
    },
    "required": ["query"]
  }
}
```

检索逻辑：
1. **标签过滤**：按 `metadata.tech_stack`、`metadata.problem_type`、`metadata.scene` 精确匹配
2. **Embedding 排序**：对 `title + problem + key_decisions` 计算余弦相似度打分
3. **返回结果**：附带 `similarity` 和相关元数据，供 agent 参考

检索返回结果时附带 `experience_id`，供 `record_session` 记录使用效果。

### 1.5 MVP 指标体系

设计原则： 指标分两类——过程指标（工具在用吗）和效果指标（用了有没有变好）。MVP 阶段优先收集原始数据，不做复杂计算。

#### 过程指标（工具运转是否正常）

每次 MCP tool 调用时自动记录，无需额外操作：

| 指标 | 说明 | 记录时机 |
|------|------|----------|
| 检索命中率 | 有结果返回 vs 无结果返回的比例 | search_best_practices 调用时 |
| 经验库增长曲线 | 每天新增 active 经验数 | xp review 确认时 |
| 候选经验通过率 | confirmed / (confirmed + rejected) | xp review 操作时 |
| 检索触发频次 | agent 每天调用检索的次数 | search_best_practices 调用时 |

#### 效果指标（工具是否真的有用）

需要 agent 在任务完成后配合上报，通过 record_session MCP tool 记录：

```json
{
  "name": "record_session",
  "description": "记录一次完整的会话数据，用于效果评估",
  "inputSchema": {
    "session_id": "string",
    "task_description": "任务描述",
    "experience_ids_injected": ["检索到并参考的经验 id 列表，无则为空数组"],
    "iteration_count": "完成任务的对话轮数",
    "had_error_correction": "过程中是否出现报错并修正（boolean）",
    "user_accepted": "用户最终是否接受了结果（boolean）"
  }
}
```

基于 session 数据，可计算以下对比指标（有经验注入 vs 无注入）：

| 指标 | 计算方式 | 衡量什么 |
|------|----------|----------|
| 平均对话轮数 | 按有无经验注入分组，对比 iteration_count 均值 | 是否减少了来回修改 |
| 报错率 | 按有无经验注入分组，对比 had_error_correction 比例 | 是否减少了踩坑 |
| 用户接受率 | user_accepted = true 的比例，按有无注入分组 | 生成质量是否提升 |

#### 反馈指标（经验质量）

通过 record_feedback MCP tool 收集每条经验的实际使用效果：

```json
{
  "name": "record_feedback",
  "description": "记录检索到的经验是否被采纳",
  "inputSchema": {
    "experience_id": "string",
    "adopted": "boolean",
    "reason": "未采纳原因（可选）"
  }
}
```

基于反馈数据计算的指标：

| 指标 | 说明 | 用途 |
|------|------|------|
| 经验采纳率 | adopted_count / hit_count | 判断经验是否相关 |
| 低采纳率经验数 | 采纳率 < 30% 的经验数 | 识别需要归档的经验 |
| 拒绝原因分布 | 统计未采纳的原因 | 优化提取质量 |

---

### 1.6 Phase 1 交付物

- extract_experience MCP tool（agent 自动提取入口）
- search_best_practices MCP tool（检索入口）
- record_session MCP tool（效果数据采集）
- record_feedback MCP tool（反馈数据采集）
- xp review CLI（人工确认）
- xp import CLI（冷启动导入）
- xp add CLI（交互式手动添加）
- xp edit CLI（交互式编辑已有经验）
- xp archive CLI（归档经验，停止参与检索）
- xp delete CLI（永久删除经验，同步清除向量索引）
- xp stats CLI（指标查看）
- xp analyze CLI（经验质量报告，含 7 类 pattern 检测与内联操作命令）
- 本地 Embedding 向量检索 + SQLite 指标库

验证标准： 积累 30 次以上 session 后，xp stats 能输出有经验注入 vs 无注入的效果对比数据。

## Phase 2：质量飞轮

目标： 让库越用越好，减少人工 review 负担

### 2.1 反馈采集

在 MCP Server 增加 feedback tool，agent 完成任务后自动调用：

```json
{
  "name": "record_feedback",
  "description": "记录检索到的经验是否被采纳",
  "inputSchema": {
    "experience_id": "string",
    "adopted": "boolean",
    "reason": "可选，未采纳原因"
  }
}
```

### 2.2 动态权重

根据采纳率动态调整 confidence：

```
新 confidence = 旧 confidence × 0.9 + 采纳率 × 0.1
```

- confidence < 0.3：降级为"仅供参考"，注入时降低权重
- confidence < 0.1：自动归档

反向优化提取质量： 被拒绝的候选经验（review 阶段 n）和低采纳率经验，统一分析拒绝原因，定期优化 extract_experience 的提取 prompt。

### 2.3 提取质量自动优化

周期性（如每周）对拒绝记录做聚类分析，找出 agent 提取经验时的系统性偏差，输出优化建议供人工调整提取 prompt。

```bash
xp analyze  # 输出经验质量报告：提取率、采纳率、低质量模式
```

`xp analyze` 识别的低质量模式（共 7 类）：

| pattern | 触发条件 | 内联操作命令 |
|---------|----------|-------------|
| `extraction_quality` | 整体采纳率 < 50% | 无（建议优化提取 prompt） |
| `low_adoption` | 存在采纳率 < 30% 的经验 | `xp archive <id>` / `xp edit <id>` |
| `reject_pattern` | 存在常见拒绝原因 | 无（建议优化提取逻辑） |
| `staleness` | Active 经验超过 90 天未被检索命中 | `xp archive <id>` |
| `search_miss` | 近 30 天有 query 返回 0 结果 | `xp add` |
| `duplicate_cluster` | 经验间余弦相似度 >= 0.92 | `xp delete <id>` |
| `coverage_gap` | 高频搜索词在知识库中无对应经验 | `xp add` |

报告末尾汇总所有可执行命令，可直接复制粘贴到终端执行。

### 2.4 人工 review 减负

高置信场景下，允许跳过人工 review 直接 active：
- agent 提取 + 相似历史经验采纳率 > 0.8 → 自动 active（confidence 初始 0.6）
- 仍保留人工随时可归档的权限

### 2.5 Phase 2 交付物

- 反馈采集 MCP tool
- confidence 动态更新机制
- xp analyze 质量报告 CLI
- 高置信自动 active 策略

## Phase 3：时效性 + 多项目

目标： 解决经验腐化，支持团队协作

### 3.1 经验失效检测

每条经验关联相关文件 hash，xp watch 监听文件变更：

```json
{
  "related_files": ["src/utils/request.ts"],
  "file_hash_at_creation": "abc123"
}
```

相关文件结构变化时，自动标记为 stale 并通知工程师复核。TTL：90 天未命中自动归档。

### 3.2 云端同步 + 团队共享

存储迁移至云端数据库（如 Supabase、Weaviate Cloud、Elasticsearch Cloud），团队共享同一知识库：

```
本地 xp CLI ←→ 云端知识库 API
```

选型建议：
- **Supabase (PostgreSQL)**：低成本，适合小团队，可用传统 SQL 查询
- **Weaviate Cloud**：原生支持 BM25 + 向量混合检索，适合需要语义搜索的场景
- **Elasticsearch Cloud**：全文检索强大，生态成熟

权限设计：
- 任何人可检索
- agent 提取的候选经验自动进入团队 pending 队列
- 团队任一成员可 review 确认

### 3.3 多项目隔离

```bash
xp init --project "mobile-app" --tags "react-native,typescript"
```

检索时优先匹配当前项目，无结果时可选择跨项目检索。

### 3.4 Phase 3 交付物

- 文件变更监听 + 失效标记
- 云端存储 + 同步 CLI
- 团队协作权限管理
- 多项目隔离支持

## 技术选型建议

| 模块 | Phase 1 | Phase 2/3 |
|------|---------|-----------| 
| 存储 | 本地 JSON | 云端数据库（Supabase / Weaviate / ES） |
| 检索引擎 | Embedding 向量检索 | 同左 |
| Embedding | BGE-small-zh（本地推理） | 同左 |
| 指标存储 | 本地 SQLite（含向量索引） | 云端（随知识库一起迁移） |
| 入口 | MCP Server + CLI | 同左 |
| 语言 | Python | 同左 |

### 云端 Provider 配置

#### Supabase (PostgreSQL)
```bash
# 环境变量
XP_SUPABASE_URL=https://your-project.supabase.co
XP_SUPABASE_KEY=your-service-key

# 或使用 xp init
xp init --project "myapp" --cloud-provider supabase --cloud-url "..." --cloud-key "..."
```

#### Weaviate Cloud
```bash
XP_WEAVIATE_URL=https://your-cluster.weaviate.network
XP_WEAVIATE_API_KEY=your-api-key
```

#### Elasticsearch
```bash
XP_ES_HOST=https://your-cluster.es.io
XP_ES_API_KEY=your-api-key
# 或用户名/密码
XP_ES_USERNAME=elastic
XP_ES_PASSWORD=your-password
```

### 自定义存储目录

```bash
# 环境变量
XP_HOME=/path/to/custom/dir xp review
```

## 关键设计原则

- **agent 提取，人工把关** - agent 负责生产候选经验，人工只做最终质量门控
- **注入是建议不是指令** - 经验注入 agent 时，措辞为"历史经验供参考"，避免误导
- **拒绝也是数据** - 每次 review 拒绝都是对提取质量的反馈，形成优化闭环
- **指标先行** - MVP 阶段就收集原始数据，用数据而非感觉判断工具价值
- **可观测** - 每条经验的命中次数、采纳率、最后使用时间，全部可查
