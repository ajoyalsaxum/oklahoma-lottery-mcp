# Oklahoma Administrative Rules — Technical Documentation

## Overview

This project provides two interfaces to the Oklahoma Administrative Code (OAC):

1. **`server.py`** — A FastMCP server (stdio transport) for Claude Desktop / MCP clients
2. **`http_server.py`** — A FastAPI HTTP server for Custom GPT Actions and REST clients

Both share the same underlying HTTP client (`api.py`) and in-memory cache (`cache.py`).
Neither requires authentication — the Oklahoma state APIs are fully open.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Client Layer                       │
│  Claude Desktop (MCP)     Custom GPT (HTTP Actions)  │
└────────────┬──────────────────────┬─────────────────┘
             │ stdio                │ HTTPS
             ▼                      ▼
┌────────────────┐        ┌──────────────────────┐
│   server.py    │        │   http_server.py      │
│   (FastMCP)    │        │   (FastAPI/uvicorn)   │
└────────┬───────┘        └──────────┬────────────┘
         │                           │
         └──────────┬────────────────┘
                    ▼
         ┌──────────────────┐
         │     cache.py     │  in-memory dict, process-scoped
         └──────────────────┘
                    │ miss
                    ▼
         ┌──────────────────┐
         │     api.py       │  async httpx calls
         └──────────────────┘
                    │
         ┌──────────┴──────────┐
         ▼                     ▼
┌─────────────────┐   ┌────────────────────────────┐
│ okadminrules-   │   │ oksearchrules.azurewebsites │
│ api.azurewebsit │   │ .net  (Azure Cognitive      │
│ es.net          │   │  Search)                    │
│ (Rules API)     │   │                             │
└─────────────────┘   └────────────────────────────┘
```

---

## File reference

| File | Purpose |
|---|---|
| `server.py` | FastMCP server — 7 MCP tools |
| `http_server.py` | FastAPI HTTP server — 7 REST endpoints + health check |
| `api.py` | All `httpx` async calls to the two Oklahoma APIs |
| `cache.py` | Simple in-memory dict cache, keyed by function+args |
| `constants.py` | Base URLs, defaults, field-name documentation |
| `test_server.py` | CLI test suite — exercises all tools against the live API |
| `Dockerfile` | Builds `http_server.py` for deployment |
| `render.yaml` | One-click Render.com deploy config |
| `.python-version` | Pins Python 3.11 for pyenv/uv |

---

## Oklahoma State API reference

### Rules API

Base URL: `https://okadminrules-api.azurewebsites.net`

Authentication: none

#### `GET /GetAllRules`

Returns a flat list of all OAC top-level titles.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `pageNumber` | int | 1 | Page number (1-based) |
| `pageSize` | int | 50 | Results per page (max observed: 200) |
| `filter` | bool | false | Unknown effect; always pass `false` |

**Response:** JSON array of rule objects.

```json
[
  {
    "id": 429,
    "title": "Oklahoma Lottery Commission",
    "referenceCode": "429",
    "segmentId": 429,
    "contactIds": {
      "liaison": 771,
      "altLiaisons": [],
      "attOfficers": [706],
      "cabinetSecretary": 588
    },
    "ruleTypeId": 3,
    "notes": null,
    "additionalInformation": null,
    "ruleStatus": 0,
    "recordStatus": 0,
    "createdBy": null,
    "created": "2024-01-12T14:33:45.9523728",
    "lastModifiedBy": "1",
    "lastModified": "2024-01-12T14:33:45.9523728"
  }
]
```

**Key fields:**

| Field | Type | Notes |
|---|---|---|
| `id` | int | Rule/title ID. Pass to `GetRuleReferenceCode`. |
| `referenceCode` | string | OAC title number (e.g. `"429"`). Use for filtering. |
| `segmentId` | int | Segment tree ID. Pass to `GetSegmentsByParentId` to get chapters. |
| `title` | string | Human-readable agency name |
| `ruleStatus` | int | 0 = active |
| `recordStatus` | int | 0 = active |

