# A/B 测试统计语义重构

**Date:** 2026-03-31

## Context

当前 `xp stats` 命令展示了两组对比数据：

1. **有注入 vs 无注入**：按 `json_array_length(experience_ids_injected) > 0` 区分
2. **treatment vs control**：按 `ab_test_group` 列区分

这两个维度在概念上存在重叠——control 组 session 会出现在"无注入"侧，但"无注入"还混入了 treatment 组中没有检索到匹配经验的 session。导致 stats 展示语义不清晰，用户难以判断哪组数据更可信。

此外，在修复之前，`record_session` 入库时遗漏了 `ab_test_group` 字段，导致所有 session 使用数据库默认值 `'treatment'`，control 组数据全为 0，两套统计实际上展示了重复数据。

## Discussion

**探索的核心问题：**

- "有注入 vs 无注入"不干净：treatment 组中未检索到经验的 session 与 control 组被屏蔽的 session 混在一起，无法准确反映"有经验 vs 无经验"的效果差异
- treatment vs control 才是更可信的对照实验，因为两组唯一变量就是"是否展示经验"

**探索的三个方案：**

| 方案 | 核心思路 | 优点 | 缺点 |
|------|---------|------|------|
| A：result_shown 单维度 | 废弃两套维度，以 `ab_test_result_shown` 为唯一区分 | 语义最清晰，无歧义 | 改动中等，需迁移历史数据 |
| B：删除重叠展示 | 只改 `cli.py`，删掉"有注入 vs 无注入" | 改动最小 | 数据仍不干净 |
| C：三分组 | treatment 拆分为 hit/miss 两组 | 信息最丰富 | 样本量不足（73次），复杂度高 |

**最终选择：方案 A**

## Approach

以"是否实际展示经验（`result_shown`）"作为唯一统计维度，替代现有的两套逻辑：

- `ab_test_result_shown = true` → 展示了经验（无论属于哪个 ab_test_group）
- `ab_test_result_shown = false` → 未展示经验（control 组屏蔽 + treatment 组无命中）

`search_best_practices` 返回值携带 `result_shown` 字段，agent 在调用 `record_session` 时如实传入，stats 展示层只保留一组对比，列名改为"展示经验 / 未展示经验"。

## Architecture

### 数据流

```
search_best_practices
    ↓ 返回 { ab_test_group, result_shown, results }
Agent 执行任务
    ↓
record_session(... result_shown=true/false)
    ↓ 写入 sessions.ab_test_result_shown
stats 查询
    ↓ WHERE ab_test_result_shown=1  vs  WHERE ab_test_result_shown=0
cli 展示
    ↓ "展示经验" vs "未展示经验"
```

### 各层改动

**`knowledge.py`**：无需改动，已通过 `meta["show_results"]` 返回是否展示。

**`server.py - search_best_practices`**：在返回 JSON 中追加 `result_shown` 字段（`meta["show_results"]` 的值）。

**`server.py - record_session` schema**：
- 新增可选参数 `result_shown: bool`，默认 `true`
- agent 从 `search_best_practices` 返回值读取并传入

**`storage.py - record_session`**：
- INSERT 语句加上 `ab_test_result_shown` 列

**`storage.py - get_stats`**：
- 删除 `experience_ids_injected > 0` 和 `= 0` 两个查询
- 删除 `ab_test_groups` 单独查询块
- 改为按 `ab_test_result_shown = 1` vs `= 0` 统计，合并为一组对比

**`cli.py`**：
- 删除"有注入 vs 无注入"展示区块
- 保留单组对比，列名改为"展示经验 / 未展示经验"

### 注意事项

- 历史 session 的 `ab_test_result_shown` 默认为 `true`（数据库建表时的默认值），历史数据不需要迁移但会有轻微偏差
- `ab_test_group` 字段继续保留，用于未来需要单独分析 control 组行为时使用
