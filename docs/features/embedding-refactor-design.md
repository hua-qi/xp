# XP Embedding 重构设计文档 (BM25 -> 纯向量化)

## 1. 重构背景与痛点

当前 XP 系统基于 BM25 和简易分词的 `keywords` 机制暴露了严重的数据失真问题：
1. **采纳率 (Adoption Rate) 计算失真**：由于中文分词过于简单，一条经验会被提取出几十个长尾词。在 `infer_adoption` 阶段， Agent 的最终回复很难命中 10% 以上的无意义词汇，导致大量明明被采纳的经验被系统判定为“未采纳 (0.0%)”。
2. **检索命中率低下**：A/B 测试显示，纯 BM25 (`bm25_only`) 的命中率仅有 21.7%，远低于纯 Embedding (`embedding_only`) 的 100%。

**目标**：彻底移除历史遗留的 BM25 分词器、停用词表以及长尾词 `keywords`，全面拥抱纯 Embedding 向量架构，以提高知识检索和采纳评估的准确率。

---

## 2. 核心架构设计

本次重构采用 **混合配置策略 (本地兜底 + 云端可选)** 的纯向量架构，并且为了保证原有 JSON 的极简性，向量数据将拆分到 SQLite 中独立存储。

### 2.1 Embedding Provider 抽象
为了支持本地和云端大模型，需要在核心层引入一套标准化的接口：
*   **基础接口**：定义 `EmbeddingProvider` 抽象类，提供统一的 `embed_texts(texts: list[str]) -> list[list[float]]` 方法。
*   **实现类**：
    *   `LocalBGEProvider`：封装现有的本地小模型（如 `BGE-small-zh`），作为开箱即用的默认兜底方案。
    *   `CloudAPIProvider`：可选，支持通过环境变量接入外部高性能云端模型（如 OpenAI `text-embedding-3-small`）。
*   **生命周期**：在 `server.py` (MCP Server) 和 `cli.py` (命令行) 获取核心服务时，基于配置按需进行单例初始化，以保证高性能和状态复用。

### 2.2 存储方案分离 (Storage)
为了避免大体积的浮点数数组（如 1536 维）撑爆或拖慢现有的纯文本 `knowledge.json`：
1. **JSON 保持纯洁**：现有的 `knowledge.json` 仍仅存储 `Experience` 的结构化文本数据，移除所有冗余的 `keywords` 字段。
2. **SQLite 向量表**：在原有的统计数据库或新建库中，新增表 `experience_vectors`：
   *   `experience_id` (TEXT, Primary Key)
   *   `vector` (BLOB): 使用二进制（如 `struct.pack`）压缩存储向量列表。
   *   `updated_at` (DATETIME): 方便冷启动和数据校验。

### 2.3 `infer_adoption` 采纳推断算法
完全抛弃原有的长尾关键词命中逻辑，改用精确的向量余弦相似度计算：
1.  计算当前任务最终交付物 (`final_response`) 的向量表示 `V_resp`。
2.  从 SQLite 中获取被注入经验的原始向量 `V_exp1, V_exp2...`。
3.  计算 `V_resp` 与各 `V_exp` 的**余弦相似度 (Cosine Similarity)**，范围 [-1, 1]。
4.  **推断阈值建议**：
    *   `>= 0.75`：高置信度采纳 (`adopted = True`)。
    *   `0.60 ~ 0.75`：低置信度采纳（后续可增加打标）。
    *   `< 0.60`：未采纳 (`adopted = False`)。

---

## 3. 工作流 (Workflow) 与 MCP 交互

所有的 MCP 工具调用是在 **任务级别 (Task-level)** 发生，因此 `final_response` 等参数的长度在向量模型 Token 限制的安全阈值内。

1. **`search_best_practices` (开始前)**：
   * 传入 `query`，调用 Provider 转化为向量。
   * 与 SQLite 全库向量计算相似度并返回 Top K。
2. **`extract_experience` (结束后)**：
   * 提取出新经验文本后，立刻为其生成向量，文本存 JSON，向量存入 SQLite。
   * 不再调用 `_extract_keywords`。
3. **`infer_adoption` (结束后)**：
   * 核心改动点，对 `final_response` 提权进行纯向量相似度推断，自动修正采纳率。

## 4. 数据冷启动策略
对于升级前已经存在的旧经验数据，需提供类似 `xp sync` 或 `xp migrate` 的 CLI 命令：
1. 加载 `knowledge.json` 现存的所有 ID。
2. 对比 SQLite `experience_vectors` 中缺失的记录。
3. 调用当前激活的 `EmbeddingProvider` 批量生成缺失的向量并落盘入库。
