# CLI 命令与 MCP 工具指南

## 快速开始

### 登录

```bash
xp login
```

输入管理员提供的 token，系统会自动验证并保存 `token`、`edge_function_url` 到 `~/.xp/config.json`。

> **注意**：v2 起不再需要 `DATABASE_URL`。本地 xp-server 完全无状态，只持有 token，所有业务逻辑运行在 Supabase Edge Function。

## CLI 命令

### 经验管理

| 命令 | 说明 |
|---|---|
| `xp add` | 交互式手动添加经验（支持中文输入） |
| `xp review` | 逐条确认/拒绝待 review 的候选经验 |
| `xp edit <ID前缀>` | 交互式编辑已有经验，归档经验可同时重新激活 |
| `xp archive <ID前缀>` | 将经验归档（不再参与检索，数据保留） |
| `xp delete <ID前缀>` | 永久删除经验（同步清除向量索引） |
| `xp import <文件>` | 从 Markdown 文件批量导入种子经验 |

### 统计与分析

| 命令 | 说明 |
|---|---|
| `xp stats` | 查看全部时间的效果统计（含健康状态面板） |
| `xp stats --since 7d` | 查看最近 7 天的统计 |
| `xp stats --since 30d` | 查看最近 30 天的统计 |
| `xp stats --project <id>` | 按项目过滤统计 |
| `xp stats --business <id>` | 按业务线过滤统计 |
| `xp stats --team <id>` | 按团队过滤统计 |
| `xp stats --compare` | 展示层级间对比数据 |
| `xp analyze` | 分析经验质量报告（采纳率、拒绝原因、过期经验等） |

#### 健康状态面板

`xp stats` 末尾固定展示知识库健康状态，包含：

| 指标 | 健康阈值 |
|------|---------|
| 采纳率 | > 60% |
| 未命中率 | < 20% |
| Pending 堆积 | < 20 条 |
| 反馈覆盖率 | > 40% |

### 升层管理

| 命令 | 说明 |
|---|---|
| `xp promote list` | 查看当前升层候选列表（含评分和理由） |
| `xp promote <id> --to business <biz-id>` | 将经验提升至 Business 层 |
| `xp promote <id> --to team <team-id>` | 将经验提升至 Team 层 |
| `xp promote ignore <id>` | 忽略该候选（30 天后可重新评估） |

### 项目管理

| 命令 | 说明 |
|---|---|
| `xp project list` | 列出所有项目 |
| `xp project switch <名>` | 切换到指定项目 |

### 其他

| 命令 | 说明 |
|---|---|
| `xp watch` | 检查文件变更和过期经验 |
| `xp login` | 登录，保存 token 到本地 config |

## Admin 命令（管理员专用）

> 需要设置 `DATABASE_URL` 环境变量（直连 Supabase PostgreSQL）。

| 命令 | 说明 |
|---|---|
| `xp admin create-token` | 为用户生成访问 token |
| `xp admin create-team` | 创建团队（交互式输入名称、owner 邮箱） |
| `xp admin create-business` | 创建业务线（交互式输入名称、owner 邮箱） |
| `xp admin link` | 查看关联命令用法（project ↔ business，business ↔ team） |

## MCP Tools

xp v2 精简为 3 个 MCP tool，覆盖完整工作流：

| Tool | 调用时机 | 用途 |
|---|---|---|
| `search` | **任务开始前必调** | 从知识库召回相关历史经验，返回 `search_event_id` |
| `save` | **任务完成后必调** | 将本次经验沉淀到知识库，传入 `search_event_id` 关联 |
| `feedback` | search 有结果且经验有帮助时 | 反馈哪些经验有用/无用，优化知识库质量 |

### 调用时序

```
任务开始 → search（获取 search_event_id）
任务完成 → save（传入 search_event_id）
         → feedback（如果经验有帮助，传入 helpful_ids）
```

所有请求由本地 xp-server 携带 token 转发至 Supabase Edge Function，本地无数据库依赖。