---

#### `GET /GetSegmentsByParentId`

Returns the immediate children of any node in the OAC rule tree.
The hierarchy is: **Title → Chapter → Subchapter → Part → Section**.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `parentId` | int | required | Segment ID of the parent node |
| `includeWIP` | bool | false | Include work-in-progress rules |

**Response:** JSON array of segment objects (same shape as `GetAllRules` items), or `null` for leaf nodes.

**Navigation pattern:**
```
GetAllRules          → find title, get segmentId
GetSegmentsByParentId(segmentId)   → chapters
GetSegmentsByParentId(chapterId)   → subchapters or sections
GetSegmentsByParentId(sectionId)   → null (leaf)
GetRuleReferenceCode(sectionId)    → full text
```

---

#### `GET /GetRuleReferenceCode/{id}`

Returns full text and metadata for any rule segment.

**Path parameter:** `id` — integer segment or rule ID

**Response:** Single object or single-element array (handle both):

```json
{
  "id": 45628,
  "title": "Lottery Game Promotion Procedures",
  "referenceCode": "429:15-1-14",
  "text": "<div>...</div>",
  "segmentType": "Section",
  "ruleStatus": 0,
  "recordStatus": 0,
  "effectiveDate": "2025-07-11T14:55:03.000Z",
  "notes": null,
  "additionalInformation": null
}
```

**Note:** The `text` field contains HTML. The servers strip it with
`_strip_html()` before returning to clients.

---

#### `GET /GetContactById/{id}`

Returns contact information for an agency liaison or attorney.

**Path parameter:** `id` — integer contact ID (found in `contactIds` fields from `GetAllRules`)

Not currently exposed as an MCP tool or HTTP endpoint, but available in `api.py`.

---

### Search API

Base URL: `https://oksearchrules.azurewebsites.net`

Authentication: none

This is an Azure Cognitive Search instance.

---

#### `POST /api/Search`

Full-text search across all published OAC rule sections.

**Request body:**

```json
{
  "q": "lottery game rules",
  "top": 8,
  "skip": 0,
  "filters": [],
  "highlight": [""]
}
```

| Field | Type | Description |
|---|---|---|
| `q` | string | Search query |
| `top` | int | Max results to return |
| `skip` | int | Offset for pagination |
| `filters` | array | OData filter expressions (see note below) |
| `highlight` | array | Fields to highlight in results |

**Filters note:** The `filters` array accepts OData-style expressions, but
client-side filtering on `Title_Number` is used in this project for
reliability.

**Response:**

```json
{
  "count": 96,
  "results": [
    {
      "score": 40.12,
      "document": {
        "Id": "45628",
        "Description": "Lottery Game Promotion Procedures",
        "DisplayName": "Title 429. Oklahoma Lottery Commission",
        "ChapterName": "Lottery Games",
        "SubChapterName": null,
        "PartName": null,
        "RuleId": null,
        "TitleName": "Oklahoma Lottery Commission",
        "SegmentTypeName": "Section",
        "Title_Number": "429",
        "Chapter_Number": "15",
        "SubChapterNum": null,
        "Section_Number": "429:15-1-14",
        "ParentId": 429,
        "Level": 2,
        "EffectiveDate": "2025-07-11T14:55:03.000Z",
        "Text": "<div>...</div>"
      }
    }
  ],
  "facets": {
    "DisplayName": [{"count": 69, "value": "Title 429. Oklahoma Lottery Commission"}],
    "Section_Number": [...],
    "Chapter_Number": [...]
  }
}
```

**Key document fields:**

| Field | Notes |
|---|---|
| `Id` | Segment ID as string. Convert to int for `GetRuleReferenceCode`. |
| `Title_Number` | String title number — use for client-side filtering |
| `Section_Number` | Full OAC citation (e.g. `"429:15-1-14"`) |
| `Description` | Section title / human-readable name |
| `Text` | Full rule text as HTML |
| `EffectiveDate` | ISO 8601 datetime |
| `score` | Relevance score (higher = more relevant) |

