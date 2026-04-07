# Phase 6: 测试辅助与端到端联调

---

## Task 17: 更新 InMemoryUnitOfWork

**Files:**
- Modify: `tests/helpers/fake_uow.py`
- Modify: `tests/helpers/test_fake_uow_smoke.py`

> **背景**：新增的 `ExperienceStatus.NEEDS_FIX` 和 `ab_group` 字段要求 `InMemoryExperienceStore.list_by_status` 能正确过滤 `needs_fix` 状态。

**Step 1: 写失败测试**

```python
# tests/helpers/test_fake_uow_smoke.py（新增用例）
from src.models import ExperienceStatus


def test_in_memory_store_filters_needs_fix_status():
    from tests.helpers.fake_uow import InMemoryUnitOfWork
    uow = InMemoryUnitOfWork()

    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceSource, ExperienceMetadata,
    )
    from datetime import datetime, timezone

    exp = Experience(
        id="test-1",
        type=ExperienceType.BUGFIX,
        level=ExperienceLevel.PROJECT,
        title="test",
        tags=[],
        problem="p",
        solution="s",
        key_decisions="",
        confidence=0.6,
        status=ExperienceStatus.NEEDS_FIX,
        source=ExperienceSource.AGENT,
        created_at=datetime.now(timezone.utc).isoformat(),
        metadata=ExperienceMetadata(),
        project="proj-1",
    )
    uow.experiences._committed["test-1"] = exp
    results = uow.experiences.list_by_status("needs_fix")
    assert len(results) == 1
    assert results[0].id == "test-1"
```

**Step 2: 运行测试确认失败**

```bash
python -m pytest tests/helpers/test_fake_uow_smoke.py::test_in_memory_store_filters_needs_fix_status -v
```

预期：FAIL（NEEDS_FIX 状态值未定义）

**Step 3: 确认 ExperienceStatus 新增 NEEDS_FIX（Phase 2 Task 05 已添加）**

如未添加，在 `src/models.py` 中添加：

```python
# ExperienceStatus enum 新增
NEEDS_FIX = "needs_fix"
```

**Step 4: 运行测试确认通过**

```bash
python -m pytest tests/helpers/test_fake_uow_smoke.py -v
```

预期：PASS（全部）

**Step 5: 提交**

```bash
git add tests/helpers/test_fake_uow_smoke.py
git commit -m "test: add needs_fix status test for InMemoryUoW"
```

---

## Task 18: 端到端联调验证

> **前提**：本地 MySQL 运行中，`.env` 已正确配置，`uv sync` 已执行。

**Step 1: 执行建表**

```bash
docker exec -i xp-mysql mysql -uroot -proot xp < src/infrastructure/backends/mysql_schema.sql
```

预期：无报错

**Step 2: 启动本地 MCP HTTP Server**

```bash
python -m uvicorn "src.server:mcp.streamable_http_app()" --host 0.0.0.0 --port 8000
```

或使用入口点（如已注册）：

```bash
xp-server
```

预期：输出类似 `Uvicorn running on http://0.0.0.0:8000`，无报错

**Step 3: 验证 search 工具（curl 模拟 MCP 调用）**

```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"method":"tools/call","params":{"name":"search","arguments":{"task_description":"MySQL连接超时","project_id":"proj-test"}}}'
```

预期：返回 JSON，包含 `session_id` 字段

**Step 4: 验证 save 工具**

```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"method":"tools/call","params":{"name":"save","arguments":{"task_description":"MySQL连接超时问题","outcome_description":"调整连接池参数后解决","outcome":"success","project_id":"proj-test"}}}'
```

预期：返回 `{"status": "saved", "experience_id": "..."}`

**Step 5: 验证 feedback 工具**

使用 Step 4 返回的 `session_id` 和 `experience_id`：

```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"method":"tools/call","params":{"name":"feedback","arguments":{"session_id":"<SESSION_ID>","adopted_ids":["<EXP_ID>"],"rejected_ids":[]}}}'
```

预期：返回 `{"status": "ok"}`

**Step 6: 在 MySQL 中验证数据写入**

```bash
docker exec -it xp-mysql mysql -uroot -proot xp -e \
  "SELECT id, title, status, confidence FROM experiences LIMIT 5;"
```

预期：看到刚保存的经验记录

**Step 7: 运行全量自动化测试**

```bash
python -m pytest tests/ -q -k "not postgres"
```

预期：全绿（E2E 测试如有需要真实 DB 的部分可加 `-k "not postgres and not e2e"`）

**Step 8: 最终提交**

```bash
git add -A
git commit -m "feat: CS arch + MySQL refactor complete - all tests pass"
```

---

## 常见问题排查

| 症状 | 原因 | 解法 |
|------|------|------|
| `ModuleNotFoundError: aiomysql` | 未安装依赖 | `uv sync` |
| `Connection refused 3306` | MySQL 未启动 | `docker start xp-mysql` |
| `LLM call returned None` | LLM API 配置错误 | 检查 `.env` 中的 `XP_LLM_API_BASE/KEY` |
| `status=pending_retry` 而非 `saved` | LLM 响应 JSON 格式不合法 | 检查 prompt 内容或 LLM 模型 |
| `NEEDS_FIX` 状态未识别 | ExperienceStatus 未更新 | 确认 Phase 2 Task 05 已执行 |
| 向量搜索总返回空 | embedding 未生成 | 确认 B 组经验的 embedding 字段非 NULL |
