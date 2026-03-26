import asyncio
import json
import os
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .knowledge import KnowledgeService
from .models import Session
from .storage import ExperienceStore, MetricsStore

load_dotenv()

app = Server("xp")

_service: KnowledgeService | None = None


def get_service() -> KnowledgeService:
    if _service is None:
        raise RuntimeError("Service not initialized")
    return _service


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="extract_experience",
            description=(
                "【任务完成后必做】把这次任务的经验沉淀下来，让团队下次遇到同样问题能秒解！"
                "只要有任何'原来要这样'、'差点踩坑'、'找到了好方案'的收获，就应该记录。"
                "哪怕是很小的问题（如：某个参数要这么配、这个库要那样用），都值得沉淀。"
                "你的记录会帮助未来的自己和同事节省大量时间！"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "【必填】你要解决什么问题？一句话说清（如：'用户反馈登录后状态不保持'）",
                    },
                    "solution_summary": {
                        "type": "string",
                        "description": "【必填】最终怎么解决的？核心思路即可（如：'在 token 过期时自动刷新，并存入 localStorage'）",
                    },
                    "key_decisions": {
                        "type": "string",
                        "description": "【必填】有什么坑要注意？这是最有价值的部分（如：'不要在 useEffect 里直接调用 setState，会导致无限循环'）",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "【推荐】涉及的技术栈，方便后续检索（如 ['react', 'hooks', 'auth']）",
                    },
                    "related_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "【推荐】改了哪些文件？方便追踪失效（如 ['src/hooks/useAuth.ts', 'src/api/client.ts']）",
                    },
                },
                "required": ["task_description", "solution_summary", "key_decisions"],
            },
        ),
        Tool(
            name="search_best_practices",
            description=(
                "【任务开始第一步】在开始任何任务前，先检索团队历史经验，避免重复踩坑！"
                "检索内容包括：bugfix 方案、代码模式、配置技巧、最佳实践等。"
                "即使不确定是否有相关经验，也应该调用 - 零成本，高回报。"
                "返回的经验会告诉你：'前人踩过什么坑'、'推荐怎么解决'、'要注意什么'。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "【必填】用一句话描述你要做什么（如：'修复 React useEffect 无限循环'、'配置 Docker 网络'）",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "【推荐】技术栈标签，帮助精准匹配（如 ['react', 'typescript']）",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回条数，默认 3",
                        "default": 3,
                    },
                    "cross_project": {
                        "type": "boolean",
                        "description": "是否跨项目检索（可选，默认 false）",
                        "default": False,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="record_session",
            description=(
                "在一次完整的代码生成任务结束后调用，记录本次会话数据用于效果评估。"
                "无论是否使用了经验注入，都应记录。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "会话 ID，与 search_best_practices 中传入的 session_id 对应",
                    },
                    "task_description": {
                        "type": "string",
                        "description": "本次任务描述",
                    },
                    "experience_ids_injected": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "本次检索到并参考的经验 ID 列表，无则传空数组",
                    },
                    "iteration_count": {
                        "type": "integer",
                        "description": "完成任务的对话轮数",
                    },
                    "had_error_correction": {
                        "type": "boolean",
                        "description": "过程中是否出现报错并修正",
                    },
                    "user_accepted": {
                        "type": "boolean",
                        "description": "用户最终是否接受了生成的代码",
                    },
                },
                "required": [
                    "session_id",
                    "task_description",
                    "experience_ids_injected",
                    "iteration_count",
                    "had_error_correction",
                    "user_accepted",
                ],
            },
        ),
        Tool(
            name="record_feedback",
            description=(
                "【帮助优化知识库】反馈每条经验对你有没有帮助，让系统越用越聪明！"
                "如果某条经验帮到了你，标记采纳 - 它会变得更容易被检索到。"
                "如果没用，标记拒绝并说明原因 - 系统会学习并改进。"
                "你的反馈直接影响整个团队的知识质量！"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "experience_id": {
                        "type": "string",
                        "description": "经验的 ID，从 search_best_practices 返回结果中获取",
                    },
                    "adopted": {
                        "type": "boolean",
                        "description": "该经验是否被采纳（实际用于最终代码）",
                    },
                    "reason": {
                        "type": "string",
                        "description": "未采纳的原因（可选），如'过时'、'不相关'、'不适用当前场景'等",
                    },
                },
                "required": ["experience_id", "adopted"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    service = get_service()

    if name == "extract_experience":
        exp = await service.extract_experience(
            task_description=arguments["task_description"],
            solution_summary=arguments["solution_summary"],
            key_decisions=arguments["key_decisions"],
            tags=arguments.get("tags", []),
            related_files=arguments.get("related_files", []),
        )
        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "pending",
                "id": exp.id,
                "title": exp.title,
                "type": exp.type.value,
                "level": exp.level.value,
                "metadata": {
                    "tech_stack": exp.metadata.tech_stack,
                    "problem_type": exp.metadata.problem_type,
                    "scene": exp.metadata.scene,
                    "keywords": exp.metadata.keywords,
                },
                "message": "经验已提取，等待人工 review。运行 `xp review` 查看并确认。",
            }, ensure_ascii=False, indent=2),
        )]

    elif name == "search_best_practices":
        results = await service.search(
            query=arguments["query"],
            tags=arguments.get("tags"),
            top_k=arguments.get("top_k", 3),
        )
        if not results:
            return [TextContent(
                type="text",
                text="暂无相关历史经验，请根据实际情况处理。",
            )]
        data = [
            {
                "id": exp.id,
                "title": exp.title,
                "type": exp.type.value,
                "level": exp.level.value,
                "tags": exp.tags,
                "problem": exp.problem,
                "solution": exp.solution,
                "bm25_score": exp.similarity,
                "metadata": {
                    "tech_stack": exp.metadata.tech_stack,
                    "problem_type": exp.metadata.problem_type,
                    "scene": exp.metadata.scene,
                    "keywords": exp.metadata.keywords,
                },
                "note": "以上为历史经验，仅供参考，请结合当前实际情况判断是否适用。",
            }
            for exp in results
        ]
        return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]

    elif name == "record_session":
        session = Session(
            session_id=arguments["session_id"],
            task_description=arguments["task_description"],
            experience_ids_injected=arguments["experience_ids_injected"],
            iteration_count=arguments["iteration_count"],
            had_error_correction=arguments["had_error_correction"],
            user_accepted=arguments["user_accepted"],
            created_at=datetime.utcnow().isoformat(),
        )
        await service.record_session(session)
        return [TextContent(
            type="text",
            text=json.dumps({"status": "recorded", "session_id": session.session_id}, ensure_ascii=False),
        )]

    elif name == "record_feedback":
        success = await service.record_feedback(
            experience_id=arguments["experience_id"],
            adopted=arguments["adopted"],
            reason=arguments.get("reason"),
        )
        if success:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "recorded",
                    "experience_id": arguments["experience_id"],
                    "adopted": arguments["adopted"],
                    "message": "反馈已记录，confidence 将自动更新。",
                }, ensure_ascii=False),
            )]
        else:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": f"经验 {arguments['experience_id']} 不存在",
                }, ensure_ascii=False),
            )]

    return [TextContent(type="text", text=f"未知工具: {name}")]


async def main():
    global _service
    from .project_config import ProjectManager
    project = ProjectManager().get_current()
    store = ExperienceStore()
    metrics = MetricsStore()
    _service = KnowledgeService(store, metrics, project)

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
