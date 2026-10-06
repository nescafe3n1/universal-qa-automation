"""
Every selector and keyword list the scanner relies on, in one place.

All lists are generic (HTML5 / ARIA / common CSS naming), not tied to any
particular site. Tune them here instead of editing the scanner.
"""

import fnmatch
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Pages the person asked the tool to leave alone (settings file, skip.paths)
# ---------------------------------------------------------------------------
SKIP_PATH_PATTERNS: list = []
_BASE_PATH = ""


def set_skip_paths(patterns, site_url: str = "") -> None:
    """Patterns are written relative to the site ("/logout", "/admin/danger/*"); `site_url` lets sites under a sub-folder match too."""
    global _BASE_PATH
    SKIP_PATH_PATTERNS[:] = list(patterns or [])
    _BASE_PATH = (urlparse(site_url).path or "").rstrip("/")


def is_skipped_path(path: str) -> bool:
    """True if this page (a path like /admin/danger/x) matches a skip pattern, relative to the site or as a full path."""
    if not SKIP_PATH_PATTERNS:
        return False
    path = "/" + (path or "").split("?")[0].split("#")[0].strip("/")
    candidates = [path]
    if _BASE_PATH and (path == _BASE_PATH or path.startswith(_BASE_PATH + "/")):
        candidates.append("/" + path[len(_BASE_PATH):].strip("/"))
    for pattern in SKIP_PATH_PATTERNS:
        folder = pattern[:-2] or "/" if pattern.endswith("/*") else None   # "/admin/*" also covers "/admin" itself
        if any(fnmatch.fnmatchcase(c, pattern) or c == folder for c in candidates):
            return True
    return False


# ---------------------------------------------------------------------------
# Network sniffing
# ---------------------------------------------------------------------------
STATIC_EXTENSIONS = (
    ".css", ".js", ".mjs", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".woff",
    ".woff2", ".ico", ".map", ".webp", ".avif", ".ttf", ".otf", ".mp4", ".webm",
)
API_CONTENT_TYPES = (
    "application/json", "application/graphql", "application/ld+json", "application/problem+json",
)
API_URL_MARKERS = ("/api/", "/v1/", "/v2/", "/v3/", "/v4/", "/graphql", "/rest/", ".json")

# ---------------------------------------------------------------------------
# Link discovery
# ---------------------------------------------------------------------------
NAV_LINK_SELECTOR = "header a[href], nav a[href], aside a[href], [role='navigation'] a[href]"
BODY_LINK_SELECTOR = "main a[href], section a[href], footer a[href]"
# Used only when the semantic containers above yield too few links
# (older sites without <header>/<nav>/<main>).
FALLBACK_LINK_SELECTOR = "body a[href]"
FALLBACK_LINK_THRESHOLD = 5
MAX_NAV_LINKS = 40
MAX_SUBPAGES_TO_SCAN = 8

# Never follow / generate GET tests for links that change state.
UNSAFE_ROUTE_WORDS = ("logout", "log-out", "signout", "sign-out", "delete", "destroy", "remove", "{")
# Ziggy (Laravel) routes containing these are private or auth-related, not public pages.
ZIGGY_SKIP_WORDS = ("login", "register", "password", "manage", "admin", "dashboard", "sanctum", "api/")

# ---------------------------------------------------------------------------
# Component detection
# ---------------------------------------------------------------------------
CARD_CANDIDATES = [
    ("articles", "article"),
    ("grid_items", "div[class*='grid'] > div"),
    ("cards", ".card, [class*='card']:not(body):not(html)"),
    ("listings", "[class*='listing'], [class*='item']:not(body):not(html):not(li)"),
]
SEARCH_CANDIDATES = [
    "input[type='search']",
    "input[name*='search' i]",
    "input[placeholder*='search' i]",
    "input[id*='search' i]",
    "input[aria-label*='search' i]",
    "input[name='q']",
    "input[name*='filter' i]",
]
SEARCH_RESULTS_CANDIDATES = ["[class*='result']", "[role='status']", "[class*='empty']", "[class*='feedback']"]
NEGATIVE_SEARCH_QUERY = "__qa_nonexistent_xyz_999__"

