"""
test_server.py — Exercises all 6 MCP tools against the live Oklahoma API.

Prints raw API responses so the data shape is visible, then shows what
each MCP tool returns. Tests happy paths and edge cases.

Usage:
    python test_server.py              # run all tests
    python test_server.py search       # run just the search tests
    python test_server.py rule 45628   # fetch a specific rule ID
"""

import asyncio
import json
import sys
from typing import Any

import api
import cache
from server import (
    search_rules,
    suggest,
    get_children,
    get_rule,
    get_all_rules,
    list_chapters,
)


# ── formatting helpers ───────────────────────────────────────────────────────

DIVIDER = "─" * 72


def header(title: str) -> None:
    print(f"\n{'═' * 72}")
    print(f"  {title}")
    print(f"{'═' * 72}")


def section(label: str) -> None:
    print(f"\n{DIVIDER}")
    print(f"  {label}")
    print(DIVIDER)


def show_raw(label: str, data: Any, max_chars: int = 1200) -> None:
    raw = json.dumps(data, indent=2, default=str)
    if len(raw) > max_chars:
        raw = raw[:max_chars] + f"\n  ... [truncated at {max_chars} chars]"
    print(f"\n[RAW — {label}]")
    print(raw)


def show_tool(label: str, result: str) -> None:
    print(f"\n[TOOL OUTPUT — {label}]")
    print(result)


# ── raw API tests (bypass cache & formatting) ────────────────────────────────

async def test_raw_get_all_rules() -> None:
    section("RAW: GetAllRules (page 1, size 5)")
    data = await api.get_all_rules(page=1, page_size=5)
    show_raw("first 2 items", data[:2])
    print(f"\nTotal items returned (page 1, size 5): {len(data)}")
    print("Field names on first item:", list(data[0].keys()) if data else "N/A")


async def test_raw_find_title_429() -> None:
    section("RAW: Finding Title 429 in GetAllRules (page 1, size 200)")
    data = await api.get_all_rules(page=1, page_size=200)
    matches = [
        r for r in data
        if str(r.get("referenceCode", "")) == "429"
        or "lottery" in (r.get("title") or "").lower()
    ]
    if matches:
        print(f"\nTitle 429 found!  segmentId = {matches[0].get('segmentId')}")
        show_raw("Title 429 rule object", matches[0])
    else:
        print("\nTitle 429 NOT found in first 200 entries.")
        print("First 5 referenceCodes:", [r.get("referenceCode") for r in data[:5]])


async def test_raw_segments(parent_id: int) -> None:
    section(f"RAW: GetSegmentsByParentId(parentId={parent_id})")
    data = await api.get_segments_by_parent_id(parent_id)
    if data:
        print(f"\nChildren found: {len(data)}")
        print("Field names:", list(data[0].keys()))
        show_raw("first child", data[0])
    else:
        print(f"No children returned for parentId={parent_id}")


async def test_raw_rule(rule_id: int) -> None:
    section(f"RAW: GetRuleReferenceCode({rule_id})")
    try:
        data = await api.get_rule_reference_code(rule_id)
        if isinstance(data, list):
            show_raw(f"rule {rule_id} (list[0])", data[0] if data else {})
        else:
            show_raw(f"rule {rule_id}", data)
    except Exception as e:
        print(f"ERROR: {e}")


async def test_raw_search(query: str) -> None:
    section(f"RAW: Search for {query!r}")
    data = await api.search(query, top=3)
    print(f"\nTotal count: {data.get('count')}")
    results = data.get("results", [])
    print(f"Results in page: {len(results)}")
    if results:
        doc = results[0]["document"]
        print("\nDocument field names:", list(doc.keys()))
        # Show first result without the (potentially long) Text field
        compact = {k: v for k, v in doc.items() if k != "Text"}
        show_raw("first result (no Text)", compact)
        text_preview = (doc.get("Text") or "")[:400]
        print(f"\nText preview:\n{text_preview}")
    facets = data.get("facets", {})
    if facets:
        print("\nFacet keys:", list(facets.keys()))
        dn = facets.get("DisplayName", [])[:5]
        print("DisplayName facets (top 5):", json.dumps(dn, indent=2))


async def test_raw_suggest(query: str) -> None:
    section(f"RAW: Suggest for {query!r}")
    data = await api.suggest(query, top=5)
    show_raw("suggestions", data)


# ── MCP tool tests ───────────────────────────────────────────────────────────

async def test_tool_search_rules() -> None:
    section("TOOL: search_rules('lottery game', title_filter='429')")
    result = await search_rules("lottery game", top=5)
    show_tool("search_rules — Title 429", result)

    section("TOOL: search_rules('rules', title_filter='') — all OAC titles")
    cache.clear()
    result = await search_rules("rules", top=4, title_filter="")
    show_tool("search_rules — all titles", result)

    section("TOOL: search_rules — edge case: no results")
    cache.clear()
    result = await search_rules("xyzzy_nonexistent_term_99999")
    show_tool("search_rules — no results", result)


async def test_tool_suggest() -> None:
    section("TOOL: suggest('lott')")
    result = await suggest("lott")
    show_tool("suggest('lott')", result)

    section("TOOL: suggest — very short term")
    cache.clear()
    result = await suggest("ga", top=3)
    show_tool("suggest('ga')", result)


async def test_tool_get_all_rules() -> None:
    section("TOOL: get_all_rules(title_filter='429')")
    result = await get_all_rules(title_filter="429")
    show_tool("get_all_rules — Title 429", result)

    section("TOOL: get_all_rules(title_filter='') — first 10 OAC titles")
    cache.clear()
    result = await get_all_rules(page_size=10, title_filter="")
    show_tool("get_all_rules — all titles (10)", result)