---

#### `POST /api/Suggest`

Autocomplete suggestions for partial search terms.

**Request body:**

```json
{
  "q": "lott",
  "top": 5,
  "suggester": "Id"
}
```

**Response:**

```json
{
  "suggestions": [
    {"text": "lottery", "queryPlusText": "lottery"},
    {"text": "lotteries", "queryPlusText": "lotteries"}
  ]
}
```

---

## HTTP server endpoints

Base URL (production): `https://ok-lottery-rules.onrender.com`

Interactive docs: `https://ok-lottery-rules.onrender.com/docs`

OpenAPI schema: `https://ok-lottery-rules.onrender.com/openapi.json`

All endpoints return JSON. Errors use standard HTTP status codes with a
`{"detail": "..."}` body.

---

### `GET /search`

Full-text search across the OAC.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | string | required | Search term |
| `top` | int | 8 | Max results (1–50) |
| `skip` | int | 0 | Pagination offset |
| `title_filter` | string | `""` | Restrict to a title number. Pass `""` for all. |

**Response:** `SearchResponse`

```json
{
  "query": "scratch ticket",
  "title_filter": "429",
  "total_api_count": 14,
  "returned_count": 8,
  "next_page_skip": 8,
  "results": [
    {
      "segment_id": "45628",
      "description": "Lottery Game Promotion Procedures",
      "citation": "429:15-1-14",
      "title_number": "429",
      "display_name": "Title 429. Oklahoma Lottery Commission",
      "chapter": "Lottery Games",
      "effective_date": "2025-07-11",
      "excerpt": "...",
      "relevance_score": 40.1183,
      "source_url": "https://oksearchrules.azurewebsites.net/api/Search"
    }
  ]
}
```

---

### `GET /suggest`

Autocomplete for partial terms.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | string | required | Partial term |
| `top` | int | 5 | Max suggestions (1–20) |

**Response:** `SuggestResponse`

```json
{
  "query": "lott",
  "suggestions": ["lottery", "lotteries", "lottery's", "lotto"]
}
```

---

### `GET /children/{parent_id}`

Get child segments of any rule tree node.

**Path parameter:** `parent_id` — integer segment ID

**Response:** `ChildrenResponse`

```json
{
  "parent_id": 429,
  "count": 12,
  "children": [
    {
      "id": 5820,
      "title": "Chapter 1. General Provisions",
      "citation": "429:1",
      "segment_type": "Chapter",
      "source_url": "https://okadminrules-api.azurewebsites.net/..."
    }
  ],
  "source_url": "https://okadminrules-api.azurewebsites.net/..."
}
```

**404:** Returned when the segment has no children (leaf node). Use `GET /rule/{id}` instead.

---

### `GET /rule/{rule_id}`

Full text and metadata for a specific rule.

**Path parameter:** `rule_id` — integer

**Response:** `RuleResponse`

```json
{
  "id": 45628,
  "title": "Lottery Game Promotion Procedures",
  "citation": "429:15-1-14",
  "segment_type": "Section",
  "effective_date": "2025-07-11",
  "rule_status": 0,
  "record_status": 0,
  "notes": "",
  "text": "Full plain-text content of the rule...",
  "source_url": "https://okadminrules-api.azurewebsites.net/GetRuleReferenceCode/45628"
}
```

---

### `GET /rules`

Paginated list of OAC top-level titles.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | int | 1 | Page number |
| `page_size` | int | 50 | Results per page (1–200) |
| `title_filter` | string | `""` | Match by reference code. `""` = all. |

**Response:** `AllRulesResponse`

```json
{
  "page": 1,
  "page_size": 50,
  "title_filter": "",
  "returned_from_api": 177,
  "matching_filter": 177,
  "rules": [
    {
      "id": 429,
      "segment_id": 429,
      "reference_code": "429",
      "title": "Oklahoma Lottery Commission"
    }
  ],
  "source_url": "https://okadminrules-api.azurewebsites.net/..."
}
```

