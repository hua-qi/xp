# ADR-002: 团队级知识层级体系与中心化部署架构

**状态**: 已采纳  
**日期**: 2026-05-04

## 背景

xp 最初定位为个人 agent 经验沉淀工具，采用本地文件存储，单人使用。随着使用深入，暴露出以下核心问题：

1. **知识孤岛**：每个开发者的经验相互独立，团队无法共享 coding 最佳实践
2. **缺乏层级**：经验扁平存储，无法区分「项目特有」和「团队通用」的经验
3. **部署门槛高**：用户需要本地安装、配置环境，无法开箱即用
4. **MCP tool 过多**：6 个 tool 认知负担重，agent 容易调用错误或遗漏

## 决策

### 2.1 引入三层知识层级

系统从扁平结构升级为与组织结构对应的三层知识层级：

```
Team（团队）—— 最抽象，跨业务通用
  └── Business（业务）—— 中等抽象，某业务下共享
        └── Project（项目 = Git 仓库）—— 最具体，单个 repo 内共享
```

- **Project 层**：agent 在 git 仓库内自动沉淀，同一仓库的所有成员共享
- **Business 层**：同一业务下所有项目共享，由人工从 Project 层遴选提升
- **Team 层**：整个团队共享，由人工从 Business 层遴选提升，最为抽象通用

### 2.2 经验双向流动

经验的层级不是固定的，支持人工双向迁移：

- **提升**：把较具体的经验抽象化，推广到更高层级
- **降级**：把通用原则具体化，落地到某个 Business 或 Project
- 迁移时，原经验**保留**，新层级创建副本，通过 `promoted_to` / `demoted_from` 字段关联溯源

### 2.3 Agent 驱动的提升推荐

Agent 定时扫描，通过多维度评分发现「提升候选」，推送给人工审核：

```
提升得分 = 跨项目出现次数 × 0.5
         + adoption_rate × 0.3
         + min(recall_count / 10, 1) × 0.2

触发条件：
  - 同 Business 下 ≥ 2 个不同 Project 存在语义相似经验（相似度 > 0.85）
  - adoption_rate > 0.6 且 recall_count > 5
  - created_at > 30 天前（排除不稳定的新经验）
  - 综合得分 > 0.7 → 标记为提升候选
```

**原则**：Agent 只做推荐，人工来决策。

### 2.4 中心化部署，始终远端

放弃本地文件存储模式，始终采用中心化部署：

- **存储**：PostgreSQL + pgvector，支持多用户并发读写和向量相似度搜索
- **部署**：单进程 FastAPI，MCP endpoint 和 REST endpoint 共享同一 Service 层
- **用户侧零配置**：只需在 MCP 配置里填入 server URL 和 personal token
- **管理员一键部署**：Docker 单容器启动

### 2.5 MCP tool 从 6 个精简为 3 个

| 旧 tool | 合并到 |
|---------|--------|
| search_best_practices | search |
| extract_experience | save |
| record_session | search（搜索时记录 session） |
| record_feedback | feedback |
| infer_adoption | feedback（隐式推断兜底） |
| finalize_task | 拆分到 save + feedback |

新的 3 个 tool：`search`（召回）/ `save`（沉淀）/ `feedback`（反馈）

## 备选方案

### 部署架构备选方案

考虑过三种架构：

**方案 A：MCP Server 直连 DB**  
最简单，但 MCP Server 直连 DB 横向扩展麻烦，鉴权需要嵌入 MCP 层，未采纳。

**方案 B：MCP Gateway + REST API 分离**  
MCP 和 REST API 解耦最彻底，但多一跳 HTTP，本地开发需启动两个进程，复杂度上升，未采纳。

**方案 C：单进程 MCP + REST 共享 Service 层（采纳）**  
单进程部署，无网络开销，MCP 和 REST 共用同一套业务逻辑，既简单又灵活。

### 项目元信息收集备选方案

考虑过通过 MCP roots 能力获取工作区目录，由 server 扫描 `package.json` 等文件。但在远端中心化部署场景下，server 无法读取客户端本地文件，因此改为通过 **tool description 引导 agent 主动读取并传入**配置文件关键内容。

## 结果

### 正面影响

- **知识共享**：团队成员的 coding 经验可以汇聚、沉淀、共享，不再是孤岛
- **层级化管理**：经验按抽象程度分层，Project 级别具体，Team 级别通用，各取所需
- **开箱即用**：用户零配置接入，管理员 Docker 一键部署
- **工具简洁**：3 个 tool 覆盖完整工作流，降低 agent 认知负担
- **自动进化**：agent 定期扫描推荐提升候选，知识库自动向上沉淀

### 负面/妥协

- **放弃离线模式**：不再支持纯本地无网络使用
- **运维依赖**：需要团队有人维护中心化服务和 PostgreSQL
- **提升需人工介入**：agent 只能推荐，不能自动提升，依赖人工及时 review
