"""
Oklahoma Administrative Rules — FastMCP server

Provides live access to the full Oklahoma Administrative Code (OAC) —
all 177 agencies — via the official state API.

Transport: stdio (for Claude Desktop / MCP clients)
"""

import re
import httpx
from fastmcp import FastMCP

import api
import cache
from constants import (
    BASE_API_URL,
    SEARCH_API_URL,
    DEFAULT_TITLE_FILTER,
    MAX_RESPONSE_CHARS,
)

mcp = FastMCP(
    "Oklahoma Administrative Rules",
    instructions=(
        "Provides live access to the full Oklahoma Administrative Code (OAC) — "
        "all 177 state agencies. "
        "Use list_titles() to see all agencies, list_chapters(title_number) to browse "
        "chapters of a specific title, search_rules() to find content by keyword, "
        "get_rule() to read full text, and get_children() to navigate the rule tree."
    ),
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _truncate(text: str, limit: int = MAX_RESPONSE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return (
        text[:limit]
        + f"\n\n[Truncated at {limit} chars. Use pagination or a narrower query to see more.]"
    )


_HTML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    text = _HTML_TAG.sub(" ", html or "")
    return _WHITESPACE.sub(" ", text).strip()


def _source_line(url: str) -> str:
    return f"Source: {url}"


# ── tool 1: search_rules ─────────────────────────────────────────────────────

@mcp.tool()
async def search_rules(
    query: str,
    top: int = 8,
    skip: int = 0,
    title_filter: str = DEFAULT_TITLE_FILTER,
) -> str:
    """
    Full-text search across Oklahoma Administrative Code rules.

    Defaults to Title 429 (Oklahoma Lottery Commission). Pass
    title_filter="" to search the entire OAC.

    Args:
        query:        Search term or phrase (e.g. "lottery game rules").
        top:          Max results to return per page (default 8, max ~50).
        skip:         Results to skip — use for pagination (default 0).
        title_filter: Restrict to a specific OAC title number, e.g. "429".
                      Pass "" to search all titles.

    Returns matched rules with citation codes, descriptions, and text excerpts.
    Use get_rule(id) with the returned Segment ID for the full rule text.
    """
    cache_key = f"search:{query}:{top}:{skip}:{title_filter}"
    if hit := cache.get(cache_key):
        return hit

    try:
        data = await api.search(query, top=top, skip=skip)
    except httpx.HTTPStatusError as e:
        return (
            f"Search API returned HTTP {e.response.status_code}.\n"
            f"Query: {query!r}\n"
            "Try a shorter query or check that the Search API is reachable."
        )
    except httpx.RequestError as e:
        return f"Network error reaching the Search API: {e}\nCheck your internet connection."

    all_results = data.get("results", [])
    total_api = data.get("count", 0)

    # Client-side filter by Title_Number (API filters field may not be OData-style)
    if title_filter:
        results = [
            r for r in all_results
            if r.get("document", {}).get("Title_Number") == title_filter
        ]
    else:
        results = all_results

    if not results:
        hint = (
            f' in Title {title_filter}. Try title_filter="" to search all OAC titles.'
            if title_filter
            else "."
        )
        return f'No results found for "{query}"{hint}'

    lines = [
        f'Search: "{query}"',
        f"Total API matches: {total_api}"
        + (f"  |  Shown (Title {title_filter} only): {len(results)}" if title_filter else ""),
        _source_line(f"{SEARCH_API_URL}/api/Search"),
        "",
    ]

    for i, result in enumerate(results, 1):
        doc = result.get("document", {})
        score = result.get("score", 0.0)
        description = doc.get("Description") or "No description"
        section = doc.get("Section_Number") or "N/A"
        display = doc.get("DisplayName") or ""
        chapter = (doc.get("ChapterName") or "").strip()
        seg_id = doc.get("Id") or ""
        effective = doc.get("EffectiveDate") or ""
        raw_text = doc.get("Text") or ""
        excerpt = _strip_html(raw_text)[:300]

        lines.append(f"{i}. {description}")
        lines.append(f"   Citation:    {section}")
        if display:
            lines.append(f"   Title:       {display}")
        if chapter:
            lines.append(f"   Chapter:     {chapter}")
        if effective:
            # Trim to date portion only
            lines.append(f"   Effective:   {effective[:10]}")
        if excerpt:
            lines.append(f"   Excerpt:     {excerpt}…")
        if seg_id:
            lines.append(f"   Segment ID:  {seg_id}  →  use get_rule({seg_id}) for full text")
        lines.append(f"   Score:       {score:.2f}")
        lines.append("")

    shown_so_far = skip + len(results)
    if shown_so_far < total_api:
        lines.append(
            f"[Page {skip // top + 1} of ~{-(-total_api // top)}. "
            f"Use skip={skip + top} for the next page.]"
        )

    out = _truncate("\n".join(lines))
    cache.set(cache_key, out)
    return out


# ── tool 2: suggest ──────────────────────────────────────────────────────────

@mcp.tool()
async def suggest(query: str, top: int = 5) -> str:
    """
    Autocomplete suggestions for a partial search term.

    Useful for discovering correct terminology before running a full search.

    Args:
        query: Partial word or phrase (e.g. "lott", "game pro").
        top:   Max suggestions to return (default 5).

    Returns a list of suggested complete terms.
    """
    cache_key = f"suggest:{query}:{top}"
    if hit := cache.get(cache_key):
        return hit

    try:
        data = await api.suggest(query, top=top)
    except httpx.HTTPStatusError as e:
        return f"Suggest API returned HTTP {e.response.status_code} for query {query!r}."
    except httpx.RequestError as e:
        return f"Network error reaching Suggest API: {e}"

    suggestions = data.get("suggestions", [])

    if not suggestions:
        return (
            f'No suggestions found for "{query}".\n'
            "Try a shorter prefix or a different starting word."
        )

    lines = [f'Suggestions for "{query}":', ""]
    for s in suggestions:
        term = s.get("text") or s.get("queryPlusText") or ""
        if term:
            lines.append(f"  • {term}  →  try search_rules({term!r})")

    lines.append(f"\n{_source_line(f'{SEARCH_API_URL}/api/Suggest')}")

    out = "\n".join(lines)
    cache.set(cache_key, out)
    return out


# ── tool 3: get_children ─────────────────────────────────────────────────────

@mcp.tool()
async def get_children(parent_id: int) -> str:
    """
    Get the immediate child segments of any node in the rule tree.

    The OAC hierarchy is: Title → Chapter → Subchapter → Part → Section.
    Start from a title's segment ID (use get_all_rules() or list_chapters()
    to find IDs) and drill down by calling get_children() on each level.

    Args:
        parent_id: Integer segment ID of the parent node.

    Returns child segments with their IDs, titles, and citation codes.
    """
    cache_key = f"children:{parent_id}"
    if hit := cache.get(cache_key):
        return hit

    try:
        children = await api.get_segments_by_parent_id(parent_id)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 404:
            return (
                f"No segment found with ID {parent_id} (HTTP 404).\n"
                "Verify the ID using get_all_rules() or search_rules()."
            )
        return f"API returned HTTP {status} for parent_id={parent_id}."
    except httpx.RequestError as e:
        return f"Network error: {e}"

    if not children:
        return (
            f"No children found for segment {parent_id}.\n"
            f"This is likely a leaf node (section level). "
            f"Use get_rule({parent_id}) to read its full text."
        )

    lines = [
        f"Children of segment {parent_id}",
        f"Count: {len(children)}",
        _source_line(
            f"{BASE_API_URL}/GetSegmentsByParentId?parentId={parent_id}&includeWIP=false"
        ),
        "",
    ]

    for child in children:
        cid = child.get("id") or child.get("segmentId") or "?"
        title = (
            child.get("title")
            or child.get("description")
            or child.get("name")
            or "Untitled"
        )
        ref = child.get("referenceCode") or child.get("citation") or ""
        seg_type = child.get("segmentType") or child.get("segmentTypeName") or ""
        notes = (child.get("notes") or child.get("additionalInformation") or "").strip()

        lines.append(f"  ID {cid}  |  {title}")
        if ref:
            lines.append(f"           Citation:  {ref}")
        if seg_type:
            lines.append(f"           Type:      {seg_type}")
        if notes:
            lines.append(f"           Notes:     {notes[:120]}")
        lines.append(f"           → get_children({cid}) to go deeper")
        lines.append(f"           → get_rule({cid}) for text at this node")
        lines.append("")

    out = _truncate("\n".join(lines))
    cache.set(cache_key, out)
    return out


# ── tool 4: get_rule ─────────────────────────────────────────────────────────

@mcp.tool()
async def get_rule(rule_id: int) -> str:
    """
    Fetch the full text and metadata for a specific rule or rule segment.

    Works at any level of the hierarchy — Title, Chapter, or Section.
    Segment IDs are returned by search_rules(), get_children(), get_all_rules(),
    and list_chapters().

    Args:
        rule_id: Integer segment/rule ID.

    Returns the full rule text (HTML stripped), citation, type, and status.
    """
    cache_key = f"rule:{rule_id}"
    if hit := cache.get(cache_key):
        return hit

    try:
        data = await api.get_rule_reference_code(rule_id)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 404:
            return (
                f"Rule ID {rule_id} not found (HTTP 404).\n"
                "Use search_rules() to locate valid IDs, or get_children() to browse."
            )
        return f"API returned HTTP {status} for rule_id={rule_id}."
    except httpx.RequestError as e:
        return f"Network error fetching rule {rule_id}: {e}"

    # API may return a list with one item or a bare dict
    if isinstance(data, list):
        if not data:
            return f"Rule ID {rule_id} returned an empty response from the API."
        data = data[0]

    if not isinstance(data, dict):
        return f"Unexpected response type for rule {rule_id}: {type(data).__name__}"

    title = (
        data.get("title")
        or data.get("description")
        or data.get("name")
        or "Untitled"
    )
    ref = data.get("referenceCode") or data.get("citation") or str(rule_id)
    seg_type = data.get("segmentType") or data.get("segmentTypeName") or ""
    rule_status = data.get("ruleStatus")
    record_status = data.get("recordStatus")
    effective = data.get("effectiveDate") or data.get("lastModified") or ""
    notes = (data.get("notes") or data.get("additionalInformation") or "").strip()

    raw_text = (
        data.get("text")
        or data.get("ruleText")
        or data.get("content")
        or data.get("body")
        or ""
    )
    plain_text = _strip_html(raw_text)

    lines = [
        f"Rule: {title}",
        f"Citation: {ref}",
        f"Segment ID: {rule_id}",
        _source_line(f"{BASE_API_URL}/GetRuleReferenceCode/{rule_id}"),
    ]
    if seg_type:
        lines.append(f"Type: {seg_type}")
    if effective:
        lines.append(f"Effective: {effective[:10]}")
    if rule_status is not None:
        lines.append(f"Rule Status: {rule_status}")
    if record_status is not None:
        lines.append(f"Record Status: {record_status}")
    if notes:
        lines.append(f"Notes: {notes[:200]}")

    lines.append("")

    if plain_text:
        lines.append("Full Text:")
        lines.append("----------")
        lines.append(plain_text)
    else:
        lines.append(
            "[No text content at this node — it may be a structural container.]\n"
            f"Use get_children({rule_id}) to see sub-sections."
        )

    out = _truncate("\n".join(lines))
    cache.set(cache_key, out)
    return out


# ── tool 5: get_all_rules ────────────────────────────────────────────────────

@mcp.tool()
async def get_all_rules(
    page: int = 1,
    page_size: int = 50,
    title_filter: str = DEFAULT_TITLE_FILTER,
) -> str:
    """
    Paginated list of Oklahoma Administrative Code top-level titles/rules.

    Defaults to filtering on Title 429 (Oklahoma Lottery Commission).
    Pass title_filter="" to see all OAC titles across the full code.

    Args:
        page:         Page number, starting at 1 (default 1).
        page_size:    Results per page, 1–200 (default 50).
        title_filter: Match against referenceCode, e.g. "429". Pass "" for all.

    Returns a list of rules with their IDs, titles, and segment IDs.
    Use get_children(segment_id) to navigate into a title's chapters.
    """
    cache_key = f"all_rules:{page}:{page_size}:{title_filter}"
    if hit := cache.get(cache_key):
        return hit

    try:
        rules = await api.get_all_rules(page=page, page_size=page_size)
    except httpx.HTTPStatusError as e:
        return f"API returned HTTP {e.response.status_code} for GetAllRules."
    except httpx.RequestError as e:
        return f"Network error fetching rules list: {e}"

    if not rules:
        return f"No rules returned for page={page}, page_size={page_size}."

    if title_filter:
        filtered = [
            r for r in rules
            if str(r.get("referenceCode", "")) == title_filter
            or title_filter.lower() in (r.get("title") or "").lower()
        ]
    else:
        filtered = rules

    filter_label = repr(title_filter) if title_filter else "(none - all titles)"
    lines = [
        "Oklahoma Administrative Code - Rules Index",
        f"Page {page}  |  Page size: {page_size}  |  Returned from API: {len(rules)}",
        f"Filter: {filter_label}  |  Matching: {len(filtered)}",
        _source_line(
            f"{BASE_API_URL}/GetAllRules?pageNumber={page}&pageSize={page_size}&filter=false"
        ),
        "",
    ]

    if not filtered:
        lines.append(
            f"No rules matched title_filter={title_filter!r} on page {page}.\n"
            "Try a higher page number, or pass title_filter=\"\" to see all titles.\n"
            f"Available referenceCode values on this page: "
            + ", ".join(str(r.get("referenceCode", "?")) for r in rules[:20])
        )
    else:
        for rule in filtered:
            rid = rule.get("id", "?")
            seg_id = rule.get("segmentId", "?")
            ref = rule.get("referenceCode", "")
            title = rule.get("title") or "Untitled"
            notes = (rule.get("notes") or rule.get("additionalInformation") or "").strip()

            lines.append(f"  ID: {rid}  |  Ref: {ref}  |  Segment ID: {seg_id}")
            lines.append(f"  Title: {title}")
            if notes:
                lines.append(f"  Notes: {notes[:120]}")
            lines.append(f"  → get_children({seg_id}) to browse chapters")
            lines.append(f"  → get_rule({rid}) for details")
            lines.append("")

    out = _truncate("\n".join(lines))
    cache.set(cache_key, out)
    return out


# ── tool 6: list_chapters ────────────────────────────────────────────────────

@mcp.tool()
async def list_chapters(title_number: str) -> str:
    """
    List all chapters under any OAC title/agency.

    Looks up the title by its reference code, then fetches its direct
    children (chapters) from the API.

    Args:
        title_number: OAC title reference code, e.g. "429" for Oklahoma
                      Lottery Commission, "310" for State Dept of Health,
                      "340" for Dept of Human Services. Use list_titles()
                      to discover all available title numbers.

    Returns each chapter with its ID, title, and citation code.
    Use get_children(chapter_id) to drill into sections within a chapter.
    """
    cache_key = f"list_chapters:{title_number}"
    if hit := cache.get(cache_key):
        return hit

    # ── Step 1: locate the title in GetAllRules ──────────────────────────────
    try:
        all_rules = await api.get_all_rules(page=1, page_size=200)
    except httpx.HTTPStatusError as e:
        return f"Failed to fetch the rules index (HTTP {e.response.status_code})."
    except httpx.RequestError as e:
        return f"Network error fetching rules index: {e}"

    matched: dict | None = None
    for rule in all_rules:
        if str(rule.get("referenceCode", "")) == title_number:
            matched = rule
            break

    if not matched:
        refs = ", ".join(str(r.get("referenceCode", "?")) for r in all_rules[:30])
        return (
            f"Title {title_number!r} not found in the rules index.\n"
            f"Sample reference codes: {refs}\n"
            "Use list_titles() to see all available title numbers."
        )

    seg_id = matched.get("segmentId") or matched.get("id")
    title_name = matched.get("title") or f"Title {title_number}"
    rule_id = matched.get("id")

    # ── Step 2: fetch children (chapters) ────────────────────────────────────
    try:
        chapters = await api.get_segments_by_parent_id(seg_id)
    except httpx.HTTPStatusError as e:
        return (
            f"Found {title_name} (segment ID {seg_id}) but chapter fetch returned "
            f"HTTP {e.response.status_code}.\n"
            f"Try get_children({seg_id}) directly."
        )
    except httpx.RequestError as e:
        return f"Network error fetching chapters for segment {seg_id}: {e}"

    if not chapters:
        return (
            f"{title_name} found (ID: {rule_id}, segment ID: {seg_id}) but no chapters returned.\n"
            f"Try get_children({seg_id}) directly, or get_rule({rule_id}) for metadata."
        )

    lines = [
        f"Chapters of {title_name}",
        f"OAC Title {title_number}  |  Segment ID: {seg_id}  |  Rule ID: {rule_id}",
        f"Chapters found: {len(chapters)}",
        _source_line(
            f"{BASE_API_URL}/GetSegmentsByParentId?parentId={seg_id}&includeWIP=false"
        ),
        "",
    ]

    for ch in chapters:
        ch_id = ch.get("id") or ch.get("segmentId") or "?"
        ch_title = (
            ch.get("title") or ch.get("description") or ch.get("name") or "Untitled"
        )
        ch_ref = ch.get("referenceCode") or ch.get("citation") or ""
        ch_type = ch.get("segmentType") or ch.get("segmentTypeName") or ""
        ch_notes = (ch.get("notes") or ch.get("additionalInformation") or "").strip()

        lines.append(f"  Chapter ID: {ch_id}  |  {ch_title}")
        if ch_ref:
            lines.append(f"              Citation:  {ch_ref}")
        if ch_type:
            lines.append(f"              Type:      {ch_type}")
        if ch_notes:
            lines.append(f"              Notes:     {ch_notes[:120]}")
        lines.append(f"              → get_children({ch_id}) to see sections")
        lines.append(f"              → get_rule({ch_id}) for chapter text")
        lines.append("")

    out = _truncate("\n".join(lines))
    cache.set(cache_key, out)
    return out


# ── tool 7: list_titles ───────────────────────────────────────────────────────

@mcp.tool()
async def list_titles() -> str:
    """
    List all 177 agencies/titles in the Oklahoma Administrative Code.

    Returns every OAC title with its reference code, name, and segment ID.
    Use the reference code with list_chapters(title_number) to browse
    chapters of any agency, or use search_rules(query) to search across all.
    """
    cache_key = "list_titles:all"
    if hit := cache.get(cache_key):
        return hit

    try:
        rules = await api.get_all_rules(page=1, page_size=200)
    except httpx.HTTPStatusError as e:
        return f"Failed to fetch rules index (HTTP {e.response.status_code})."
    except httpx.RequestError as e:
        return f"Network error: {e}"

    lines = [
        "Oklahoma Administrative Code — All Agencies",
        f"Total titles: {len(rules)}",
        _source_line(f"{BASE_API_URL}/GetAllRules?pageNumber=1&pageSize=200&filter=false"),
        "",
    ]

    for rule in rules:
        ref = rule.get("referenceCode", "?")
        title = rule.get("title") or "Untitled"
        seg_id = rule.get("segmentId") or rule.get("id") or "?"
        lines.append(f"  [{ref:>4}]  {title}")
        lines.append(f"           Segment ID: {seg_id}  → list_chapters({ref!r})")
        lines.append("")

    out = _truncate("\n".join(lines))
    cache.set(cache_key, out)
    return out


# ── entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
