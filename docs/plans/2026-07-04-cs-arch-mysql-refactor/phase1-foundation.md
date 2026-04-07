# Phase 1: 基础层

---

## Task 01: 依赖更新

**Files:**
- Modify: `pyproject.toml`

**Step 1: 更新 pyproject.toml 依赖**

将 `asyncpg` 和 `pgvector` 替换为 MySQL 驱动；新增 `openai`（LLM 调用）：

```toml
[project.dependencies]
mcp[cli]>=1.0.0
python-dotenv>=1.0.0
sentence-transformers>=3.0.0
numpy>=1.24.0
aiomysql>=0.2.0
PyMySQL>=1.1.0
fastapi>=0.110.0
uvicorn>=0.29.0
httpx>=0.27.0
pytest-asyncio>=1.3.0
openai>=1.0.0
apscheduler>=3.10.0
```

> 删除 `asyncpg` 和 `pgvector`，新增 `aiomysql`、`PyMySQL`、`openai`、`apscheduler`。

**Step 2: 安装依赖**

```bash
uv sync
```

预期：无报错

**Step 3: 验证关键包可导入**

```bash
python -c "import aiomysql; import openai; import apscheduler; print('OK')"
```

预期输出：`OK`

---

## Task 02: 配置模块更新

**Files:**
- Modify: `src/config.py`

**Step 1: 阅读现有 config.py**

```bash
# 阅读 src/config.py 了解现有结构
```

**Step 2: 新增 LLM 配置字段**

在现有配置类中新增以下字段（保持原有字段不变）：

```python
# src/config.py 新增内容（在现有 Config 类中添加）
LLM_API_BASE: str = os.getenv("XP_LLM_API_BASE", "")
LLM_API_KEY: str = os.getenv("XP_LLM_API_KEY", "")
LLM_MODEL: str = os.getenv("XP_LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT: int = int(os.getenv("XP_LLM_TIMEOUT", "30"))
```

**Step 3: 写失败测试**

```python
# tests/unit/test_config.py（新增用例）
def test_llm_config_defaults():
    import os
    os.environ.pop("XP_LLM_MODEL", None)
    from importlib import reload
    import src.config as cfg
    reload(cfg)
    assert cfg.get_config().LLM_MODEL == "gpt-4o-mini"
    assert cfg.get_config().LLM_TIMEOUT == 30
```

**Step 4: 运行测试确认失败**

```bash
python -m pytest tests/unit/test_config.py::test_llm_config_defaults -v
```

预期：FAIL（字段未定义）

**Step 5: 实现配置字段**

修改 `src/config.py`，在 Config dataclass 中添加上述四个字段。

**Step 6: 运行测试确认通过**

```bash
python -m pytest tests/unit/test_config.py::test_llm_config_defaults -v
```

预期：PASS

**Step 7: 提交**

```bash
git add src/config.py tests/unit/test_config.py
git commit -m "feat: add LLM config fields"
```

---

## Task 03: LLM 统一调用层

**Files:**
- Create: `src/infrastructure/llm.py`
- Create: `tests/unit/test_llm.py`

**Step 1: 写失败测试**

```python
# tests/unit/test_llm.py
from unittest.mock import AsyncMock, MagicMock, patch

def make_mock_response(content: str):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp

async def test_llm_call_returns_content():
    from src.infrastructure.llm import LLMClient
    client = LLMClient(api_base="http://fake", api_key="key", model="gpt-4o-mini", timeout=10)
    with patch.object(client._client.chat.completions, "create", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = make_mock_response("hello")
        result = await client.call("你好")
    assert result == "hello"

async def test_llm_call_returns_none_on_timeout():
    from src.infrastructure.llm import LLMClient
    import asyncio
    client = LLMClient(api_base="http://fake", api_key="key", model="gpt-4o-mini", timeout=1)
    with patch.object(client._client.chat.completions, "create", side_effect=asyncio.TimeoutError):
        result = await client.call("你好")
    assert result is None
```

**Step 2: 运行测试确认失败**

```bash
python -m pytest tests/unit/test_llm.py -v
```

预期：FAIL（模块不存在）

**Step 3: 实现 LLMClient**

```python
# src/infrastructure/llm.py
from __future__ import annotations
import asyncio
from typing import Optional
import openai


class LLMClient:
    def __init__(self, api_base: str, api_key: str, model: str, timeout: int):
        self._model = model
        self._timeout = timeout
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=api_base or None)

    async def call(self, prompt: str, system: str = "") -> Optional[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            resp = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                ),
                timeout=self._timeout,
            )
            return resp.choices[0].message.content
        except Exception:
            return None
```

**Step 4: 运行测试确认通过**

```bash
python -m pytest tests/unit/test_llm.py -v
```

预期：PASS（2 个测试）

**Step 5: 提交**

```bash
git add src/infrastructure/llm.py tests/unit/test_llm.py
git commit -m "feat: add LLMClient"
```

---

## Task 04: Embedding 模型切换到 BGE-m3

**Files:**
- Modify: `src/embeddings.py`
- Modify: `tests/unit/test_embeddings.py`（如存在）

**Step 1: 写失败测试**

```python
# tests/unit/test_embeddings_bge_m3.py
def test_local_bge_m3_default_model_name():
    from src.embeddings import LocalBGEProvider
    p = LocalBGEProvider()
    assert p._model_name == "BAAI/bge-m3"

def test_embedding_dim_constant():
    from src.embeddings import EMBEDDING_DIM
    assert EMBEDDING_DIM == 1024
```

**Step 2: 运行测试确认失败**

```bash
python -m pytest tests/unit/test_embeddings_bge_m3.py -v
```

预期：FAIL（默认 model_name 不对，EMBEDDING_DIM 未定义）

**Step 3: 修改 embeddings.py**

- 将 `LocalBGEProvider.__init__` 默认 `model_name` 改为 `"BAAI/bge-m3"`
- 在模块顶层新增：`EMBEDDING_DIM = 1024`

**Step 4: 运行测试确认通过**

```bash
python -m pytest tests/unit/test_embeddings_bge_m3.py -v
```

预期：PASS

**Step 5: 提交**

```bash
git add src/embeddings.py tests/unit/test_embeddings_bge_m3.py
git commit -m "feat: switch embedding model to BGE-m3 (1024-dim)"
```
