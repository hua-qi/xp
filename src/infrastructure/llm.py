from __future__ import annotations
import asyncio
from typing import Optional
import openai


class LLMClient:
    def __init__(self, api_base: str, api_key: str, model: str, timeout: int):
        self._model = model
        self._timeout = timeout
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=api_base or None)

    async def call(self, prompt: str, system: str = "") -> Optional[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            resp = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                ),
                timeout=self._timeout,
            )
            return resp.choices[0].message.content
        except Exception:
            return None
