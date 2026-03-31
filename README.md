# XP - Agent 最佳实践沉淀工具

让 agent 在任何任务中越用越聪明：自动沉淀每次任务的经验，下次遇到相似问题时直接复用。

适用场景：**编写代码、生成文档、Debug 排查、代码重构、配置环境、代码审查、测试编写等任何通过 agent 完成的任务**。

---

## 工作原理

```
agent 开始任何任务
      ↓
调用 search_best_practices → 检索历史经验（零成本，高回报）
      ↓
    [执行任务]
      ↓
调用 extract_experience → 沉淀本次经验（哪怕很小也值得）
      ↓
调用 record_feedback → 反馈每条经验是否有帮助
      ↓
调用 record_session → 记录会话效果数据
      ↓
你运行 xp review → 确认/拒绝候选经验
      ↓
xp stats → 查看工具是否真的有用
```

---

## 安装

**前置要求：** Python 3.11+，uv 或 pip

```bash
cd xp

# 复制环境变量
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY

# 创建虚拟环境（如尚未创建）
python -m venv .venv

# 激活虚拟环境
source .venv/bin/activate  # macOS/Linux
# 或: .venv\Scripts\activate  # Windows

# 安装依赖
pip install -e .
```

验证安装：

```bash
xp
# 应输出命令帮助
```

**注意**：使用 `xp` 命令前需要先激活虚拟环境，或使用完整路径 `.venv/bin/xp`。

---

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

**配置说明：**
- `command`: 使用虚拟环境中的 Python 解释器（必须写完整路径）
- `args`: 指向 `src/server.py` 启动 MCP 服务器
- `env.PYTHONPATH`: 确保能正确导入项目模块

**客户端会自动启动和停止 xp-server**，无需手动运行。

重启 MCP 客户端，在工具面板中确认 `xp` 服务已连接。

---

## 快速上手：5 步验证工具效果

### Step 1：冷启动 - 导入种子经验

如果你有现成的最佳实践文档，可以直接导入。按以下格式准备一个 Markdown 文件：

```markdown
# useEffect 依赖项遗漏导致无限循环

**问题**
在 useEffect 中使用了外部变量但未加入依赖项数组，导致每次渲染都重新执行。

**解决方案**
使用 eslint-plugin-react-hooks 的 exhaustive-deps 规则，或手动检查所有外部引用。
useCallback/useMemo 包裹函数类型的依赖，避免引用变化触发重新执行。

**标签**: react, hooks, useEffect

---

# async/await 在 useEffect 中的正确用法

**问题**
直接将 useEffect 的回调设为 async 函数会导致返回 Promise，而 useEffect 期望返回 cleanup 函数或 undefined。

**解决方案**
在 useEffect 内部定义并立即调用 async 函数：
```js
useEffect(() => {
  const fetchData = async () => { ... };
  fetchData();
}, []);
```

**标签**: react, hooks, async
```

```bash
xp import ./my-practices.md
```

### Step 2：review 导入的经验

```bash
xp review
```

每条经验会显示详情，按提示操作：
- `y` → 确认，加入知识库
- `n` → 拒绝（可填写原因）
- `s` → 跳过，留待下次
- `q` → 退出

### Step 3：让 agent 在任务前检索

在 Cursor 中开始一个新任务，在 system prompt 或任务开头加入：

> 在开始编写代码前，请先调用 `search_best_practices` 检索相关历史经验。

或者直接在对话中说：

> 帮我实现一个带防抖的搜索框，先检索一下有没有相关的历史经验。

agent 会自动调用 MCP tool，返回类似：

```json
[
  {
    "title": "useEffect 依赖项遗漏导致无限循环",
    "similarity": 0.72,
    "solution": "...",
    "note": "以上为历史经验，仅供参考，请结合当前实际情况判断是否适用。"
  }
]
```

### Step 4：让 agent 在任务后提取经验

任务完成后，在对话中说：

> 请调用 `extract_experience` 将本次任务的经验沉淀下来。

agent 会自动提取并生成候选经验（pending），再次运行 `xp review` 确认。

同时让 agent 记录本次会话数据：

> 请调用 `record_session` 记录本次会话，session_id 用 "session-001"，本次对话了 4 轮，没有报错，用户接受了代码。

### Step 5：查看效果数据

积累几次任务后：

```bash
xp stats
```

输出示例：

```
==================================================
  XP 效果统计 (全部时间)
==================================================

--- 知识库状态 ---
  Active 经验数:     8
  Pending 待 review: 2

--- 过程指标 ---
  检索触发次数:   15
  检索命中率:     73.3%
  候选确认数:     8
  候选拒绝数:     3
  候选通过率:     72.7%

--- 效果对比 (共 15 次会话) ---
                    有经验注入    无注入
  平均对话轮数      3.2           5.7
  报错率            18.0          41.0%
  用户接受率        84.0          67.0%
```

**判断标准：**
- 有注入时平均轮数 < 无注入 → 工具在提速
- 有注入时报错率 < 无注入 → 工具在减少踩坑
- 检索命中率 < 30% → 知识库经验太少，需要继续沉淀

---

## CLI 命令参考

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

---

## MCP Tools 参考

| Tool | 调用时机 | 用途 |
|---|---|---|
| `search_best_practices` | **任务开始前必调** | 检索历史经验，避免重复踩坑 |
| `extract_experience` | **任务完成后必调** | 沉淀本次任务经验 |
| `record_feedback` | 任务完成后 | 反馈每条经验是否被采纳 |
| `record_session` | 任务完成后 | 记录会话效果数据 |

**工作流程：**
1. 任务开始 → `search_best_practices`（先查后做）
2. 任务完成 → `extract_experience`（沉淀经验）
3. 任务完成 → `record_feedback`（反馈采纳情况）
4. 任务完成 → `record_session`（记录效果）

---

## 数据存储位置

所有数据存储在本地 `~/.xp/` 目录：

```
~/.xp/
  knowledge.json    # 经验库
  metrics.db        # SQLite 指标库（含检索事件、向量索引、审核事件、会话记录、反馈记录）
```

经验检索采用 **BM25 + BGE-small-zh Embedding 混合检索**（BM25 权重 70%，Embedding 权重 30%）。向量索引存储在 `metrics.db` 的 `experience_vectors` 表中，删除经验时会同步清除对应向量。

---

## Markdown 导入格式

每条经验用 `---` 分隔，格式如下：

```markdown
# 经验标题

**问题**
问题描述...

**解决方案**
解决方案内容...

**标签**: tag1, tag2, tag3

---

# 下一条经验标题
...
```

`**标签**` 行是可选的，其他字段均必填。
