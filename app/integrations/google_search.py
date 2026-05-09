"""Google Search via SerpAPI — einfache REST-Anfrage, kein SDK nötig."""
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search"


async def google_search(query: str, num_results: int = 5) -> list[dict]:
    """
    Führt eine Google-Suche über SerpAPI durch.
    Gibt eine Liste von {title, link, snippet} zurück.
    """
    if not settings.SERPAPI_KEY:
        raise ValueError("SERPAPI_KEY nicht konfiguriert — bitte in .env setzen.")

    params = {
        "q": query,
        "api_key": settings.SERPAPI_KEY,
        "engine": "google",
        "num": num_results,
        "hl": "de",
        "gl": "de",
    }

    logger.info("google_search.request", extra={"query": query, "num": num_results})

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(SERPAPI_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for r in data.get("organic_results", [])[:num_results]:
        results.append({
            "title":   r.get("title", ""),
            "link":    r.get("link", ""),
            "snippet": r.get("snippet", ""),
        })

    logger.info("google_search.results", extra={"query": query, "count": len(results)})
    return results
