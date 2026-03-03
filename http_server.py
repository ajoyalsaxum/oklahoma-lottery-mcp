"""
http_server.py — FastAPI HTTP layer for Custom GPT Actions.

Exposes 7 REST endpoints covering the full Oklahoma Administrative Code
(all 177 agencies). FastAPI auto-generates the OpenAPI spec at /openapi.json.

Start locally:
    uvicorn http_server:app --reload --port 8000

Then visit http://localhost:8000/docs to explore the interactive API docs.
"""

import re
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import api
import cache
from constants import BASE_API_URL, SEARCH_API_URL, DEFAULT_TITLE_FILTER

# ── app setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Oklahoma Administrative Rules",
    description=(
        "Live access to the full Oklahoma Administrative Code (OAC) — all 177 state agencies. "
        "Use GET /titles to see every agency, GET /chapters to browse chapters of any title, "
        "and GET /search to find rules by keyword."
    ),
    version="1.0.0",
    contact={"name": "Oklahoma Lottery Commission research tool"},
    servers=[
        {"url": "https://ok-lottery-rules.onrender.com", "description": "Production"},
    ],
)

# ChatGPT needs permissive CORS to call the API from its backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://chat.openai.com", "https://chatgpt.com", "*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ── helpers ───────────────────────────────────────────────────────────────────

_HTML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    text = _HTML_TAG.sub(" ", html or "")
    return _WHITESPACE.sub(" ", text).strip()


def _http_error(e: Exception, context: str) -> HTTPException:
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 404:
            raise HTTPException(status_code=404, detail=f"{context} not found.")
        raise HTTPException(status_code=502, detail=f"Upstream API returned {status}.")
    if isinstance(e, httpx.RequestError):
        raise HTTPException(status_code=503, detail=f"Network error reaching the API: {e}")
    raise HTTPException(status_code=500, detail=str(e))


# ── response models (for OpenAPI schema generation) ──────────────────────────

class SearchResult(BaseModel):
    segment_id: str
    description: str
    citation: str
    title_number: str
    display_name: str
    chapter: str
    effective_date: str
    excerpt: str
    relevance_score: float
    source_url: str = Field(default=f"{SEARCH_API_URL}/api/Search")


class SearchResponse(BaseModel):
    query: str
    title_filter: str
    total_api_count: int
    returned_count: int
    results: list[SearchResult]
    next_page_skip: int | None = None


class SuggestResponse(BaseModel):
    query: str
    suggestions: list[str]


class ChildSegment(BaseModel):
    id: int | str
    title: str
    citation: str
    segment_type: str
    source_url: str


class ChildrenResponse(BaseModel):
    parent_id: int
    count: int
    children: list[ChildSegment]
    source_url: str


class RuleResponse(BaseModel):
    id: int
    title: str
    citation: str
    segment_type: str
    effective_date: str
    rule_status: Any
    record_status: Any
    notes: str
    text: str
    source_url: str


class RuleListItem(BaseModel):
    id: int | str
    segment_id: int | str
    reference_code: str
    title: str


class AllRulesResponse(BaseModel):
    page: int
    page_size: int
    title_filter: str
    returned_from_api: int
    matching_filter: int
    rules: list[RuleListItem]
    source_url: str


class Chapter(BaseModel):
    id: int | str
    title: str
    citation: str
    segment_type: str


class ChaptersResponse(BaseModel):
    title_number: str
    title_name: str
    segment_id: int | str
    rule_id: int | str
    chapter_count: int
    chapters: list[Chapter]
    source_url: str


class TitleItem(BaseModel):
    reference_code: str
    title: str
    segment_id: int | str
    rule_id: int | str


