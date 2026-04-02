# 5分钟快速上手

## 接入 MCP 客户端（如 Cursor、codeflicker）

在 MCP 配置文件（如 `~/.cursor/mcp.json` 或项目 `.cursor/mcp.json`）中添加：

```json
{
  "mcpServers": {
    "xp": {
      "command": "/path/to/xp/.venv/bin/python",
      "args": ["/path/to/xp/src/server.py"],
      "env": {
        "OPENAI_API_KEY": "your_key_here",
        "PYTHONPATH": "/path/to/xp"
      }
    }
  }
}
```

客户端会自动启动和停止 xp-server。

## 让 agent 使用工具

在任务前让 agent 检索经验：

> 在开始编写代码前，请先调用 search_best_practices 检索相关历史经验。

任务完成后让 agent 沉淀经验：

> 请调用 extract_experience 将本次任务的经验沉淀下来。
> 然后调用 record_session 记录本次会话数据。

## CLI 审核与统计

```bash
# 审核待定经验
xp review

# 查看统计数据
xp stats
```
