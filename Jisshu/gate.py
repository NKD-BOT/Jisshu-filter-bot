"""
Thin client for your ALREADY-DEPLOYED protection bot (CRAZYHUBXBOT).
Every shortlink this bot generates gets wrapped through that bot's gate
API first, so users hit the bot-check page before ever reaching the
actual shortener link:

    user -> your protection bot's gate (bot-check) -> shortener link -> ads -> file

This bot doesn't run any gate logic itself — it just calls the
protection bot's existing API. Nothing new to deploy here.
"""

import logging

import aiohttp

from info import GATE_ENABLED, GATE_API_URL, GATE_API_KEY

log = logging.getLogger("gate")


async def wrap_with_gate(destination: str) -> str:
    """Wraps `destination` with your protection bot's gate. Fails open —
    if the protection bot is unreachable or misconfigured, the original
    link is returned so this bot never gets stuck because of it."""
    if not GATE_ENABLED or not GATE_API_URL or not GATE_API_KEY:
        return destination

    api_url = f"{GATE_API_URL.rstrip('/')}/api/create"
    headers = {"X-API-Key": GATE_API_KEY}
    payload = {"destination": destination}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                api_url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    log.warning("Protection bot gate API returned HTTP %s, sending link ungated.", resp.status)
                    return destination
                data = await resp.json()
                gate_url = data.get("gate_url")
                if gate_url:
                    return gate_url
                log.warning("Protection bot gate API response missing gate_url: %s", data)
    except Exception as e:
        log.warning("Protection bot gate API call failed, sending link ungated: %s", e)

    return destination
