"""
Universal reconnaissance engine.

dynamic_scan_site() opens the target with Playwright and returns a plain dict
describing what exists on the site. The generator turns that dict into tests,
so the scan result is the contract between the two halves.
"""

from playwright.sync_api import sync_playwright

from qa_generator.config import MAX_INTERACTIONS, MAX_SUBPAGES_TO_SCAN, MAX_TOTAL_FORMS, SKIP_PATH_PATTERNS
from qa_generator.scanner.auth import crawl_admin, crawl_user
from qa_generator.scanner.components import (
    detect_cards, detect_filters, detect_forms, detect_modal, detect_search, detect_tables,
)
from qa_generator.scanner.accessibility import MAX_A11Y_PAGES, scan_accessibility
from qa_generator.templates import qa_consent
from qa_generator.scanner.coverage import add_form_notes, add_input_notes, detect_coverage_gaps
from qa_generator.scanner.interactions import detect_interactions
from qa_generator.scanner.homepage import detect_inertia, discover_links, scan_landmarks
from qa_generator.scanner.network import make_sniffer
from qa_generator.utils import resolve_endpoint_url


def empty_scan(url: str) -> dict:
    return {
        "url": url,
        "is_inertia": False,
        "inertia_version": "",
        "homepage": {
            "title": "",
            "heading": "",
            "landmarks": [],
            "skip_link": None,
            "primary_cta": None,
            "nav_links": [],
        },
        "components": {
            "search": None,
            "filters": [],
            "cards": None,
            "all_cards": [],
            "modal": None,
            "tables": [],
            "forms": [],
            "interactions": {"tabs": [], "toggles": [], "pagination": [], "carousels": [], "uploads": [], "inputs": []},
        },
        "sub_pages": [],
        "accessibility": [],
        "consent_banner": None,
        "coverage_notes": [],
        "captured_apis": [],
        "user_session": None,
        "admin_session": None,
        "page_errors": [],
    }


def _settle(page, ms: int = 3000) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=ms)
    except Exception:
        pass


def _probe_link_statuses(context, links: list) -> None:
    """Record each link's HTTP status and content type as a guest (used to pick the right expectation)."""
    for lk in links:
        try:
            res = context.request.get(lk["full_url"], timeout=15000)
            lk["status"] = res.status
            lk["content_type"] = res.headers.get("content-type", "")
            lk["final_url"] = res.url  # where redirects ended up
        except Exception:
            lk["status"] = None
            lk["content_type"] = ""


def _probe_components(page, page_url: str, scan_data: dict, first_page: bool) -> None:
    """Run every component detector on the current page; keep the first find of each kind."""
    comp = scan_data["components"]

    for card in detect_cards(page, page_url):
        if not any(c["type"] == card["type"] for c in comp["all_cards"]):
            comp["all_cards"].append(card)
    if comp["all_cards"] and not comp["cards"]:
        comp["cards"] = comp["all_cards"][0]

    if not comp["search"]:
        ref_text = (comp["cards"] or {}).get("sample_title") or scan_data["homepage"]["heading"] or page.title()
        comp["search"] = detect_search(page, page_url, ref_text)

    if not comp["filters"]:
        comp["filters"] = detect_filters(page, page_url, max_buttons=6 if first_page else 4, max_selects=3 if first_page else 2)

    if not comp["tables"]:
        comp["tables"] = detect_tables(page, page_url)

    for frm in detect_forms(page, page_url):
        if len(comp["forms"]) >= MAX_TOTAL_FORMS:
            break
        # The same footer / newsletter form appears on every page: keep it once.
        if not any(f["action"] == frm["action"] and f["names"] == frm["names"] for f in comp["forms"]):
            comp["forms"].append(frm)

    detect_coverage_gaps(page, page_url, scan_data["coverage_notes"])

    if len(scan_data["accessibility"]) < MAX_A11Y_PAGES:   # passive: reads the page, changes nothing
        try:
            scan_data["accessibility"].append(scan_accessibility(page, page_url))
        except Exception:
            pass   # an accessibility check that cannot run must never break the scan

    # Widget probing clicks things (and reloads the page afterwards), so it runs after the passive detectors.
    for kind, items in detect_interactions(page, page_url, scan_data["options"]["submit_forms"]).items():
        kept = comp["interactions"][kind]
        for item in items:
            # The same header menu appears on every page: compare without the page it was found on.
            sans_page = {k: v for k, v in item.items() if k != "page_url"}
            duplicate = item in kept or (kind in ("toggles", "inputs") and any(
                {k: v for k, v in other.items() if k != "page_url"} == sans_page for other in kept))
            if len(kept) < MAX_INTERACTIONS[kind] and not duplicate:
                kept.append(item)

    # Modal probing clicks things, so it runs last on each page.
    if not comp["modal"]:
        comp["modal"] = detect_modal(page, page_url, max_triggers=6 if first_page else 3)


