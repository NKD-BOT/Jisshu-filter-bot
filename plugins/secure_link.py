import os
import aiohttp
import logging

logger = logging.getLogger(__name__)

CENTRAL_API_URL = os.getenv("CENTRAL_VERIFY_API", "").rstrip("/")
CENTRAL_API_KEY = os.getenv("CENTRAL_API_KEY", "")

async def get_secure_link(original_url: str) -> str:
    if not CENTRAL_API_URL or not CENTRAL_API_KEY:
        return original_url
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"X-API-Key": CENTRAL_API_KEY}
            payload = {"destination": original_url}
            async with session.post(
                f"{CENTRAL_API_URL}/api/create",
                json=payload,
                headers=headers,
                timeout=10
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    gate_url = data.get("gate_url")
                    if gate_url:
                        return gate_url
    except Exception as e:
        logger.error(f"Secure link failed: {e}")
    return original_url
