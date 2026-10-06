"""Authenticated crawling for the user and admin accounts."""

from urllib.parse import urljoin, urlparse

from qa_generator.config import (
    ADMIN_ROUTE_KEYWORDS, MAX_ADMIN_SUBPAGES, MAX_TOTAL_FORMS, MAX_USER_SUBLINKS, UNSAFE_ROUTE_WORDS, is_skipped_path,
)
from qa_generator.scanner.components import detect_forms
from qa_generator.templates.qa_login import (
    LOGOUT_SELECTOR, access_blocked, is_login_url, password_field_visible, perform_login,
)

SKIP_HREF_PREFIXES = ("#", "javascript:", "mailto:", "tel:", "sms:")


def _same_origin_links(page, base_url: str, selector: str) -> list:
    origin = urlparse(base_url).netloc
    current = page.url.split("#")[0].rstrip("/")
    links, seen = [], set()
    for a in page.locator(selector).all():
        try:
            h = (a.get_attribute("href") or "").strip()
            if not h or h.startswith(SKIP_HREF_PREFIXES):
                continue
            clean = urljoin(page.url, h).split("#")[0].rstrip("/")
            parsed = urlparse(clean)
            if parsed.netloc != origin or clean == current or clean in seen:
                continue
            if any(w in parsed.path.lower() for w in UNSAFE_ROUTE_WORDS) or is_skipped_path(parsed.path):
                continue
            seen.add(clean)
            text = " ".join((a.inner_text() or "").split())
            links.append({
                "name": text if (text and len(text) < 30) else (parsed.path.rstrip("/").split("/")[-1].capitalize() or "Home"),
                "url": clean,
                "path": parsed.path or "/",
            })
        except Exception:
            continue
    return links


def _collect_forms(page, forms: list, page_url: str) -> None:
    """Add this page's non-login forms to `forms` (read-only: nothing is filled or submitted during the scan)."""
    for frm in detect_forms(page, page_url, limit=3):
        if len(forms) >= MAX_TOTAL_FORMS:
            return
        if not any(f["action"] == frm["action"] and f["names"] == frm["names"] for f in forms):
            if frm.get("has_password"):
                # Inside a logged-in area a password form usually CHANGES the test account's password: fill it, never submit it.
                frm["unsafe_submit"] = True
                frm["unsafe_reason"] = "it has a password field in a logged-in area, so submitting could change the test account's password"
            forms.append(frm)


def _guest_blocked(browser, urls: list, login_url: str, timeout_ms: int, prepare_page=None) -> list:
    """Which of these URLs does a logged-out visitor NOT get to see? Only those are worth a 'guests are refused' test."""
    context = browser.new_context(ignore_https_errors=True)
    blocked = []
    try:
        page = context.new_page()
        if prepare_page:
            prepare_page(page)
        for url in list(dict.fromkeys(urls))[:10]:
            try:
                res = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=2000)
                except Exception:
                    pass
                if access_blocked(page.url, res.status if res else None, url, login_url, password_field_visible(page)):
                    blocked.append(url)
            except Exception:
                continue
    finally:
        context.close()
    return blocked


def _http_ok(context, urls: list, login_url: str) -> list:
    """
    Which pages answer a plain HTTP GET with the logged-in session? Single-page apps keep some pages
    only inside the browser (a direct request gets a 404), so HTTP-level tests must skip those:
    they would fail for the wrong reason, and a 'guests are refused' test would pass for the wrong reason.
    """
    ok = []
    for url in dict.fromkeys(urls):
        try:
            res = context.request.get(url, timeout=15000)
            if res.status < 400 and not is_login_url(res.url, login_url):
                ok.append(url)
        except Exception:
            continue
    return ok


def _allowed(urls: list) -> list:
    """Drop pages the person asked to skip (settings: skip.paths), even when login happens to land on one of them."""
    return [u for u in urls if not is_skipped_path(urlparse(u).path)]


def _has_heading(page) -> bool:
    h = page.locator("h1, h2").first
    return h.count() > 0 and h.is_visible()


