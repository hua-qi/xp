# 经验沉淀质量优化

**Date:** 2026-03-31

## Context

当前 `extract_experience` 存在四个问题，导致知识库信噪比低、检索精度差：

1. **title 质量差**：直接截断 task_description 前 60 字，不是真正的标题
2. **没有写入去重**：重复经验不断积累，检索时返回大量相似内容
3. **没有质量门槛**：任何调用都写入，包括一次性、不值得复用的任务
4. **key_decisions 价值丢失**：被拼接进 solution 字段，无法单独利用

## 向量化匹配问题

当前检索把 `title + problem + solution` 整体向量化，solution 内容会干扰匹配精度。两条问题不同的经验，若解决方案用了相同技术，余弦相似度会被拉高，产生误命中。

## Approach

### 1. LLM 生成 title

`extract_experience` 时调用一次 LLM（轻量 prompt），从 task_description 生成 10-15 字的标题。

```python
prompt = f"用10-15个字总结以下任务，只输出标题，不加标点：\n{task_description}"
```

失败时降级为现有截断逻辑，不阻断主流程。

### 2. 写入时去重

存入前先用 `title + problem` 向量检索知识库，若已有经验余弦相似度 >= 0.85，则：
- 返回已有经验的 ID 和标题
- 提示 agent 这是重复，建议复用或更新已有经验，而非新增

阈值 0.85 而非 0.92（analyze 中的重复检测阈值），是因为写入时宁可误判也要保护知识库纯净度。

### 3. 质量门槛

在 `extract_experience` 入口加规则校验，以下情况**拒绝写入**并返回原因：

- `key_decisions` 为空或长度 < 10 字
- `solution_summary` 长度 < 20 字

拒绝时返回明确提示，引导 agent 补充内容后重试。

### 4. key_decisions 独立存储

**模型层**：`Experience` 新增 `key_decisions: str` 字段。

**存储层**：`knowledge.json` 和 `_to_dict`/`_from_dict` 同步更新，向后兼容（旧数据默认空字符串）。

**提取层**：`solution` 字段只存 `solution_summary`，`key_decisions` 单独存储，不再拼接。

**向量化**：经验向量只用 `title + problem + key_decisions`，去掉 solution（解决方案不影响"这条经验该不该被找到"）。

**检索**：查询向量用 agent 的 `query`（任务描述），和经验的 `title + problem + key_decisions` 向量匹配。

**Review 展示**：`xp review` 中单独展示 key_decisions，突出"坑"的信息。

## Architecture

### 数据流变化

```
extract_experience(task_description, solution_summary, key_decisions)
    ↓
[质量门槛] key_decisions < 10字 → 拒绝，返回提示
    ↓
[LLM] title = llm_summarize(task_description)  # 失败则截断降级
    ↓
[去重检查] embed(title + problem) → 检索 → 相似度 >= 0.85 → 返回重复警告
    ↓
[存储] experience.key_decisions = key_decisions（独立字段）
       experience.solution = solution_summary（不含 key_decisions）
    ↓
[向量化] embed(title + problem + key_decisions) → 存入 experience_vectors
```

### 检索变化

```
search(query)
    ↓
query_vec = embed(query)
    ↓
余弦相似度匹配 experience_vectors（内容为 title + problem + key_decisions）
    ↓
返回 top-k
```

### 需要修改的文件

| 文件 | 改动 |
|------|------|
| `src/models.py` | Experience 新增 `key_decisions: str = ""` 字段 |
| `src/storage.py` | `_to_dict`/`_from_dict` 加 key_decisions，向后兼容 |
| `src/knowledge.py` | extract_experience 加质量门槛、去重、LLM title、独立存 key_decisions；向量化文本改为 title+problem+key_decisions |
| `src/cli.py` | `xp review` 单独展示 key_decisions |

### 注意事项

- 历史经验的 key_decisions 字段默认为空字符串，向量需要重新生成（可通过 `xp migrate` 触发）
- LLM 调用需要配置可用的模型，失败不应阻断整个提取流程
- 去重阈值 0.85 可后续通过配置项调整
