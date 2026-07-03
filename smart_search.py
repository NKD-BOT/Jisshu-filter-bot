"""
Smart Search — turns a natural-language description like
"that spiderman movie with tobey" into a real, searchable title
("Spider-Man"), using the free TMDb API.

Two-tier strategy:
  1. Strip filler words ("that", "movie", "with", "film", ...) and ask
     TMDb's multi-search for the best title match.
  2. If the query also seems to mention a PERSON (actor/director), look
     that person up on TMDb, pull their filmography, and cross-match the
     remaining keywords against it — e.g. "tobey" -> Tobey Maguire ->
     his movies -> "spiderman" narrows it down to the exact right film.

If TMDB_API_KEY isn't configured, or TMDb is unreachable, this fails
silently (returns None) and the caller just falls back to a normal
keyword/spelling search.
"""
import re
import difflib
import aiohttp

from info import TMDB_API_KEY

BASE = "https://api.themoviedb.org/3"

FILLER_WORDS = {
    "that", "the", "a", "an", "movie", "film", "show", "series", "with",
    "starring", "ft", "feat", "featuring", "actor", "actress", "one",
    "please", "send", "find", "search", "for", "me", "video", "download",
}


def _strip_filler(query: str) -> str:
    words = [w for w in re.split(r"\s+", query.strip()) if w.lower() not in FILLER_WORDS]
    return " ".join(words) if words else query.strip()


async def _get(session, path, params):
    params = {**params, "api_key": TMDB_API_KEY}
    try:
        async with session.get(f"{BASE}{path}", params=params, timeout=aiohttp.ClientTimeout(total=6)) as resp:
            if resp.status != 200:
                return None
            return await resp.json()
    except Exception as e:
        print(f"[TMDb] request failed ({path}): {e}")
        return None


async def _resolve_by_title(session, cleaned_query):
    data = await _get(session, "/search/multi", {"query": cleaned_query, "include_adult": "false"})
    if not data:
        return None
    for result in data.get("results", []):
        title = result.get("title") or result.get("name")
        if title and result.get("media_type") in ("movie", "tv"):
            return title
    return None


async def _resolve_by_person(session, query):
    words = [w for w in re.split(r"\s+", query.strip()) if w.lower() not in FILLER_WORDS]
    if len(words) < 2:
        return None

    candidates = words + [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]
    person_id = None
    matched_tokens = set()

    for cand in sorted(set(candidates), key=len, reverse=True):
        if len(cand.replace(" ", "")) < 4:
            continue
        data = await _get(session, "/search/person", {"query": cand})
        if data and data.get("results"):
            person_id = data["results"][0].get("id")
            matched_tokens = set(cand.lower().split())
            break

    if not person_id:
        return None

    remaining = [w for w in words if w.lower() not in matched_tokens]
    if not remaining:
        remaining = words

    credits = await _get(session, f"/person/{person_id}/combined_credits", {})
    if not credits:
        return None

    titles = []
    for item in credits.get("cast", []) + credits.get("crew", []):
        t = item.get("title") or item.get("name")
        if t:
            titles.append(t)
    if not titles:
        return None

    remaining_str = " ".join(remaining).lower()
    best = difflib.get_close_matches(remaining_str, [t.lower() for t in titles], n=1, cutoff=0.3)
    if best:
        for t in titles:
            if t.lower() == best[0]:
                return t
    for t in titles:
        if any(tok in t.lower() for tok in remaining if len(tok) >= 4):
            return t
    return None


async def smart_resolve(query: str):
    """Returns a canonical title guess for a natural-language query, or
    None if TMDb isn't configured / couldn't help."""
    if not TMDB_API_KEY or not query or not query.strip():
        return None
    cleaned = _strip_filler(query)
    async with aiohttp.ClientSession() as session:
        person_result = await _resolve_by_person(session, query)
        if person_result:
            return person_result
        return await _resolve_by_title(session, cleaned)