class TitlesResponse(BaseModel):
    total_count: int
    titles: list[TitleItem]
    source_url: str


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get(
    "/search",
    response_model=SearchResponse,
    summary="Full-text search across Oklahoma Administrative Code rules",
    tags=["Rules"],
)
async def search_rules(
    query: str = Query(..., description="Search term or phrase, e.g. 'lottery game rules'"),
    top: int = Query(8, ge=1, le=50, description="Max results per page"),
    skip: int = Query(0, ge=0, description="Results to skip for pagination"),
    title_filter: str = Query(
        DEFAULT_TITLE_FILTER,
        description="Restrict to OAC title number (e.g. '429'). Pass '' to search all titles.",
    ),
) -> SearchResponse:
    """
    Search OAC rules by keyword. Returns matched rules with citation codes,
    descriptions, and text excerpts.

    Use the returned `segment_id` with `GET /rule/{rule_id}` to fetch full text.
    Paginate with `skip` (e.g. skip=8 for page 2 when top=8).
    """
    cache_key = f"http:search:{query}:{top}:{skip}:{title_filter}"
    if hit := cache.get(cache_key):
        return hit

    try:
        data = await api.search(query, top=top, skip=skip)
    except Exception as e:
        _http_error(e, "Search")

    all_results = data.get("results", [])
    total = data.get("count", 0)

    if title_filter:
        results = [r for r in all_results if r.get("document", {}).get("Title_Number") == title_filter]
    else:
        results = all_results

    items = []
    for r in results:
        doc = r.get("document", {})
        excerpt = _strip_html(doc.get("Text") or "")[:400]
        effective = (doc.get("EffectiveDate") or "")[:10]
        items.append(
            SearchResult(
                segment_id=str(doc.get("Id") or ""),
                description=doc.get("Description") or "",
                citation=doc.get("Section_Number") or "",
                title_number=doc.get("Title_Number") or "",
                display_name=doc.get("DisplayName") or "",
                chapter=(doc.get("ChapterName") or "").strip(),
                effective_date=effective,
                excerpt=excerpt,
                relevance_score=round(r.get("score", 0.0), 4),
                source_url=f"{SEARCH_API_URL}/api/Search",
            )
        )

    shown = skip + len(items)
    next_skip = shown if shown < total else None

    out = SearchResponse(
        query=query,
        title_filter=title_filter,
        total_api_count=total,
        returned_count=len(items),
        results=items,
        next_page_skip=next_skip,
    )
    cache.set(cache_key, out)
    return out


@app.get(
    "/suggest",
    response_model=SuggestResponse,
    summary="Autocomplete suggestions for a partial search term",
    tags=["Rules"],
)
async def suggest(
    query: str = Query(..., description="Partial word or phrase, e.g. 'lott' or 'game pro'"),
    top: int = Query(5, ge=1, le=20, description="Max suggestions to return"),
) -> SuggestResponse:
    """
    Returns autocomplete suggestions. Useful for discovering correct terminology
    before running a full search.
    """
    cache_key = f"http:suggest:{query}:{top}"
    if hit := cache.get(cache_key):
        return hit

    try:
        data = await api.suggest(query, top=top)
    except Exception as e:
        _http_error(e, "Suggest")

    terms = [
        s.get("text") or s.get("queryPlusText") or ""
        for s in data.get("suggestions", [])
        if s.get("text") or s.get("queryPlusText")
    ]
    out = SuggestResponse(query=query, suggestions=terms)
    cache.set(cache_key, out)
    return out


@app.get(
    "/children/{parent_id}",
    response_model=ChildrenResponse,
    summary="Get child segments of any node in the OAC rule tree",
    tags=["Navigation"],
)
async def get_children(
    parent_id: int,
) -> ChildrenResponse:
    """
    Navigates the OAC hierarchy: Title → Chapter → Subchapter → Part → Section.

    Start with a title's segment ID (from `/rules` or `/chapters`) and drill
    down by calling this endpoint on each returned child ID.
    """
    cache_key = f"http:children:{parent_id}"
    if hit := cache.get(cache_key):
        return hit

    try:
        children = await api.get_segments_by_parent_id(parent_id)
    except Exception as e:
        _http_error(e, f"Segment {parent_id}")

    if not children:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No children found for segment {parent_id}. "
                "This may be a leaf node — call GET /rule/{parent_id} to read its text."
            ),
        )

    items = [
        ChildSegment(
            id=ch.get("id") or ch.get("segmentId") or 0,
            title=ch.get("title") or ch.get("description") or ch.get("name") or "Untitled",
            citation=ch.get("referenceCode") or ch.get("citation") or "",
            segment_type=ch.get("segmentType") or ch.get("segmentTypeName") or "",
            source_url=f"{BASE_API_URL}/GetSegmentsByParentId?parentId={parent_id}&includeWIP=false",
        )
        for ch in children
    ]

    out = ChildrenResponse(
        parent_id=parent_id,
        count=len(items),
        children=items,
        source_url=f"{BASE_API_URL}/GetSegmentsByParentId?parentId={parent_id}&includeWIP=false",
    )
    cache.set(cache_key, out)
    return out


