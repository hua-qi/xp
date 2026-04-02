# 混合检索设计决策记录

## 问题
使用 Embedding 语义检索后，是否还需要 BM25？

## 结论
**两者都需要，它们是互补关系。**

## 场景对比分析

| 场景 | BM25 | Embedding | 结果 |
|------|------|-----------|------|
| 查询 "useEffect 无限循环" | 能精确匹配 `useEffect` 关键词 | 能理解语义相关 | ✅ 都擅长 |
| 查询 "hook 依赖问题" | 可能匹配不到 `useEffect` | 能理解 `hook` ≈ `useEffect` | Embedding 赢 |
| 查询 `getUserById` 函数报错 | 能精确匹配函数名 | 函数名是专有名词，语义无意义 | BM25 赢 |
| 查询 "登录失败" | 匹配字面 | 能理解 ≈ "认证错误"/"无法登录" | Embedding 赢 |
| 查询 "Docker 端口映射" | 精确匹配 `Docker` 和 `端口` | 能理解容器网络概念 | 都擅长 |

## 经验类型分析

### 代码类经验（占多数）
- 函数名、变量名、配置项 → 必须用 **BM25** 精确匹配
- 例如：`vite.config.ts`、`useAuth()`、`process.env`

### 描述类经验
- 问题描述、解决方案 → **Embedding** 语义匹配更好

## 实现方案

保留 **70% BM25 + 30% Embedding** 的混合权重：

```
1. BM25 先粗筛：保证专业术语、代码片段不丢失
2. Embedding 精排：提升语义相似但字面不同的召回
3. 混合分数排序：兼顾精确性和语义理解
```

## 后续优化方向

如果后期发现纯 Embedding 效果更好，可以通过 A/B 实验数据调整权重或完全切换。

## 参考资料

- BM25: https://en.wikipedia.org/wiki/Okapi_BM25
- BGE Embedding: https://huggingface.co/BAAI/bge-small-zh-v1.5
- 混合检索最佳实践: https://www.pinecone.io/learn/hybrid-search/

---
*记录时间: 2025-03-27*
