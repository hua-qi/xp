# Phase 0: 开发环境准备

**Files:**
- Modify: `.env.example`
- Reference: `docs/designs/2026-07-04-cs-arch-mysql-refactor.md`

---

### Task 00: 搭建本地 MySQL + 配置环境变量

**Step 1: 启动本地 MySQL（Docker）**

```bash
docker run -d \
  --name xp-mysql \
  -e MYSQL_ROOT_PASSWORD=root \
  -e MYSQL_DATABASE=xp \
  -p 3306:3306 \
  mysql:8.4
```

预期：容器正常运行，`docker ps` 可见 `xp-mysql`

**Step 2: 确认 MySQL 可连接**

```bash
docker exec -it xp-mysql mysql -uroot -proot -e "SELECT 1;"
```

预期输出：`1`（无报错）

**Step 3: 配置本地 .env**

复制 `.env.example` 为 `.env`，填入以下内容：

```
DATABASE_URL=mysql+aiomysql://root:root@localhost:3306/xp
XP_LLM_API_BASE=http://your-llm-api-base
XP_LLM_API_KEY=your-api-key
XP_LLM_MODEL=gpt-4o-mini
XP_LLM_TIMEOUT=30
```

> 注意：`XP_LLM_API_BASE` 指向公司内部 LLM 服务地址，本地开发可临时用 OpenAI 公网。

**Step 4: 安装 Python 依赖（暂时跳过，Phase 1 Task 01 会更新 pyproject.toml 后再装）**

```bash
uv sync
```

预期：无报错，`.venv/` 下有 `aiomysql` 和 `sentence-transformers`
