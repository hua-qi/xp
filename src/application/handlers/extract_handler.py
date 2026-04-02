from __future__ import annotations
from typing import Callable
from ..commands import ExtractExperienceCommand
from ..unit_of_work import AbstractUnitOfWork


class ExtractHandler:
    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork], project: str = "default"):
        self._uow_factory = uow_factory
        self._project = project

    def handle_extract(self, cmd: ExtractExperienceCommand):
        from ...domain.extraction import ExtractionService
        from ...storage import ExperienceStore, VectorStore
        import os
        import asyncio

        title = None
        try:
            api_key = os.getenv("OPENAI_API_KEY") or os.getenv("XP_LLM_API_KEY")
            api_base = os.getenv("XP_LLM_API_BASE")
            model = os.getenv("XP_LLM_MODEL", "gpt-4o-mini")
            if api_key:
                import openai
                client = openai.OpenAI(api_key=api_key, base_url=api_base)
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": f"用10-15个字总结以下任务，只输出标题，不加标点：\n{cmd.task_description}"}],
                    max_tokens=30,
                    temperature=0,
                )
                title = resp.choices[0].message.content.strip()
        except Exception:
            title = None

        store = ExperienceStore()
        v_store = VectorStore()
        svc = ExtractionService(store, v_store, project=self._project)

        import asyncio
        coro = svc.extract(
            cmd.task_description,
            cmd.solution_summary,
            cmd.key_decisions,
            cmd.conversation_summary,
            cmd.tags,
            cmd.related_files,
            title=title,
        )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, coro)
                    exp = future.result()
            else:
                exp = loop.run_until_complete(coro)
        except RuntimeError:
            exp = asyncio.run(coro)
        return exp
