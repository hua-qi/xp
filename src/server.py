import asyncio
import json
import os
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .container import build_command_bus
from .models import Session
from .storage import ExperienceStore, MetricsStore

load_dotenv()

app = Server("xp")

_bus = None


def get_bus():
    if _bus is None:
        raise RuntimeError("Service not initialized")
    return _bus


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
                    "conversation_summary": {
                        "type": "string",
                        "description": "【强烈推荐】对话过程摘要，包含关键排查步骤、尝试过的方案、报错信息等，帮助更完整理解问题背景",
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
                "【任务开始第一步】在执行任何任务前，先检索团队历史经验，避免重复踩坑！"
                "适用任务：编写代码、生成文档、Debug 排查、代码重构、配置环境、代码审查、测试编写等。"
                "检索内容：bugfix 方案、代码模式、配置技巧、文档模板、最佳实践等。"
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
                    "session_id": {
                        "type": "string",
                        "description": "【强烈推荐】会话 ID，用于 A/B 测试分组和效果追踪（如 'session-20250327-001'）",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="record_session",
            description=(
                "【任务完成后必调】在一次完整的任务结束后调用，记录本次会话数据用于效果评估。"
                "适用任务：编写代码、生成文档、Debug 排查、代码重构、配置环境、代码审查、测试编写等任何任务。"
                "无论是否使用了经验注入、无论成功与否，都应记录。"
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
                    "ab_test_group": {
                        "type": "string",
                        "description": "A/B 测试分组，从 search_best_practices 返回的 metadata.ab_test_group 中获取，未调用则传 'treatment'",
                    },
                    "result_shown": {
                        "type": "boolean",
                        "description": "是否实际展示了经验结果，从 search_best_practices 返回值的 result_shown 字段获取，未调用则传 true",
                        "default": True,
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
        Tool(
            name="infer_adoption",
            description=(
                "【自动推断经验采纳情况】根据最终生成的内容和注入的经验，自动推断哪些经验被采纳了。"
                "系统会检查最终回复是否包含经验中的关键代码、方案或决策点。"
                "无需手动标记，自动完成反馈闭环！"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "会话 ID，与 record_session 中的一致",
                    },
                    "final_response": {
                        "type": "string",
                        "description": "任务的最终回复内容（代码、文档、分析结果等）",
                    },
                    "experience_ids_injected": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "本次注入的经验 ID 列表",
                    },
                },
                "required": ["session_id", "final_response", "experience_ids_injected"],
            },
        ),
        Tool(
            name="finalize_task",
            description=(
                "【任务完成后一键完成】替代原有的 extract_experience + record_session + infer_adoption 三步调用。"
                "内部三步独立容错：提取失败不影响会话记录；无需手动调用其他工具。"
                "每次任务完成后只需调用这一个工具即可。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "会话 ID，与 search_best_practices 中传入的 session_id 一致",
                    },
                    "task_description": {
                        "type": "string",
                        "description": "【必填】你要解决什么问题？一句话说清",
                    },
                    "solution_summary": {
                        "type": "string",
                        "description": "【必填】最终怎么解决的？核心思路",
                    },
                    "key_decisions": {
                        "type": "string",
                        "description": "【必填】有什么坑要注意？这是最有价值的部分",
                    },
                    "final_response": {
                        "type": "string",
                        "description": "【必填】任务的最终回复内容，用于推断经验采纳情况",
                    },
                    "conversation_summary": {
                        "type": "string",
                        "description": "【推荐】对话过程摘要，包含关键排查步骤",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "技术栈标签",
                    },
                    "related_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "涉及的关键文件路径",
                    },
                    "iteration_count": {
                        "type": "integer",
                        "description": "对话轮数，默认 1",
                        "default": 1,
                    },
                    "had_error_correction": {
                        "type": "boolean",
                        "description": "是否出现过报错修正",
                        "default": False,
                    },
                    "user_accepted": {
                        "type": "boolean",
                        "description": "用户是否接受结果",
                        "default": True,
                    },
                },
                "required": ["session_id", "task_description", "solution_summary", "key_decisions", "final_response"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    from .application.commands import (
        ExtractExperienceCommand, SearchCommand, RecordSessionCommand,
        RecordFeedbackCommand, InferAdoptionCommand,
    )
    bus = get_bus()

    if name == "extract_experience":
        exp = bus.dispatch(ExtractExperienceCommand(
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
        results, meta = bus.dispatch(SearchCommand(
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
        bus.dispatch(RecordSessionCommand(
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
        success = bus.dispatch(RecordFeedbackCommand(
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
        results = bus.dispatch(InferAdoptionCommand(
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
        extract_result = {"status": "skipped", "id": None, "reason": None}
        session_result = {"status": "skipped"}
        adoption_result = {"status": "skipped", "results": []}

        experience_id = None
        try:
            exp = bus.dispatch(ExtractExperienceCommand(
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
            bus.dispatch(RecordSessionCommand(
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
                results = bus.dispatch(InferAdoptionCommand(
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
    global _bus
    from .project_config import ProjectManager
    project = ProjectManager().get_current()
    _bus = build_command_bus(project=project)

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
