"""Homepage landmarks and internal link / route discovery."""

import json
from urllib.parse import urljoin, urlparse

from qa_generator.config import (
    is_skipped_path,
    BODY_LINK_SELECTOR, FALLBACK_LINK_SELECTOR, FALLBACK_LINK_THRESHOLD, MAX_NAV_LINKS,
    NAV_LINK_SELECTOR, UNSAFE_ROUTE_WORDS, ZIGGY_SKIP_WORDS,
)
from qa_generator.utils import css_attr

SKIP_HREF_PREFIXES = ("#", "javascript:", "mailto:", "tel:", "sms:", "data:")


def detect_inertia(page, scan_data: dict) -> None:
    """Detect a Laravel Inertia app (#app[data-page]) and capture its asset version."""
    try:
        data_page = page.locator("#app").get_attribute("data-page", timeout=2000)
        if data_page:
            scan_data["is_inertia"] = True
            scan_data["inertia_version"] = json.loads(data_page).get("version", "") or ""
            print(f"      [SPA] Detected Inertia app (version: {scan_data['inertia_version'] or 'n/a'})")
    except Exception:
        pass


def scan_landmarks(page, hp: dict) -> None:
    """Title, main heading, semantic landmarks, skip link and primary CTA."""
    hp["title"] = page.title()
    h1 = page.locator("h1, [role='heading'][aria-level='1'], h2").first
    if h1.count() > 0 and h1.is_visible():
        hp["heading"] = h1.inner_text().strip()

    for lm in ["header", "nav", "main", "aside", "footer"]:
        if page.locator(lm).count() > 0:
            hp["landmarks"].append(lm)

    skip_link = page.locator("a.skip-link, a[href^='#content'], a[href^='#main']").first
    if skip_link.count() > 0:
        s_href = skip_link.get_attribute("href") or ""
        if s_href.startswith("#") and len(s_href) > 1:
            hp["skip_link"] = {"href": s_href, "target_id": s_href[1:]}

    cta_btn = page.locator("main a.btn, main a[role='button'], header a.btn, a.btn-primary").first
    if cta_btn.count() > 0 and cta_btn.is_visible():
        c_href = cta_btn.get_attribute("href") or ""
        if c_href and not c_href.startswith(SKIP_HREF_PREFIXES):
            hp["primary_cta"] = {
                "text": cta_btn.inner_text().strip(),
                "href": c_href,
                "full_url": urljoin(page.url, c_href),
                "new_tab": (cta_btn.get_attribute("target") or "") == "_blank",
                "selector": f"a{css_attr('href', c_href)}",
            }


def discover_links(page, base_url: str) -> list:
    """
    Same-origin links from nav/header/aside first, then main/section/footer, then (only for
    sites without semantic containers) any link in <body>. Unsafe routes (logout, delete…) are skipped.
    """
    origin = urlparse(base_url)
    seen = {origin.path or "/", (origin.path or "/").rstrip("/") or "/"}
    links = []

    def collect(selector: str):
        for a in page.locator(selector).all():
            if len(links) >= MAX_NAV_LINKS:
                return
            try:
                h = (a.get_attribute("href") or "").strip()
                if not h or h.startswith(SKIP_HREF_PREFIXES):
                    continue
                full_u = urljoin(page.url, h).split("#")[0]
                parsed = urlparse(full_u)
                if parsed.netloc != origin.netloc or parsed.scheme not in ("http", "https"):
                    continue
                route = parsed.path or "/"
                if route in seen or any(w in route.lower() for w in UNSAFE_ROUTE_WORDS) or is_skipped_path(route):
                    continue
                seen.add(route)
                text = " ".join((a.inner_text() or "").split())
                links.append({
                    "name": text if (text and len(text) < 35) else (route.strip("/").split("/")[-1].replace("-", " ").capitalize() or "Route"),
                    "route": route,
                    "href": h,
                    "full_url": full_u,
                    "visible": a.is_visible(),
                    "new_tab": (a.get_attribute("target") or "") == "_blank",
                })
            except Exception:
                continue

    collect(NAV_LINK_SELECTOR)
    collect(BODY_LINK_SELECTOR)
    if len(links) < FALLBACK_LINK_THRESHOLD:
        collect(FALLBACK_LINK_SELECTOR)
    links.extend(_ziggy_routes(page, base_url, seen, MAX_NAV_LINKS - len(links)))
    return links


def _ziggy_routes(page, base_url: str, seen: set, room: int) -> list:
    """Laravel Ziggy exposes the route table as window.Ziggy.routes; add public GET routes from it."""
    if room <= 0:
        return []
    try:
        routes = page.evaluate(
            "() => (window.Ziggy && window.Ziggy.routes) ? Object.entries(window.Ziggy.routes)"
            ".map(([k, v]) => ({ name: k, uri: v.uri, methods: v.methods || [] })) : []"
        )
    except Exception:
        return []

    found = []
    for zr in routes or []:
        uri = zr.get("uri", "")
        if "GET" not in zr.get("methods", []) or "{" in uri:
            continue
        full_u = urljoin(base_url.rstrip("/") + "/", uri.lstrip("/"))
        route = urlparse(full_u).path or "/"
        if route in seen or any(k in route.lower() for k in ZIGGY_SKIP_WORDS + UNSAFE_ROUTE_WORDS):
            continue
        seen.add(route)
        found.append({
            "name": zr["name"].replace(".", " ").replace("-", " ").title(),
            "route": route,
            "href": None,  # not a clickable link on the page
            "full_url": full_u,
            "visible": False,
            "new_tab": False,
        })
        if len(found) >= room:
            break
    return found
