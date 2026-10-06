"""Small, dependency-free helpers shared by the scanner and the generator."""

import os
import pprint
import re
import shutil
import sys
from urllib.parse import urlparse


def is_interactive() -> bool:
    """True only when stdin is a real terminal. (Windows reports the NUL device as a tty, so check the console mode.)"""
    try:
        if not sys.stdin.isatty():
            return False
        if os.name == "nt":
            import ctypes
            import msvcrt
            mode = ctypes.c_uint()
            handle = msvcrt.get_osfhandle(sys.stdin.fileno())
            return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Centered prompts: the menus, banners and questions sit in the middle of a wide terminal.
# Everything shares one left edge (a column CONTENT_WIDTH wide), so it lines up like a page.
# Output that is not a prompt (scan summary, pytest output) stays left-aligned.
# ---------------------------------------------------------------------------
CONTENT_WIDTH = 80


def left_margin() -> int:
    """Spaces to put before each prompt line; 0 when output is not a terminal or the window is narrow."""
    if not is_interactive():
        return 0
    try:
        columns = shutil.get_terminal_size().columns
    except Exception:
        return 0
    return max(0, (columns - CONTENT_WIDTH) // 2)


def _pad_lines(text: str) -> str:
    pad = " " * left_margin()
    return "\n".join(pad + line if line.strip() else line for line in str(text).split("\n"))


def cprint(text: str = "", **kwargs) -> None:
    """print(), with every non-empty line moved to the centered column."""
    print(_pad_lines(text), **kwargs)


def cinput(prompt: str = "") -> str:
    """input() whose question starts at the centered column (leading blank lines are kept as they are)."""
    stripped = prompt.lstrip("\n")
    return input("\n" * (len(prompt) - len(stripped)) + " " * left_margin() + stripped)


def cgetpass(prompt: str = "") -> str:
    """getpass.getpass() whose question starts at the centered column."""
    import getpass
    return getpass.getpass(" " * left_margin() + prompt)


def slugify(text: str) -> str:
    """Convert arbitrary text into a safe, clean Python identifier fragment."""
    text = re.sub(r"[^\w\s-]", "_", text or "", flags=re.ASCII).strip().lower()
    return re.sub(r"[-\s_]+", "_", text).strip("_")


def normalize_url(url: str) -> str:
    """Ensure URL has a valid scheme: https for websites, http for local addresses (localhost, 127.x, 192.168.x...)."""
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        host = url.split("/")[0].split(":")[0].lower()
        local = host == "localhost" or host.endswith(".local") or re.fullmatch(r"(127|10)(\.\d{1,3}){3}|192\.168(\.\d{1,3}){2}|172\.(1[6-9]|2\d|3[01])(\.\d{1,3}){2}", host)
        url = ("http://" if local else "https://") + url
    return url


def resolve_endpoint_url(base: str, path: str) -> str:
    """Safely combine base URL and sub-route, preserving subdirectories if present."""
    if not path:
        return base
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return base.rstrip("/") + "/" + path.lstrip("/")


SEARCH_STOP_WORDS = {
    "with", "from", "your", "this", "that", "have", "more", "item", "view",
    "page", "home", "about", "contact", "login", "register", "admin", "sign",
    "user", "click", "here", "read", "load", "loading", "error", "select"
}


def extract_meaningful_words(text: str, count: int = 3) -> list:
    """Up to `count` distinct representative keywords from DOM text, in order of appearance."""
    words, seen = [], set()
    for w in re.findall(r'\b[a-zA-Z]{4,}\b', text or ""):
        if w.lower() not in SEARCH_STOP_WORDS and w.lower() not in seen:
            seen.add(w.lower())
            words.append(w)
    return words[:count]


def extract_meaningful_word(text: str, default: str = "test") -> str:
    """Extract a representative keyword from DOM text to use for dynamic search probing."""
    return (extract_meaningful_words(text, 1) or [default])[0]


def same_site(url: str, base_url: str) -> bool:
    """True when url is on the base host or one of its subdomains (e.g. api.example.com)."""
    host = urlparse(url).hostname or ""
    base_host = (urlparse(base_url).hostname or "").removeprefix("www.")
    return host == base_host or host.endswith("." + base_host) or host == "www." + base_host


def path_of(url: str) -> str:
    return urlparse(url).path or "/"


def css_attr(name: str, value: str) -> str:
    """Build an exact-match CSS attribute selector that survives quotes/backslashes in value."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'[{name}="{escaped}"]'


def py(obj) -> str:
    """Render a Python literal (str/list/dict/tuple/bool/None) for embedding in generated code."""
    return pprint.pformat(obj, width=110, sort_dicts=False)


class UniqueNamer:
    """Hands out unique identifiers so generated tests never silently overwrite each other."""

    def __init__(self):
        self._seen = {}

    def __call__(self, base: str, fallback: str = "item") -> str:
        base = slugify(base) or fallback
        count = self._seen.get(base, 0) + 1
        self._seen[base] = count
        return base if count == 1 else f"{base}_{count}"