async def test_tool_list_chapters() -> None:
    section("TOOL: list_chapters()")
    result = await list_chapters()
    show_tool("list_chapters", result)


async def test_tool_get_children(parent_id: int) -> None:
    section(f"TOOL: get_children({parent_id})")
    cache.clear()
    result = await get_children(parent_id)
    show_tool(f"get_children({parent_id})", result)


async def test_tool_get_rule(rule_id: int) -> None:
    section(f"TOOL: get_rule({rule_id})")
    cache.clear()
    result = await get_rule(rule_id)
    show_tool(f"get_rule({rule_id})", result)


async def test_edge_cases() -> None:
    header("EDGE CASES")

    section("get_children — invalid parent ID")
    cache.clear()
    result = await get_children(99_999_999)
    show_tool("get_children(99999999)", result)

    section("get_rule — invalid rule ID")
    cache.clear()
    result = await get_rule(99_999_999)
    show_tool("get_rule(99999999)", result)

    section("search_rules — title_filter for non-existent title")
    cache.clear()
    result = await search_rules("lottery", title_filter="000")
    show_tool("search_rules — title '000'", result)

    section("suggest — term with no matches")
    cache.clear()
    result = await suggest("zzzzqqqqwwww")
    show_tool("suggest — no matches", result)


# ── drill-down integration test ───────────────────────────────────────────────

async def test_drill_down() -> None:
    """
    Full tree walk: list_chapters → pick first chapter → get_children →
    pick first child → get_rule.
    Demonstrates the complete navigation pattern.
    """
    header("INTEGRATION: Title 429 Tree Walk")

    # Step 1: list chapters
    section("Step 1 — list_chapters()")
    cache.clear()
    chapters_text = await list_chapters()
    show_tool("list_chapters", chapters_text)

    # Step 2: extract first chapter ID from the tool output
    import re
    ch_ids = re.findall(r"Chapter ID:\s*(\d+)", chapters_text)
    if not ch_ids:
        print("\nCould not parse chapter IDs from list_chapters output — stopping drill-down.")
        return

    first_chapter_id = int(ch_ids[0])
    section(f"Step 2 — get_children({first_chapter_id}) [first chapter]")
    cache.clear()
    children_text = await get_children(first_chapter_id)
    show_tool(f"get_children({first_chapter_id})", children_text)

    # Step 3: pick first child ID
    child_ids = re.findall(r"ID\s+(\d+)\s+\|", children_text)
    if not child_ids:
        print("\nCould not parse child IDs — stopping drill-down.")
        return

    first_child_id = int(child_ids[0])
    section(f"Step 3 — get_rule({first_child_id}) [first child segment]")
    cache.clear()
    rule_text = await get_rule(first_child_id)
    show_tool(f"get_rule({first_child_id})", rule_text)


# ── entry point ───────────────────────────────────────────────────────────────

async def main(args: list[str]) -> None:
    mode = args[0].lower() if args else "all"

    if mode == "all":
        header("Oklahoma Administrative Rules — Full Test Suite")

        # Raw API inspection
        header("1/3 — RAW API RESPONSES")
        await test_raw_get_all_rules()
        await test_raw_find_title_429()
        await test_raw_search("lottery")
        await test_raw_suggest("lott")
        # Segments: try IDs 1, 2, 3 to discover which is Title 429's parent
        for pid in [1, 2, 3]:
            await test_raw_segments(pid)
        await test_raw_rule(45628)   # known good ID from search results

        # MCP tool outputs
        header("2/3 — MCP TOOL OUTPUTS")
        await test_tool_search_rules()
        await test_tool_suggest()
        await test_tool_get_all_rules()
        await test_tool_list_chapters()
        # After list_chapters we know a real chapter ID — use dynamic drill-down
        await test_tool_get_rule(45628)

        # Edge cases
        await test_edge_cases()

        # Integration / drill-down
        header("3/3 — INTEGRATION DRILL-DOWN")
        await test_drill_down()

    elif mode == "search":
        query = " ".join(args[1:]) if len(args) > 1 else "lottery"
        header(f"Search test: {query!r}")
        await test_raw_search(query)
        cache.clear()
        result = await search_rules(query)
        show_tool("search_rules", result)

    elif mode == "rule":
        rule_id = int(args[1]) if len(args) > 1 else 45628
        header(f"Rule test: ID {rule_id}")
        await test_raw_rule(rule_id)
        cache.clear()
        result = await get_rule(rule_id)
        show_tool("get_rule", result)

    elif mode == "children":
        parent_id = int(args[1]) if len(args) > 1 else 1
        header(f"Children test: parentId={parent_id}")
        await test_raw_segments(parent_id)
        cache.clear()
        result = await get_children(parent_id)
        show_tool("get_children", result)

    elif mode == "chapters":
        header("list_chapters test")
        await test_raw_find_title_429()
        cache.clear()
        result = await list_chapters()
        show_tool("list_chapters", result)

    elif mode == "drill":
        await test_drill_down()

    elif mode == "edge":
        await test_edge_cases()

    else:
        print(f"Unknown mode: {mode!r}")
        print("Usage: python test_server.py [all|search [query]|rule [id]|children [id]|chapters|drill|edge]")
        sys.exit(1)

    print(f"\n{'═' * 72}")
    print("  Test suite complete.")
    print(f"{'═' * 72}\n")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
