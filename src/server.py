import asyncio
import json
from typing import Any

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .edge_client import EdgeFunctionClient

load_dotenv()

app = Server("xp")

_bus = None
_edge_client: EdgeFunctionClient | None = None


def get_bus():
    if _bus is None:
        raise RuntimeError("Service not initialized")
    return _bus


def get_edge_client() -> EdgeFunctionClient:
    if _edge_client is None:
        raise RuntimeError("EdgeFunctionClient not initialized")
    return _edge_client


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search",
            description=(
                "【任务开始第一步】coding 任务开始前必须调用，从团队知识库召回相关历史经验，避免重复踩坑。\n"
                "调用前请先执行：git remote get-url origin 获取 project_id；\n"
                "读取 package.json / pyproject.toml / go.mod 中的 dependencies 字段作为 project_manifest（限 2000 tokens）。\n"
                "返回的 search_event_id 需要保存，后续 save 和 feedback 需要传入。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "【必填】当前任务目标，一句话描述（如：修复 userId 为 null 的 NPE），≤500字",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "【必填】从 git remote get-url origin 提取并标准化（格式：github.com/org/repo），无 git 时用目录绝对路径",
                    },
                    "project_manifest": {
                        "type": "string",
                        "description": "【必填】package.json / pyproject.toml / go.mod 中 dependencies 相关字段内容，限 2000 tokens，超出截断",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "会话 ID，用于关联同一任务的 search/save/feedback",
                    },
                },
                "required": ["task_description", "project_id", "project_manifest"],
            },
        ),
        Tool(
            name="save",
            description=(
                "【任务完成后必调】将本次编码任务的经验沉淀到团队知识库，无论成功与否都应调用。\n"
                "solution 建议 ≥50字，key_decisions 建议 ≥30字，tags 建议 ≥2个，以保证经验质量可被自动激活。\n"
                "若任务前调用过 search，请传入 search_event_id 以关联召回记录。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "【必填】任务描述，与 search 时保持一致",
                    },
                    "solution": {
                        "type": "string",
                        "description": "【必填】解决方案核心思路，建议 ≥50字",
                    },
                    "key_decisions": {
                        "type": "string",
                        "description": "【必填】关键决策或踩坑点，建议 ≥30字，这是最有价值的部分",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "【必填】技术栈标签，建议 ≥2个（如 ['java', 'null-safety']）",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "【必填】同 search 时的 project_id",
                    },
                    "outcome": {
                        "type": "string",
                        "enum": ["success", "partial", "failed"],
                        "description": "【必填】任务结果：success（完全解决）/ partial（部分解决）/ failed（未解决）",
                    },
                    "search_event_id": {
                        "type": "string",
                        "description": "【推荐】search 返回的 search_event_id，用于关联召回记录",
                    },
                },
                "required": ["task_description", "solution", "key_decisions", "tags", "project_id", "outcome"],
            },
        ),
        Tool(
            name="feedback",
            description=(
                "【经验反馈】search 返回的经验对本次任务有帮助时，任务结束后调用，帮助系统持续优化知识质量。\n"
                "helpful_ids 和 unhelpful_ids 中的 id 必须来自对应 search 返回的结果，不能传入其他 id。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search_event_id": {
                        "type": "string",
                        "description": "【必填】search 返回的 search_event_id",
                    },
                    "helpful_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "有帮助的经验 id 列表（必须来自该 search 的结果）",
                    },
                    "unhelpful_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "无帮助的经验 id 列表（必须来自该 search 的结果）",
                    },
                    "comment": {
                        "type": "string",
                        "description": "可选的文字说明，如'exp_001 的解法直接复用'",
                    },
                },
                "required": ["search_event_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "search":
        client = get_edge_client()
        result = await client.search(
            task_description=arguments["task_description"],
            project_id=arguments["project_id"],
            project_manifest=arguments.get("project_manifest", ""),
            session_id=arguments.get("session_id"),
        )
        if not result.get("results"):
            return [TextContent(type="text", text=json.dumps(
                {"search_event_id": result.get("search_event_id"), "results": [], "message": "暂无相关历史经验"},
                ensure_ascii=False
            ))]
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "save":
        client = get_edge_client()
        result = await client.save(
            task_description=arguments["task_description"],
            solution=arguments["solution"],
            key_decisions=arguments["key_decisions"],
            tags=arguments.get("tags", []),
            project_id=arguments["project_id"],
            outcome=arguments["outcome"],
            search_event_id=arguments.get("search_event_id"),
        )
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "feedback":
        client = get_edge_client()
        result = await client.feedback(
            search_event_id=arguments["search_event_id"],
            helpful_ids=arguments.get("helpful_ids", []),
            unhelpful_ids=arguments.get("unhelpful_ids", []),
            comment=arguments.get("comment"),
        )
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "extract_experience":
        from .application.commands import ExtractExperienceCommand
        bus = get_bus()
        exp = await bus.dispatch(ExtractExperienceCommand(
            task_description=arguments["task_description"],
            solution_summary=arguments["solution_summary"],
            key_decisions=arguments["key_decisions"],
            conversation_summary=arguments.get("conversation_summary"),
            tags=arguments.get("tags", []),
            related_files=arguments.get("related_files", []),
        ))
        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "pending",
                "id": exp.id,
                "title": exp.title,
                "type": exp.type.value,
                "level": exp.level.value,
                "key_decisions": exp.key_decisions,
                "metadata": {
                    "tech_stack": exp.metadata.tech_stack,
                    "problem_type": exp.metadata.problem_type,
                    "scene": exp.metadata.scene,
                    "keywords": [],
                },
                "message": "经验已提取，等待人工 review。运行 `xp review` 查看并确认。",
            }, ensure_ascii=False, indent=2),
        )]

    elif name == "search_best_practices":
        from .application.commands import SearchCommand
        bus = get_bus()
        results, meta = await bus.dispatch(SearchCommand(
            query=arguments["query"],
            tags=arguments.get("tags"),
            top_k=arguments.get("top_k", 3),
            session_id=arguments.get("session_id"),
        ))
        if not results:
            return [TextContent(
                type="text",
                text=json.dumps({"ab_test_group": meta.get("ab_test_group", "treatment"), "result_shown": False, "results": [], "message": "暂无相关历史经验，请根据实际情况处理。"}, ensure_ascii=False),
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
                "similarity": exp.similarity,
                "metadata": {
                    "tech_stack": exp.metadata.tech_stack,
                    "problem_type": exp.metadata.problem_type,
                    "scene": exp.metadata.scene,
                    "keywords": [],
                },
                "note": "以上为历史经验，仅供参考，请结合当前实际情况判断是否适用。",
            }
            for exp in results
        ]
        return [TextContent(type="text", text=json.dumps({"ab_test_group": meta.get("ab_test_group", "treatment"), "result_shown": bool(meta.get("show_results", True)), "results": data}, ensure_ascii=False, indent=2))]

    elif name == "record_session":
        from .application.commands import RecordSessionCommand
        bus = get_bus()
        await bus.dispatch(RecordSessionCommand(
            session_id=arguments["session_id"],
            task_description=arguments["task_description"],
            experience_ids_injected=arguments["experience_ids_injected"],
            iteration_count=arguments["iteration_count"],
            had_error_correction=arguments["had_error_correction"],
            user_accepted=arguments["user_accepted"],
            ab_test_group=arguments.get("ab_test_group", "treatment"),
            ab_test_result_shown=arguments.get("result_shown", True),
        ))
        return [TextContent(
            type="text",
            text=json.dumps({"status": "recorded", "session_id": arguments["session_id"]}, ensure_ascii=False),
        )]

    elif name == "record_feedback":
        from .application.commands import RecordFeedbackCommand
        bus = get_bus()
        success = await bus.dispatch(RecordFeedbackCommand(
            experience_id=arguments["experience_id"],
            helpful=arguments["adopted"],
        ))
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

    elif name == "infer_adoption":
        from .application.commands import InferAdoptionCommand
        bus = get_bus()
        results = await bus.dispatch(InferAdoptionCommand(
            session_id=arguments["session_id"],
            final_response=arguments["final_response"],
            experience_ids_injected=arguments["experience_ids_injected"],
        ))
        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "inferred",
                "session_id": arguments["session_id"],
                "results": results,
                "message": f"已自动推断 {len(results)} 条经验的采纳情况，反馈已记录。",
            }, ensure_ascii=False, indent=2),
        )]

    elif name == "finalize_task":
        from .application.commands import ExtractExperienceCommand, RecordSessionCommand, InferAdoptionCommand
        bus = get_bus()
        extract_result = {"status": "skipped", "id": None, "reason": None}
        session_result = {"status": "skipped"}
        adoption_result = {"status": "skipped", "results": []}

        experience_id = None
        try:
            exp = await bus.dispatch(ExtractExperienceCommand(
                task_description=arguments["task_description"],
                solution_summary=arguments["solution_summary"],
                key_decisions=arguments["key_decisions"],
                conversation_summary=arguments.get("conversation_summary"),
                tags=arguments.get("tags", []),
                related_files=arguments.get("related_files", []),
            ))
            experience_id = exp.id
            extract_result = {"status": "ok", "id": exp.id, "reason": None}
        except Exception as e:
            extract_result = {"status": "skipped", "id": None, "reason": str(e)}

        try:
            await bus.dispatch(RecordSessionCommand(
                session_id=arguments["session_id"],
                task_description=arguments["task_description"],
                experience_ids_injected=[experience_id] if experience_id else [],
                iteration_count=arguments.get("iteration_count", 1),
                had_error_correction=arguments.get("had_error_correction", False),
                user_accepted=arguments.get("user_accepted", True),
            ))
            session_result = {"status": "ok"}
        except Exception as e:
            session_result = {"status": "error", "reason": str(e)}

        if experience_id:
            try:
                results = await bus.dispatch(InferAdoptionCommand(
                    session_id=arguments["session_id"],
                    final_response=arguments["final_response"],
                    experience_ids_injected=[experience_id],
                ))
                adoption_result = {"status": "ok", "results": results}
            except Exception as e:
                adoption_result = {"status": "error", "reason": str(e)}

        result = {"extract": extract_result, "session": session_result, "adoption": adoption_result}
        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "ok",
                **result,
                "message": (
                    f"经验已提取 [{result['extract']['id'][:8] if result['extract']['id'] else '跳过'}]，"
                    f"会话已记录，"
                    f"采纳推断完成（{len(result['adoption'].get('results', []))} 条）。"
                    if result['extract']['status'] == 'ok'
                    else f"会话已记录（提取跳过：{result['extract']['reason']}）"
                ),
            }, ensure_ascii=False, indent=2),
        )]

    return [TextContent(type="text", text=f"未知工具: {name}")]


async def main():
    global _edge_client
    import sys
    from .config import load_config

    config = load_config()
    if config is None:
        print("请先运行 xp login 完成登录配置。", file=sys.stderr)
        sys.exit(1)

    token = config.get("token")
    if not token:
        print("config.json 中缺少 token，请重新运行 xp login。", file=sys.stderr)
        sys.exit(1)

    edge_url = config.get("edge_function_url", "https://tsawobjvvhvbgcxnxczy.supabase.co/functions/v1")
    _edge_client = EdgeFunctionClient(base_url=edge_url, token=token)

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())


def run():
    asyncio.run(main())