@app.get(
    "/rule/{rule_id}",
    response_model=RuleResponse,
    summary="Full text and metadata for a specific rule segment",
    tags=["Rules"],
)
async def get_rule(
    rule_id: int,
) -> RuleResponse:
    """
    Returns the full plain-text content and metadata for a rule.
    Works at any hierarchy level (title, chapter, section).

    Rule/segment IDs are returned by `/search`, `/children`, `/rules`, and `/chapters`.
    """
    cache_key = f"http:rule:{rule_id}"
    if hit := cache.get(cache_key):
        return hit

    try:
        data = await api.get_rule_reference_code(rule_id)
    except Exception as e:
        _http_error(e, f"Rule {rule_id}")

    if isinstance(data, list):
        if not data:
            raise HTTPException(status_code=404, detail=f"Rule {rule_id} returned no data.")
        data = data[0]

    raw_text = (
        data.get("text") or data.get("ruleText") or data.get("content") or data.get("body") or ""
    )

    out = RuleResponse(
        id=rule_id,
        title=data.get("title") or data.get("description") or data.get("name") or "Untitled",
        citation=data.get("referenceCode") or data.get("citation") or str(rule_id),
        segment_type=data.get("segmentType") or data.get("segmentTypeName") or "",
        effective_date=(data.get("effectiveDate") or data.get("lastModified") or "")[:10],
        rule_status=data.get("ruleStatus"),
        record_status=data.get("recordStatus"),
        notes=(data.get("notes") or data.get("additionalInformation") or "").strip(),
        text=_strip_html(raw_text),
        source_url=f"{BASE_API_URL}/GetRuleReferenceCode/{rule_id}",
    )
    cache.set(cache_key, out)
    return out


@app.get(
    "/rules",
    response_model=AllRulesResponse,
    summary="Paginated list of OAC top-level titles",
    tags=["Navigation"],
)
async def get_all_rules(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Results per page"),
    title_filter: str = Query(
        DEFAULT_TITLE_FILTER,
        description="Filter by reference code (e.g. '429'). Pass '' for all OAC titles.",
    ),
) -> AllRulesResponse:
    """
    Lists Oklahoma Administrative Code top-level titles with their segment IDs.
    Use `GET /children/{segment_id}` to navigate into a title's chapters.
    """
    cache_key = f"http:rules:{page}:{page_size}:{title_filter}"
    if hit := cache.get(cache_key):
        return hit

    try:
        rules = await api.get_all_rules(page=page, page_size=page_size)
    except Exception as e:
        _http_error(e, "Rules list")

    if title_filter:
        filtered = [
            r for r in rules
            if str(r.get("referenceCode", "")) == title_filter
            or title_filter.lower() in (r.get("title") or "").lower()
        ]
    else:
        filtered = rules

    items = [
        RuleListItem(
            id=r.get("id") or 0,
            segment_id=r.get("segmentId") or r.get("id") or 0,
            reference_code=str(r.get("referenceCode") or ""),
            title=r.get("title") or "Untitled",
        )
        for r in filtered
    ]

    out = AllRulesResponse(
        page=page,
        page_size=page_size,
        title_filter=title_filter,
        returned_from_api=len(rules),
        matching_filter=len(items),
        rules=items,
        source_url=f"{BASE_API_URL}/GetAllRules?pageNumber={page}&pageSize={page_size}&filter=false",
    )
    cache.set(cache_key, out)
    return out


