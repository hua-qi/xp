from __future__ import annotations
from typing import Optional

_FALLBACK_PROMPTS = {
    "extraction_prompt": (
        "你是一个工程经验提炼助手。任务描述：{task_description}，"
        "结果：{outcome_description}，状态：{outcome}。"
        '请输出 JSON：{{"title":"","problem":"","solution":"",'
        '"key_decisions":"","tags":[],"type":"bugfix"}}'
    ),
    "conflict_type_prompt": "只输出类型名称：outdated/alternative/version_diff/new_may_wrong/condition_diff",
    "rerank_prompt": "只输出 JSON ID 数组",
    "comment_analysis_prompt": "只输出：irrelevant 或 needs_fix",
}

PROMPT_KEYS = list(_FALLBACK_PROMPTS.keys())


class PromptLoader:
    def __init__(self, backend):
        self._backend = backend
        self._cache: dict[str, str] = {}

    async def refresh(self):
        for key in PROMPT_KEYS:
            val = await self._backend.async_get_prompt(key)
            if val:
                self._cache[key] = val

    def get(self, key: str, **kwargs) -> str:
        template = self._cache.get(key) or _FALLBACK_PROMPTS.get(key, "")
        if kwargs:
            try:
                return template.format(**kwargs)
            except KeyError:
                return template
        return template