---

### `GET /titles`

All 177 OAC agencies in a single response.

**No parameters.**

**Response:** `TitlesResponse`

```json
{
  "total_count": 177,
  "titles": [
    {
      "reference_code": "429",
      "title": "Oklahoma Lottery Commission",
      "segment_id": 429,
      "rule_id": 429
    }
  ],
  "source_url": "https://okadminrules-api.azurewebsites.net/..."
}
```

---

### `GET /chapters`

All chapters under a specific OAC title/agency.

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `title_number` | string | yes | OAC reference code, e.g. `"429"` |

**Response:** `ChaptersResponse`

```json
{
  "title_number": "429",
  "title_name": "Oklahoma Lottery Commission",
  "segment_id": 429,
  "rule_id": 429,
  "chapter_count": 12,
  "chapters": [
    {
      "id": 5820,
      "title": "Chapter 1. General Provisions",
      "citation": "429:1",
      "segment_type": "Chapter"
    }
  ],
  "source_url": "https://okadminrules-api.azurewebsites.net/..."
}
```

---

### `GET /health`

Health check. Not included in the OpenAPI schema (hidden from GPT).

**Response:**

```json
{"status": "ok", "cache_entries": 42}
```

---

## MCP tools (server.py)

| Tool | Signature | Description |
|---|---|---|
| `search_rules` | `(query, top=8, skip=0, title_filter="")` | Full-text search |
| `suggest` | `(query, top=5)` | Autocomplete |
| `get_children` | `(parent_id: int)` | Navigate rule tree |
| `get_rule` | `(rule_id: int)` | Full rule text |
| `get_all_rules` | `(page=1, page_size=50, title_filter="")` | Paginated title list |
| `list_chapters` | `(title_number: str)` | Chapters of any agency |
| `list_titles` | `()` | All 177 OAC agencies |

---

## Cache

`cache.py` wraps a module-level `dict`. Keys are strings encoding the
function name and arguments. Values are the formatted response strings
(MCP server) or Pydantic model instances (HTTP server).

```python
# Cache key conventions
"search:{query}:{top}:{skip}:{title_filter}"
"suggest:{query}:{top}"
"children:{parent_id}"
"rule:{rule_id}"
"all_rules:{page}:{page_size}:{title_filter}"
"list_chapters:{title_number}"
"list_titles:all"
"http:search:..."   # HTTP server uses "http:" prefix
"http:chapters:..."
"http:titles:all"
```

The cache is process-scoped and never persisted. It resets on server
restart. There is no TTL — entries live for the lifetime of the process.

**Adding a TTL (optional):**

```python
# cache.py — add TTL support
import time

_store: dict[str, tuple[Any, float]] = {}
TTL = 3600  # 1 hour

def get(key: str) -> Any | None:
    entry = _store.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if time.time() > expires_at:
        del _store[key]
        return None
    return value

def set(key: str, value: Any, ttl: float = TTL) -> None:
    _store[key] = (value, time.time() + ttl)
```

---

## Error handling

### HTTP server errors

| Status | Meaning |
|---|---|
| 400 | Bad request (invalid params) |
| 404 | Segment/rule not found, or no children for leaf node |
| 502 | Upstream Oklahoma API returned an error |
| 503 | Network error reaching the upstream API |

All errors return `{"detail": "human-readable message"}`.

### MCP tool errors

Tools return error strings (not exceptions) so the LLM can relay them
to the user with context. Each error message includes a suggested next step.

---

## Deployment

### Render (production)

The `render.yaml` file configures a **Docker-based web service**.
Render auto-deploys on every push to `main`.

**Environment variables set by Render:**
- `PORT` — Render sets this automatically; the `CMD` in Dockerfile reads it

**Free tier limits:**
- 512 MB RAM
- Sleeps after 15 min inactivity (cold start ~30s)
- 750 free hours/month