@app.get(
    "/chapters",
    response_model=ChaptersResponse,
    summary="List all chapters under any OAC title/agency",
    tags=["Navigation"],
)
async def list_chapters(
    title_number: str = Query(
        ...,
        description=(
            "OAC title reference code, e.g. '429' (Oklahoma Lottery Commission), "
            "'310' (State Dept of Health), '340' (Dept of Human Services). "
            "Call GET /titles first to discover all available codes."
        ),
    ),
) -> ChaptersResponse:
    """
    Returns all chapters for any OAC title/agency.

    Use GET /titles to find the reference code for any agency, then pass
    it here to browse that agency's chapters.

    Follow up with `GET /children/{chapter_id}` to see sections within a chapter.
    """
    cache_key = f"http:chapters:{title_number}"
    if hit := cache.get(cache_key):
        return hit

    # Step 1 — find the title
    try:
        all_rules = await api.get_all_rules(page=1, page_size=200)
    except Exception as e:
        _http_error(e, "Rules index")

    matched = next(
        (r for r in all_rules if str(r.get("referenceCode", "")) == title_number),
        None,
    )
    if not matched:
        raise HTTPException(
            status_code=404,
            detail=f"Title {title_number!r} not found. Call GET /titles to see all available codes.",
        )

    seg_id = matched.get("segmentId") or matched.get("id")
    rule_id = matched.get("id")
    title_name = matched.get("title") or f"Title {title_number}"

    # Step 2 — get chapters
    try:
        chapters = await api.get_segments_by_parent_id(seg_id)
    except Exception as e:
        _http_error(e, f"Chapters for segment {seg_id}")

    if not chapters:
        raise HTTPException(
            status_code=404,
            detail=f"{title_name} found (segment {seg_id}) but no chapters returned. Try GET /children/{seg_id}.",
        )

    items = [
        Chapter(
            id=ch.get("id") or ch.get("segmentId") or 0,
            title=ch.get("title") or ch.get("description") or ch.get("name") or "Untitled",
            citation=ch.get("referenceCode") or ch.get("citation") or "",
            segment_type=ch.get("segmentType") or ch.get("segmentTypeName") or "",
        )
        for ch in chapters
    ]

    out = ChaptersResponse(
        title_number=title_number,
        title_name=title_name,
        segment_id=seg_id,
        rule_id=rule_id,
        chapter_count=len(items),
        chapters=items,
        source_url=f"{BASE_API_URL}/GetSegmentsByParentId?parentId={seg_id}&includeWIP=false",
    )
    cache.set(cache_key, out)
    return out


@app.get(
    "/titles",
    response_model=TitlesResponse,
    summary="List all 177 agencies in the Oklahoma Administrative Code",
    tags=["Navigation"],
)
async def list_titles() -> TitlesResponse:
    """
    Returns every OAC title (all 177 state agencies) with reference codes
    and segment IDs.

    Use the `reference_code` with `GET /chapters?title_number=<code>` to
    browse chapters of any agency, or use `GET /search` to search across all.
    """
    cache_key = "http:titles:all"
    if hit := cache.get(cache_key):
        return hit

    try:
        rules = await api.get_all_rules(page=1, page_size=200)
    except Exception as e:
        _http_error(e, "Rules index")

    items = [
        TitleItem(
            reference_code=str(r.get("referenceCode") or ""),
            title=r.get("title") or "Untitled",
            segment_id=r.get("segmentId") or r.get("id") or 0,
            rule_id=r.get("id") or 0,
        )
        for r in rules
    ]

    out = TitlesResponse(
        total_count=len(items),
        titles=items,
        source_url=f"{BASE_API_URL}/GetAllRules?pageNumber=1&pageSize=200&filter=false",
    )
    cache.set(cache_key, out)
    return out


# ── health check ──────────────────────────────────────────────────────────────

@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok", "cache_entries": cache.size()}
