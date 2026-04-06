from __future__ import annotations
from typing import Optional
import httpx


class EdgeFunctionClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def search(
        self,
        task_description: str,
        project_id: str,
        project_manifest: str,
        session_id: Optional[str] = None,
        top_k: int = 5,
    ) -> dict:
        payload = {
            "task_description": task_description,
            "project_id": project_id,
            "project_manifest": project_manifest,
            "top_k": top_k,
        }
        if session_id:
            payload["session_id"] = session_id

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/search",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def save(
        self,
        task_description: str,
        solution: str,
        key_decisions: str,
        tags: list[str],
        project_id: str,
        outcome: str,
        search_event_id: Optional[str] = None,
    ) -> dict:
        payload = {
            "task_description": task_description,
            "solution": solution,
            "key_decisions": key_decisions,
            "tags": tags,
            "project_id": project_id,
            "outcome": outcome,
        }
        if search_event_id:
            payload["search_event_id"] = search_event_id

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/process-save",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def feedback(
        self,
        search_event_id: str,
        helpful_ids: list[str] = None,
        unhelpful_ids: list[str] = None,
        comment: Optional[str] = None,
    ) -> dict:
        payload = {
            "search_event_id": search_event_id,
            "helpful_ids": helpful_ids or [],
            "unhelpful_ids": unhelpful_ids or [],
        }
        if comment:
            payload["comment"] = comment

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/process-feedback",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
