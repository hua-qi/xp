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
                "在完成一个代码任务后调用此工具，将本次任务的经验提取并沉淀到知识库（状态为 pending，需人工 review 确认）。"
                "每次完成有价值的功能实现或 bug 修复时都应调用。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "本次任务描述，说明要做什么或遇到了什么问题",
                    },
                    "solution_summary": {
                        "type": "string",
                        "description": "解决方案摘要，说明最终如何解决的",
                    },
                    "key_decisions": {
                        "type": "string",
                        "description": "关键决策或踩坑点，说明过程中做了哪些重要选择或遇到了哪些坑",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "技术栈标签，如 ['react', 'typescript', 'hooks']",
                    },
                    "related_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "本次任务涉及的关键文件路径（可选）",
                    },
                },
                "required": ["task_description", "solution_summary", "key_decisions"],
            },
        ),
        Tool(
            name="search_best_practices",
            description=(
                "在开始编写代码前，根据当前任务描述检索历史最佳实践和 bugfix 经验。"
                "遇到相似场景或报错时优先调用，返回的经验仅供参考，需结合实际情况判断是否适用。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "任务描述或报错信息",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "技术栈标签，用于过滤（可选）",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回条数，默认 3",
                        "default": 3,
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
                "记录检索到的经验是否被采纳，用于动态更新经验 confidence 和识别低质量经验。"
                "在完成任务后，agent 应评估每个注入的经验是否实际被采用。"
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
    store = ExperienceStore()
    metrics = MetricsStore()
    _service = KnowledgeService(store, metrics)

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
