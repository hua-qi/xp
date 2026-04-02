# CLI 命令与 MCP 工具指南

## CLI 命令

| 命令 | 说明 |
|---|---|
| `xp add` | 交互式手动添加经验（支持中文输入） |
| `xp review` | 逐条确认/拒绝待 review 的候选经验 |
| `xp edit <ID前缀>` | 交互式编辑已有经验（标题、问题描述、解决方案、标签），归档经验可同时重新激活 |
| `xp archive <ID前缀>` | 将经验归档（不再参与检索，数据保留） |
| `xp delete <ID前缀>` | 永久删除经验（同步清除向量索引） |
| `xp import <文件>` | 从 Markdown 文件批量导入种子经验 |
| `xp stats` | 查看全部时间的效果统计 |
| `xp stats --since 7d` | 查看最近 7 天的统计 |
| `xp stats --since 30d` | 查看最近 30 天的统计 |
| `xp analyze` | 分析经验质量报告（采纳率、拒绝原因、过期经验、搜索空白、重复经验等） |
| `xp project list` | 列出所有项目 |
| `xp project switch <名>` | 切换到指定项目 |
| `xp watch` | 检查文件变更和过期经验 |
| `xp sync up/down` | 云端同步（需配置） |

## MCP Tools

| Tool | 调用时机 | 用途 |
|---|---|---|
| `search_best_practices` | **任务开始前必调** | 检索历史经验，避免重复踩坑 |
| `extract_experience` | **任务完成后必调** | 沉淀本次任务经验 |
| `record_feedback` | 任务完成后 | 反馈每条经验是否被采纳 |
| `record_session` | 任务完成后 | 记录会话效果数据 |