def dynamic_scan_site(url: str, login_path: str = None, accounts: list = None, headed: bool = False, timeout_ms: int = 30000,
                      submit_forms: bool = False, cookie_button: str = None):
    """
    Inspect ANY target website using generic DOM semantics & live traffic sniffing:
    page title/headings/landmarks, internal routes, repeating items, search, filters,
    tables, forms, modals, user/admin post-login areas, and same-site XHR/fetch calls.
    """
    print(f"\n[1/4] Running dynamic reconnaissance on: {url}")
    print(f"      Mode: {'Visible Browser (Headed)' if headed else 'Headless Background'}")

    scan_data = empty_scan(url)
    scan_data["options"] = {"submit_forms": submit_forms}   # the person's permission to send data while scanning
    accounts = accounts or []
    user_acc = next((a for a in accounts if a["role"] in ["user", "customer"]), None)
    admin_acc = next((a for a in accounts if a["role"] == "admin"), None)
    resolved_login = resolve_endpoint_url(url, login_path or "/login")

    def record_banner(found):
        if found["dismissed"]:
            scan_data["consent_banner"] = scan_data["consent_banner"] or {"container": found["container"], "button": found["button"]}
            return
        text = (f"A cookie banner appeared but clicking '{found['button']}' did not make it go away, so it may block clicks "
                "and cause test failures.")
        if not any(n["text"] == text for n in scan_data["coverage_notes"]):
            scan_data["coverage_notes"].append({"page_url": url, "kind": "cookie-banner", "text": text})

    def prepare_page(page):
        """Every page the scan opens deals with a cookie banner the same way (once per page, only after its first load)."""
        qa_consent.install(page, scan_data["consent_banner"], on_found=record_banner,
                           extra_labels=[cookie_button] if cookie_button else [])

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        attach_sniffer = make_sniffer(scan_data, url)

        # STEP 1: public homepage & component discovery
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 800})
        page = context.new_page()
        attach_sniffer(page, "public")
        prepare_page(page)

        print("      Crawling and probing live homepage...")
        try:
            res = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            scan_data["homepage"]["status"] = res.status if res else None
            _settle(page)
            detect_inertia(page, scan_data)
            scan_landmarks(page, scan_data["homepage"])
            scan_data["homepage"]["nav_links"] = discover_links(page, url)
            _probe_components(page, page.url, scan_data, first_page=True)
            print(f"      Checking HTTP status of {len(scan_data['homepage']['nav_links'])} discovered links...")
            _probe_link_statuses(context, scan_data["homepage"]["nav_links"])
        except Exception as e:
            print(f"      [!] Homepage reconnaissance notice: {e}")

        # STEP 2: crawl top internal sub-pages
        crawlable = [lk for lk in scan_data["homepage"]["nav_links"]
                     if (lk.get("status") or 200) < 400 and "html" in (lk.get("content_type") or "text/html")]
        for lk in crawlable[:MAX_SUBPAGES_TO_SCAN]:
            sub_u = lk["full_url"]
            try:
                print(f"      Scanning sub-page: {lk['name']} ({sub_u})...")
                s_res = page.goto(sub_u, wait_until="domcontentloaded", timeout=timeout_ms)
                status = s_res.status if s_res else None
                scan_data["sub_pages"].append({"name": lk["name"], "route": lk["route"], "url": sub_u, "status": status})
                if status and status < 400:
                    _settle(page, 2500)
                    _probe_components(page, sub_u, scan_data, first_page=False)
            except Exception:
                continue
        context.close()

        # STEPS 3-4: authenticated user & admin crawls
        if user_acc:
            scan_data["user_session"] = crawl_user(browser, attach_sniffer, url, resolved_login, user_acc, timeout_ms, prepare_page)
        if admin_acc:
            scan_data["admin_session"] = crawl_admin(browser, attach_sniffer, url, resolved_login, admin_acc, timeout_ms, prepare_page)

        browser.close()

    for had, key, label in ((user_acc, "user_session", "User"), (admin_acc, "admin_session", "Admin")):
        if had and not scan_data[key]:
            scan_data["coverage_notes"].append({
                "page_url": resolved_login, "kind": "login",
                "text": f"{label} login failed, so no {label.lower()}-area tests were generated. Check the login URL and credentials."})
    for key, label in (("user_session", "user"), ("admin_session", "admin")):
        session_data = scan_data[key]
        if session_data and session_data.get("guest_blocked_urls") == []:
            scan_data["coverage_notes"].append({
                "page_url": resolved_login, "kind": "no-protected-page",
                "text": f"No page in the {label} area was refused to guests during the scan, so no 'guests are blocked' "
                        f"test was generated for it. Use --{label}-target with a page that needs login to add one."})
    for key, label in (("user_session", "user"), ("admin_session", "admin")):
        session_data = scan_data[key]
        if not session_data or session_data.get("http_ok_urls") is None:
            continue
        browser_only = [u for u in ([session_data.get("post_login_url") or session_data.get("dashboard_url")]
                                    + [lk["url"] for lk in session_data.get("sublinks") or []]
                                    + [x for x in session_data.get("admin_links") or []])
                        if u and u not in session_data["http_ok_urls"]]
        if browser_only:
            scan_data["coverage_notes"].append({
                "page_url": browser_only[0], "kind": "browser-only",
                "text": f"{len(set(browser_only))} page(s) in the {label} area only work inside the browser (a plain HTTP request fails, "
                        "typical for single-page apps), so no HTTP-level tests were generated for them. The browser tests still cover them."})
    if SKIP_PATH_PATTERNS:
        scan_data["coverage_notes"].append({
            "page_url": url, "kind": "skipped-by-settings",
            "text": "Pages skipped because your settings file asked for it (skip.paths): " + ", ".join(SKIP_PATH_PATTERNS) + "."})
    add_form_notes(scan_data)
    add_input_notes(scan_data)

    _print_summary(scan_data, bool(user_acc), bool(admin_acc))
    return scan_data