FILTER_BUTTON_SELECTOR = (
    "[role='tab'], [role='tablist'] button, [data-filter], "
    "button[class*='filter'], button[class*='pill'], button[class*='tab']"
)
SELECT_FILTER_SELECTOR = "select[name*='filter' i], select[name*='category' i], select[name*='sort' i], select[id*='filter' i]"
MAX_FORMS_PER_PAGE = 5
MAX_TOTAL_FORMS = 8
# Forms whose submit button / action match this are filled but never submitted (destructive or they spend money).
UNSAFE_SUBMIT_PATTERN = (r"delete|remove|destroy|deactivate|close.?account|cancel.?(?:account|subscription)|"
                         r"log.?out|sign.?out|unsubscribe|checkout|purchase|place.?order|pay(?:ment)?\b|buy")

# Interactive widgets (see scanner/interactions.py). Each is only tested if clicking it worked during the scan.
TOGGLE_SELECTOR = "button[aria-expanded]:visible, summary:visible"
PAGINATION_SELECTOR = "nav[aria-label*='pagination' i], [class*='pagination'], [class*='pager']"
PAGINATION_NEXT_CANDIDATES = (
    "a[rel='next']", "[aria-label*='next' i]", "a:has-text('Next')", "button:has-text('Next')",
    "a:has-text('›')", "a:has-text('»')", "a:text-is('2')",
)
CAROUSEL_SELECTOR = ("[aria-roledescription='carousel'], [class*='carousel'], [class*='swiper'], "
                     "[class*='slick'], [class*='splide']")
CAROUSEL_NEXT_SELECTOR = "button[aria-label*='next' i], [class*='next'], [class*='arrow-right']"
CAROUSEL_SLIDE_SELECTOR = "[aria-roledescription='slide'], [class*='slide']"
MAX_INTERACTIONS = {"tabs": 3, "toggles": 4, "pagination": 1, "carousels": 1, "uploads": 2, "inputs": 2}
TABLE_SELECTOR ="table, [role='table'], [role='grid']"

MODAL_TRIGGER_SELECTOR = (
    "button[aria-haspopup='dialog'], [data-bs-toggle='modal'], [data-toggle='modal'], "
    "button:has-text('Detail'), button:has-text('View'), button:has-text('Open'), button:has-text('Info'), "
    # Popups that usually hold a form.
    "button:has-text('Subscribe'), button:has-text('Contact'), button:has-text('Sign up'), button:has-text('Register'), "
    "button:has-text('Join'), button:has-text('Book'), button:has-text('Request'), button:has-text('Feedback'), "
    "button:has-text('Get started')"
)
# ':visible' matters: many frameworks keep hidden [role=dialog] nodes in the DOM.
DIALOG_SELECTOR = "dialog:visible, [role='dialog']:visible, [aria-modal='true']:visible, [class*='modal']:visible"
DIALOG_CLOSE_SELECTOR = "button[aria-label*='close' i], button:has-text('Close'), button:has-text('×'), [class*='close']"

# ---------------------------------------------------------------------------
# Authenticated crawling
# ---------------------------------------------------------------------------
# Links on the post-login page that look like the admin area.
ADMIN_ROUTE_KEYWORDS = (
    "/admin", "/manage", "/dashboard", "/portal", "/settings", "/users", "/staff", "/orders",
    "/products", "/inventory", "/customers", "/reports", "/analytics", "/categories", "/services",
)
MAX_USER_SUBLINKS = 8
MAX_ADMIN_SUBPAGES = 15

# Paths that suggest a page is a writable resource (used only by --include-write-tests).
WRITE_PROBE_KEYWORDS = ("item", "order", "cart", "product", "service", "post", "category", "listing")

# Limits for generated files
MAX_E2E_ROUTE_TESTS = 12
MAX_INTERCEPTED_API_TESTS = 15
