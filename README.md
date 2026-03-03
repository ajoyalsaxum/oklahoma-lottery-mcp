# Oklahoma Administrative Rules — MCP Server + Custom GPT

Live access to the **Oklahoma Administrative Code (OAC)** via the official
Oklahoma state API. Scoped by default to **Title 429 — Oklahoma Lottery
Commission**.

Two ways to use it:

| Mode | File | Use with |
|---|---|---|
| **MCP server** (stdio) | `server.py` | Claude Desktop / Claude Code |
| **HTTP REST API** | `http_server.py` | Custom GPT Actions, any HTTP client |

---

## Project layout

```
oklahoma-lottery-mcp/
├── server.py        # FastMCP server — 6 tools (Claude Desktop / MCP)
├── http_server.py   # FastAPI HTTP server — same 6 tools as REST endpoints (Custom GPT)
├── api.py           # All httpx async HTTP calls (shared by both servers)
├── cache.py         # In-memory per-session cache (shared by both servers)
├── constants.py     # Base URLs, defaults, field-name documentation
├── test_server.py   # End-to-end CLI test suite
├── Dockerfile       # For deploying http_server to Render / Railway / Fly.io
├── render.yaml      # One-click Render.com deploy config
└── requirements.txt
```

---

## Setup

### 1. Get Python 3.11+

FastMCP requires Python ≥ 3.10. macOS ships with Python 3.9 — install a
newer version first if needed:

```bash
# Option A — Homebrew (recommended on macOS)
brew install python@3.11
# then use: python3.11 -m venv .venv

# Option B — uv (fastest, manages Python versions automatically)
brew install uv
uv venv --python 3.11 .venv
uv pip install -r requirements.txt
source .venv/bin/activate

# Option C — pyenv (respected by the .python-version file in this project)
brew install pyenv
pyenv install 3.11
pyenv local 3.11           # activates 3.11 in this directory
python -m venv .venv
```

### 2. Create a virtual environment and install dependencies

```bash
cd oklahoma-lottery-mcp

# If you used Homebrew:
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# If you used uv (already done above — just activate):
source .venv/bin/activate
```

No API key or authentication is required — both state APIs are open.

---

## Run the test suite

```bash
# Full suite — raw API responses + all 6 tool outputs + edge cases
python test_server.py

# Targeted sub-tests
python test_server.py search "lottery game"   # search with a custom query
python test_server.py rule 45628              # fetch a specific segment ID
python test_server.py children 2              # explore children of parent ID 2
python test_server.py chapters                # list Title 429 chapters
python test_server.py drill                   # walk the tree: chapters → sections → text
python test_server.py edge                    # only edge-case / error-path tests
```

The test output shows **raw JSON from the API first**, then the formatted
string each MCP tool would return to the LLM. This makes it easy to verify
field names and data shapes when the API changes.

---

## Start the MCP server (stdio transport)

```bash
python server.py
```

The server speaks the MCP protocol over stdin/stdout and is ready for a
client such as Claude Desktop.

---

## Claude Desktop configuration

Add the following block to your Claude Desktop `claude_desktop_config.json`
(typically at `~/Library/Application Support/Claude/claude_desktop_config.json`
on macOS):

```json
{
  "mcpServers": {
    "oklahoma-lottery": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["/absolute/path/to/oklahoma-lottery-mcp/server.py"],
      "env": {}
    }
  }
}
```

Replace the paths with the actual absolute paths on your machine. After
saving, restart Claude Desktop. You should see the server listed under
**MCP Servers** in the Claude settings panel.

### Quick check

```bash
# Print the path to the Python interpreter in your venv
source .venv/bin/activate
which python   # copy this into "command" above
pwd            # use this to build the path to server.py
```

---

## Available tools

| Tool | Purpose |
|---|---|
| `search_rules(query, top, skip, title_filter)` | Full-text search. Defaults to Title 429. |
| `suggest(query, top)` | Autocomplete suggestions for partial terms. |
| `get_children(parent_id)` | Navigate the rule tree from any node. |
| `get_rule(rule_id)` | Full text + metadata for a specific rule segment. |
| `get_all_rules(page, page_size, title_filter)` | Paginated list of OAC top-level titles. |
| `list_chapters()` | All chapters of Title 429 with IDs and citations. |

### Typical workflow in Claude

```
User: What are the rules about scratch ticket prizes?

Claude calls:
  1. search_rules("scratch ticket prizes")   → finds relevant sections
  2. get_rule(45812)                          → reads full text of top result
  3. get_children(chapter_id)                → if user wants to browse nearby rules
```

---

## API reference

All endpoints are unauthenticated.

| Endpoint | Method | Notes |
|---|---|---|
| `https://okadminrules-api.azurewebsites.net/GetAllRules` | GET | `pageNumber`, `pageSize`, `filter` params |
| `https://okadminrules-api.azurewebsites.net/GetSegmentsByParentId` | GET | `parentId`, `includeWIP` params |
| `https://okadminrules-api.azurewebsites.net/GetRuleReferenceCode/{id}` | GET | — |
| `https://okadminrules-api.azurewebsites.net/GetContactById/{id}` | GET | — |
| `https://oksearchrules.azurewebsites.net/api/Search` | POST | JSON body: `q, top, skip, filters, highlight` |
| `https://oksearchrules.azurewebsites.net/api/Suggest` | POST | JSON body: `q, top, suggester` |

### OAC citation format

```
Title:Chapter-Part-Section
 429 : 15  - 1  - 14
```

The `Section_Number` field in search results uses this format (e.g., `429:15-1-14`).

