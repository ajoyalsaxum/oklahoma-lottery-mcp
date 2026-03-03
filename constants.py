# API base URLs
BASE_API_URL = "https://okadminrules-api.azurewebsites.net"
SEARCH_API_URL = "https://oksearchrules.azurewebsites.net"

# Default scoping — empty string means all 177 OAC titles
DEFAULT_TITLE_FILTER = ""
DEFAULT_PAGE_SIZE = 50

# HTTP settings
HTTP_TIMEOUT = 30.0                   # seconds

# Response cap — keeps tool output LLM-friendly
MAX_RESPONSE_CHARS = 6000

# ── Search document field names (from live API inspection) ──────────────────
# document.Title_Number  → "429"
# document.Section_Number → "429:15-1-14"  (OAC citation)
# document.Id            → segment ID as string
# document.ParentId      → int, parent segment ID
# document.DisplayName   → "Title 429. Oklahoma Lottery Commission"
# document.Description   → human-readable section title
# document.Text          → HTML-encoded rule text
# ────────────────────────────────────────────────────────────────────────────