def _print_summary(scan_data: dict, had_user: bool, had_admin: bool) -> None:
    comp = scan_data["components"]

    def session(value, attempted):
        return "Yes" if value else ("FAILED (see notice above)" if attempted else "No")

    print("      [OK] Dynamic Reconnaissance Complete:")
    print(f"           - Title                : {scan_data['homepage']['title']}")
    print(f"           - Navigation Routes    : {len(scan_data['homepage']['nav_links'])}")
    print(f"           - Sub-pages Scanned    : {len(scan_data['sub_pages'])}")
    print(f"           - Repeating Items      : {len(comp['all_cards'])} group(s)")
    print(f"           - Search Bar           : {'Yes' if comp['search'] else 'No'}")
    print(f"           - Filter Controls      : {len(comp['filters'])}")
    print(f"           - Modal Dialog         : {'Yes' if comp['modal'] else 'No'}")
    print(f"           - Data Tables          : {len(comp['tables'])}")
    print(f"           - Forms Detected       : {len(comp['forms'])}"
          + (f" (+1 in popup)" if (comp["modal"] or {}).get("form") else ""))
    inter = comp["interactions"]
    print(f"           - Widgets              : {len(inter['tabs'])} tabs, {len(inter['toggles'])} toggles, "
          f"{len(inter['pagination'])} pagination, {len(inter['carousels'])} carousel, {len(inter['uploads'])} upload, "
          f"{len(inter.get('inputs', []))} typing box")
    for label, key in (("User", "user_session"), ("Admin", "admin_session")):
        if scan_data[key]:
            print(f"           - {label} Area Forms     : {len(scan_data[key].get('forms') or [])}")
    print(f"           - Same-site API calls  : {len(scan_data['captured_apis'])}")
    print(f"           - JS page errors seen  : {len(scan_data['page_errors'])}")
    print(f"           - User Session         : {session(scan_data['user_session'], had_user)}")
    print(f"           - Admin Session        : {session(scan_data['admin_session'], had_admin)}")
    notes = scan_data.get("coverage_notes") or []
    if notes:
        print(f"      [!] Not covered by the generated tests ({len(notes)}):")
        for n in notes[:12]:
            print(f"           - {n['text']}")
        if len(notes) > 12:
            print(f"           ... and {len(notes) - 12} more (see the report)")
