# XP Embedding 纯向量化重构实施记录

## 1. 变更背景
本次重构的目标是彻底移除旧有的 BM25 分词器、停用词表以及相关的基于分词的 `keywords` 机制。使用统一的基于向量的 Embedding 方案（包含本地和云端模型支持），解决原先关键词泛滥导致采纳推断不准确（数据失真），以及混合检索命中率不高的问题。

## 2. 变更内容

### 2.1 引入 Embedding Provider 层
在 `src/embeddings.py` 中抽象出 `EmbeddingProvider`：
- `LocalBGEProvider`: 封装基于 `BAAI/bge-small-zh-v1.5` 的默认本地模型兜底方案
- `CloudAPIProvider`: 可选的外部云端模型支持（如 OpenAI `text-embedding-3-small`）

### 2.2 存储层的拆分与优化 (SQLite + JSON)
在 `src/storage.py` 及 `src/models.py` 内部实施了存储结构分离：
- 净化了 `knowledge.json` 中冗余的 `keywords` 字典内容，相关结构化元数据 (`ExperienceMetadata`) 不再生成/维护长尾的 `keywords` 数组。
- 在 `metrics.db` 统计库中增加了 `experience_vectors` 表。使用 `struct` 二进制 BLOB 压缩存储经验的浮点数向量。
- 新增了 `VectorStore` 类，提供批量/单条读取和写入向量的方法。

### 2.3 `infer_adoption` 采纳推断算法全面向量化
修改 `src/knowledge.py`，抛弃原先依赖提取生成的关键词对 final_response 做文本匹配的方式，重构为：
- 利用激活的 `EmbeddingProvider` 编码出当前交付文本的表示向量。
- 读取出所有受注入的经验对应的原始向量进行**纯余弦相似度**计算。
- 采用余弦相似度作为新标尺（>= 0.75 高置信度采纳，0.60~0.75 为低置信采纳，< 0.60 为未采纳）。

### 2.4 移除历史依赖并更新命令行 (CLI) 交互
- 全局移除了 `rank_bm25` 以及简单的字符串分词 `_tokenize` 与 `_extract_keywords` 的逻辑。
- 移除了 `xp stats` 对于多检索策略（BM25_only 等混合检索对比）统计的代码和表字段展示。
- 新增 `xp migrate` 命令并加入 CLI 参数映射。用于冷启动或扫描知识库现存记录中缺少向量支持的实体，进行异步自动批量向量补充计算并持久化。
- 修复了 `xp review` CLI 工具直接访问已被移除的 `keywords` 属性引发的抛错。

## 3. 经验总结与关键决策
- **二进制存储性能优化**：对于高维向量（如 512 或更长的维度列表），不使用纯 JSON 或者文本落地，而是使用 `struct.pack` 统一压入 SQLite BLOB 字段读取，这极大提高了高频读写的性能并避免了无意义的纯文本库体积膨胀。
- **冷启动与批量写入**：更新底层结构时必须考虑老数据的平滑过渡，实现 `xp migrate` 的独立入口通过分批次提取计算并 commit 入库，这降低了对内存的瞬间压力，也是典型的结构迭代模式。
- **f-string 转义陷阱**：在使用脚本（如 sed, python AST / re）更新或写入大段带内联多行 f-string 的 Python 代码时，须谨防真实换行破坏 f-string 的语法。推荐严格控制并处理 `\\n` 的转义，或者避免多行嵌套。