---

## Custom GPT setup

Custom GPTs use **Actions** — they call HTTP REST endpoints over the internet.
`http_server.py` is a FastAPI app that exposes the same 6 tools as REST
endpoints. FastAPI auto-generates the OpenAPI schema ChatGPT needs.

### Step 1 — Deploy the HTTP server

You need a public HTTPS URL. The free tier on **Render.com** works well
(always-on HTTPS, deploys from GitHub in ~3 minutes).

#### Option A — Render (recommended, free)

1. Push this repo to GitHub.
2. Go to [render.com](https://render.com) → **New** → **Blueprint**.
3. Connect your GitHub repo — Render picks up `render.yaml` automatically.
4. Click **Apply**. Your URL will be `https://ok-lottery-rules.onrender.com`
   (or similar — Render shows it in the dashboard).

> **Free tier note:** Render spins the service down after 15 minutes of
> inactivity. The first request after sleep takes ~30 seconds to wake up.
> Upgrade to the $7/mo Starter plan to keep it always-on.

#### Option B — Railway (free, no sleep)

1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**.
2. Select your repo. Railway detects the Dockerfile automatically.
3. In **Settings → Networking**, generate a public domain.
4. Your URL will be `https://ok-lottery-rules.up.railway.app` (or similar).

Railway's free tier gives 500 hours/month — enough for a personal GPT.

#### Option C — Local with ngrok (for testing only)

```bash
# Install ngrok from https://ngrok.com, then:
source .venv/bin/activate
uvicorn http_server:app --port 8000 &
ngrok http 8000
# Copy the https://xxxx.ngrok-free.app URL — it changes every restart
```

---

### Step 2 — Create the Custom GPT Action

1. Open [chatgpt.com](https://chatgpt.com) → your profile → **My GPTs** → **Create a GPT**.
2. Go to the **Configure** tab → scroll down → **Add action**.
3. In the **Schema** field, paste this URL in the import box:

   ```
   https://<your-render-url>/openapi.json
   ```

   ChatGPT fetches and parses the schema automatically.

4. Set **Authentication** to `None` (the Oklahoma API is public).
5. Click **Save**.

Your GPT now has these actions available:

| Action | Endpoint | What it does |
|---|---|---|
| `search_rules` | `GET /search?query=...` | Full-text search, defaults to Title 429 |
| `suggest` | `GET /suggest?query=...` | Autocomplete for partial terms |
| `get_children` | `GET /children/{id}` | Navigate the rule tree |
| `get_rule` | `GET /rule/{id}` | Full text of a specific rule |
| `get_all_rules` | `GET /rules` | Paginated list of OAC titles |
| `list_chapters` | `GET /chapters` | All Title 429 chapters |

---

### Step 3 — Write the GPT system prompt

Paste this into the GPT's **Instructions** field:

```
You are an expert on the Oklahoma Administrative Code (OAC), with a focus on
Title 429 — Oklahoma Lottery Commission rules.

When the user asks about OLC rules, regulations, or procedures:
1. Use search_rules to find relevant sections.
2. Use get_rule with the returned segment_id to read the full text.
3. Use list_chapters and get_children to help users browse if they aren't
   sure what they're looking for.
4. Always cite the OAC citation (e.g. 429:15-1-14) in your answers.
5. If a rule references another rule, look it up with get_rule.

Be precise and quote the actual rule text when answering. If you're unsure,
say so and suggest the user consult an attorney or the OLC directly.
```

---

### Test the deployed API

```bash
# Health check
curl https://<your-render-url>/health

# List chapters
curl https://<your-render-url>/chapters

# Search
curl "https://<your-render-url>/search?query=scratch+ticket&title_filter=429"

# Get a specific rule
curl https://<your-render-url>/rule/45628

# Browse the interactive API docs
open https://<your-render-url>/docs
```

The `/docs` page (Swagger UI) lets you try every endpoint in the browser
and see the exact request/response shapes.

---

## Extending to other OAC titles

The server is built to cover all OAC titles — Title 429 is just the default.

### Expand search to the full OAC

Pass `title_filter=""` to any tool that accepts it:

```python
# Search all OAC titles
search_rules("child care licensing", title_filter="")

# Browse all top-level titles
get_all_rules(title_filter="", page_size=200)
```

### Find and navigate a different title

```python
# 1. Find a title by its reference code
get_all_rules(title_filter="340")       # DHS — Dept of Human Services

# 2. Get its segment ID from the output, then drill in
get_children(segment_id)               # → chapters
get_children(chapter_id)              # → subchapters / sections
get_rule(section_id)                  # → full text
```

### Change the default title

Edit `constants.py`:

```python
DEFAULT_TITLE_FILTER = "340"   # change to any OAC title number
```

Or set it per-call without touching the code.

### Add new tools

All HTTP logic lives in `api.py`. To wrap a new endpoint:

1. Add an async function to `api.py`.
2. Add an `@mcp.tool()` function to `server.py` that calls it.
3. Add a test case to `test_server.py`.

---

## Caching notes

The in-memory cache (`cache.py`) lives for the lifetime of the MCP server
process. It prevents duplicate API calls within a session (e.g., if Claude
calls `list_chapters()` twice in the same conversation).

To force a fresh API call from the test suite, call `cache.clear()` before
the tool call — `test_server.py` does this between sections.

The cache is intentionally not persisted to disk. OAC rules change infrequently,
but caching across sessions risks serving stale text if a rule is amended.
For a long-running deployment you could add a TTL layer (e.g., with
`functools.lru_cache` + timestamps) without changing the tool signatures.