def crawl_user(browser, attach_sniffer, base_url: str, login_url: str, account: dict, timeout_ms: int, prepare_page=None):
    print(f"      Logging in as User ({account['username']})...")
    context = browser.new_context(ignore_https_errors=True)
    try:
        page = context.new_page()
        attach_sniffer(page, "user")
        if prepare_page:
            prepare_page(page)
        ok, msg = perform_login(page, login_url, account["username"], account["password"], timeout_ms=min(timeout_ms, 20000))
        if not ok:
            print(f"      [!] User login failed: {msg}")
            return None

        post_login_url = page.url
        heading = page.locator("h1, h2, [role='heading']").first
        logout = page.locator(LOGOUT_SELECTOR).first
        sublinks = [
            lk for lk in _same_origin_links(page, base_url, "nav a[href], aside a[href], header a[href], main a[href]")
            if not is_login_url(lk["url"], login_url)
        ]
        welcome_text = heading.inner_text().strip() if heading.count() > 0 else ""
        has_logout = logout.count() > 0 and logout.is_visible()
        sublinks = sublinks[:MAX_USER_SUBLINKS]

        forms = []
        if not is_skipped_path(urlparse(post_login_url).path):
            _collect_forms(page, forms, post_login_url)
        for lk in sublinks:
            try:
                page.goto(lk["url"], wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                if not is_login_url(page.url, login_url):
                    _collect_forms(page, forms, lk["url"])
            except Exception:
                continue

        return {
            "login_url": login_url,
            "post_login_url": post_login_url,
            "welcome_text": welcome_text,
            "has_logout": has_logout,
            "sublinks": sublinks,
            "forms": forms,
            "guest_blocked_urls": _guest_blocked(browser, _allowed([post_login_url] + [lk["url"] for lk in sublinks]), login_url, timeout_ms, prepare_page),
            "http_ok_urls": _http_ok(context, _allowed([post_login_url] + [lk["url"] for lk in sublinks]), login_url),
        }
    except Exception as e:
        print(f"      [!] User scan notice: {e}")
        return None
    finally:
        context.close()


def crawl_admin(browser, attach_sniffer, base_url: str, login_url: str, account: dict, timeout_ms: int, prepare_page=None):
    print(f"      Logging in as Admin ({account['username']})...")
    context = browser.new_context(ignore_https_errors=True)
    try:
        page = context.new_page()
        attach_sniffer(page, "admin")
        if prepare_page:
            prepare_page(page)
        ok, msg = perform_login(page, login_url, account["username"], account["password"], timeout_ms=min(timeout_ms, 20000))
        if not ok:
            print(f"      [!] Admin login failed: {msg}")
            return None

        # Record the landing page BEFORE visiting sub-pages.
        dashboard_url = page.url
        dashboard_heading = _has_heading(page)
        admin_base_path = urlparse(dashboard_url).path.rstrip("/")

        admin_links = []
        for lk in _same_origin_links(page, base_url, "nav a[href], aside a[href], [role='navigation'] a[href], main a[href]"):
            under_base = admin_base_path not in ("", "/") and lk["path"].startswith(admin_base_path)
            if (under_base or any(m in lk["path"].lower() for m in ADMIN_ROUTE_KEYWORDS)) and not is_login_url(lk["url"], login_url):
                admin_links.append(lk)
        admin_links = admin_links[:MAX_ADMIN_SUBPAGES]

        forms = []
        if not is_skipped_path(urlparse(dashboard_url).path):
            _collect_forms(page, forms, dashboard_url)
        subpages = []
        for lk in admin_links:
            try:
                res = page.goto(lk["url"], wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                if is_login_url(page.url, login_url):
                    continue
                _collect_forms(page, forms, lk["url"])
                subpages.append({
                    "name": lk["name"],
                    "url": lk["url"],
                    "path": lk["path"],
                    "status": res.status if res else None,
                    "has_heading": _has_heading(page),
                    "has_table": page.locator("table:visible, [role='table']:visible").count() > 0,
                })
            except Exception:
                continue

        return {
            "login_url": login_url,
            "dashboard_url": dashboard_url,
            "has_heading": dashboard_heading,
            "admin_links": [x["url"] for x in admin_links],
            "subpages": subpages,
            "forms": forms,
            "guest_blocked_urls": _guest_blocked(browser, _allowed([dashboard_url] + [x["url"] for x in admin_links]), login_url, timeout_ms, prepare_page),
            "http_ok_urls": _http_ok(context, _allowed([dashboard_url] + [x["url"] for x in admin_links]), login_url),
        }
    except Exception as e:
        print(f"      [!] Admin scan notice: {e}")
        return None
    finally:
        context.close()