**Upgrade path:** Render Starter ($7/mo) for always-on, or Railway/Fly.io.

### Local development

```bash
# Start the HTTP server with auto-reload
uvicorn http_server:app --reload --port 8000

# Start the MCP server (connects via stdio)
python server.py
```

### Docker

```bash
docker build -t ok-rules .
docker run -p 8000:8000 ok-rules
```

---

## Extending the project

### Add a new endpoint to the HTTP server

1. Add an async function to `api.py` if a new upstream call is needed.
2. Add a Pydantic response model to `http_server.py`.
3. Add a `@app.get(...)` or `@app.post(...)` function.
4. Add a corresponding `@mcp.tool()` to `server.py` if you want MCP support.
5. Add test cases to `test_server.py`.
6. Commit and push — Render redeploys automatically.

### Add a new MCP tool only

1. Add an async function to `api.py` if needed.
2. Add a `@mcp.tool()` function to `server.py`.
3. The function docstring becomes the tool description — write it clearly.

### Change the default agency

Edit `constants.py`:

```python
DEFAULT_TITLE_FILTER = "310"   # State Department of Health
```

### Point at a different Oklahoma API environment

Edit `constants.py`:

```python
BASE_API_URL = "https://okadminrules-api-staging.azurewebsites.net"
```

### Add authentication to the HTTP server

If you ever need to restrict access to your deployed server (e.g. to
prevent abuse), add an API key header check:

```python
# http_server.py
from fastapi.security import APIKeyHeader
from fastapi import Security, HTTPException

API_KEY = os.environ.get("API_KEY", "")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def require_api_key(key: str = Security(api_key_header)):
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")

# Add to any endpoint:
@app.get("/search", dependencies=[Depends(require_api_key)])
```

Then set `API_KEY` as an environment variable in Render's dashboard.

---

## Data flow example

**User asks:** "What are the rules for claiming a prize over $600?"

```
Custom GPT
  │
  ├─ POST https://ok-lottery-rules.onrender.com/search
  │    ?query=prize+claim+over+600&title_filter=429
  │
  └─ http_server.py → cache miss → api.search()
       │
       └─ POST https://oksearchrules.azurewebsites.net/api/Search
            {"q": "prize claim over 600", "top": 8, ...}
            → returns results with segment IDs
  │
  ├─ GET https://ok-lottery-rules.onrender.com/rule/45923
  │    (segment ID from search result)
  │
  └─ http_server.py → cache miss → api.get_rule_reference_code(45923)
       │
       └─ GET https://okadminrules-api.azurewebsites.net/GetRuleReferenceCode/45923
            → returns HTML text → stripped → returned as JSON

GPT formats the response with citation "429:20-1-3" and presents to user.
```

---

## Known limitations

1. **No WIP rules** — `includeWIP=false` is hardcoded. Rules in draft are
   not returned by `GetSegmentsByParentId`. Change the constant in `api.py`
   if needed.

2. **Search scope** — The Azure Search index only covers published rule text.
   Structural nodes (Chapters, Subchapters) don't appear in search results —
   only Sections do. Use `get_children()` to navigate structure.

3. **HTML in text** — The upstream API returns rule text as HTML. The
   `_strip_html()` function removes tags but may lose some formatting
   (tables, ordered lists). The raw HTML is available in `api.py` responses
   if you need to parse it more carefully.

4. **Response size cap** — MCP tool responses are capped at 6,000 characters
   (`MAX_RESPONSE_CHARS` in `constants.py`). Very long rules will be truncated.
   Increase the cap or implement chunked responses if needed.

5. **No cross-session caching** — The in-memory cache resets on every server
   restart. On Render's free tier, the server sleeps after 15 min of inactivity,
   which clears the cache. Add Redis or a disk-based cache for persistence.

6. **Rate limiting** — The Oklahoma state APIs have no documented rate limits,
   but aggressive polling could result in blocks. The cache mitigates this
   within a session.
