import os
from typing import Any, Optional

import httpx

_FALLBACK_AUTH_URL = "https://tsawobjvvhvbgcxnxczy.supabase.co/functions/v1/verify-token"


async def verify_token(token: str, auth_url: str = None) -> Optional[dict]:
    if auth_url is None:
        auth_url = os.environ.get("XP_AUTH_URL", _FALLBACK_AUTH_URL)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(auth_url, json={"token": token})
    if response.status_code == 200:
        return response.json()
    return None
