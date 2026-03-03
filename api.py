"""
API client — all httpx calls live here.

Every public function is async and returns parsed JSON (dict or list).
Callers (server.py, test_server.py) are responsible for error handling
and response formatting.
"""

import httpx
from typing import Any

from constants import BASE_API_URL, SEARCH_API_URL, HTTP_TIMEOUT


# ── shared async client factory ─────────────────────────────────────────────

def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        headers={"Accept": "application/json"},
    )


# ── Rules API ────────────────────────────────────────────────────────────────

async def get_all_rules(page: int = 1, page_size: int = 50) -> list[dict]:
    """
    GET /GetAllRules
    Returns a flat list of top-level OAC titles/rules.
    Each item has: id, title, referenceCode, segmentId, contactIds, ...
    """
    url = f"{BASE_API_URL}/GetAllRules"
    params = {
        "pageNumber": page,
        "pageSize": page_size,
        "filter": "false",
    }
    async with _client() as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def get_segments_by_parent_id(
    parent_id: int, include_wip: bool = False
) -> list[dict]:
    """
    GET /GetSegmentsByParentId?parentId={id}&includeWIP=false
    Returns child segments of any rule tree node.
    Navigates: title → chapter → subchapter → section.
    """
    url = f"{BASE_API_URL}/GetSegmentsByParentId"
    params = {
        "parentId": parent_id,
        "includeWIP": str(include_wip).lower(),
    }
    async with _client() as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        # API may return null for leaf nodes
        return data if isinstance(data, list) else []


async def get_rule_reference_code(rule_id: int) -> dict | list:
    """
    GET /GetRuleReferenceCode/{id}
    Returns full text and metadata for a specific rule segment.
    May return a dict or a single-element list depending on segment type.
    """
    url = f"{BASE_API_URL}/GetRuleReferenceCode/{rule_id}"
    async with _client() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def get_contact_by_id(contact_id: int) -> dict:
    """
    GET /GetContactById/{id}
    Returns agency contact information.
    """
    url = f"{BASE_API_URL}/GetContactById/{contact_id}"
    async with _client() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


# ── Search API ───────────────────────────────────────────────────────────────

async def search(
    q: str,
    top: int = 8,
    skip: int = 0,
    filters: list[str] | None = None,
) -> dict:
    """
    POST /api/Search
    Response shape:
      {
        "count": int,
        "results": [{"score": float, "document": {...}}, ...],
        "facets": {"DisplayName": [...], "Section_Number": [...], ...}
      }

    Document fields of interest:
      Id, Description, DisplayName, ChapterName, Title_Number,
      Section_Number, ParentId, SegmentTypeName, Text (HTML), EffectiveDate
    """
    url = f"{SEARCH_API_URL}/api/Search"
    body: dict[str, Any] = {
        "q": q,
        "top": top,
        "skip": skip,
        "filters": filters or [],
        "highlight": [""],
    }
    async with _client() as client:
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()


async def suggest(q: str, top: int = 5) -> dict:
    """
    POST /api/Suggest
    Response shape:
      {
        "suggestions": [{"text": str, "queryPlusText": str}, ...]
      }
    """
    url = f"{SEARCH_API_URL}/api/Suggest"
    body = {
        "q": q,
        "top": top,
        "suggester": "Id",
    }
    async with _client() as client:
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()
