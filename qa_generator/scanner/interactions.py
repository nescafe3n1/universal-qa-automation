"""
Detectors for interactive widgets: tabs, accordion / menu toggles, pagination, carousels, file uploads.

Widgets that need a click are verified once during the scan (the click must visibly do something).
Only verified widgets are reported, so a generated test never asserts something the site never did.
"""

from qa_generator.config import (
    CAROUSEL_NEXT_SELECTOR, CAROUSEL_SELECTOR, CAROUSEL_SLIDE_SELECTOR, PAGINATION_NEXT_CANDIDATES,
    PAGINATION_SELECTOR, TOGGLE_SELECTOR,
)
from qa_generator.scanner.components import dom_text
from qa_generator.scanner.standalone import detect_standalone_inputs
from qa_generator.utils import css_attr

EMPTY_INTERACTIONS = {"tabs": [], "toggles": [], "pagination": [], "carousels": [], "uploads": [], "inputs": []}


def detect_interactions(page, page_url: str, press_enter: bool = False) -> dict:
    """Run every widget detector on the current page. Reloads the page afterwards if any click changed it."""
    found = {kind: [] for kind in EMPTY_INTERACTIONS}
    clicked = False
    for kind, detector, clicks in (
        ("tabs", detect_tabs, True), ("toggles", detect_toggles, True), ("uploads", detect_uploads, False),
        ("carousels", detect_carousels, True), ("pagination", detect_pagination, True),
        # text boxes outside forms: only typed into (and Enter pressed) when the person allowed sending data
        ("inputs", lambda pg, url: detect_standalone_inputs(pg, url, press_enter), False),
    ):
        try:
            found[kind] = detector(page, page_url)
            clicked = clicked or (clicks and bool(found[kind]))
        except Exception:
            continue
        if clicks and page.url != page_url:  # a probe navigated away: come back before the next detector
            page.goto(page_url, wait_until="domcontentloaded")
    if clicked:
        try:
            page.goto(page_url, wait_until="domcontentloaded")
            page.wait_for_timeout(500)
        except Exception:
            pass
    return found


def detect_tabs(page, page_url: str) -> list:
    tabs = []
    for idx, tablist in enumerate(page.get_by_role("tablist").all()):
        items = tablist.get_by_role("tab")
        count = items.count()
        if count < 2 or not tablist.is_visible():
            continue
        second = items.nth(1)
        second.click()
        page.wait_for_timeout(300)
        if second.get_attribute("aria-selected") != "true":
            continue  # clicking did not select it: not a working tab widget
        tabs.append({
            "page_url": page_url,
            "tablist_index": idx,
            "count": count,
            "has_controls": all(items.nth(k).get_attribute("aria-controls") for k in range(count)),
        })
    return tabs


def detect_toggles(page, page_url: str, limit: int = 6) -> list:
    """Accordion headers and menu buttons that open/close something."""
    toggles, seen = [], set()
    for el in page.locator(TOGGLE_SELECTOR).all()[:limit * 2]:
        if len(toggles) >= limit:
            break
        info = el.evaluate("""el => ({
            tag: el.tagName.toLowerCase(), id: el.id, role: el.getAttribute('role') || '',
            popup: el.getAttribute('aria-haspopup') || '', inForm: !!el.closest('form'),
            inNav: !!el.closest('nav, header, [role=navigation]'),
            expanded: el.tagName === 'SUMMARY' ? el.parentElement.open : el.getAttribute('aria-expanded') === 'true'})""")
        if info["inForm"] or info["role"] in ("tab", "combobox") or info["popup"] == "dialog":
            continue
        text = dom_text(el)[:150]  # the whole label: the test matches on it
        if info["id"]:
            selector, text_filter = f"{info['tag']}{css_attr('id', info['id'])}", None
        elif text:
            selector, text_filter = info["tag"], text
        else:
            continue
        key = (selector, text_filter)
        if key in seen:
            continue
        seen.add(key)
        el.click()
        page.wait_for_timeout(300)
        now = el.evaluate("el => el.tagName === 'SUMMARY' ? el.parentElement.open : el.getAttribute('aria-expanded') === 'true'")
        if now == info["expanded"]:
            continue  # the click changed nothing
        toggles.append({
            "page_url": page_url,
            "kind": "summary" if info["tag"] == "summary" else "button",
            "selector": selector,
            "text": text_filter,
            "label": text[:40] or info["id"],  # short, for the test name only
            "region": "menu" if info["inNav"] else "accordion",
            "starts_open": info["expanded"],
        })
        el.click()  # put it back so later probes see the original layout
        page.wait_for_timeout(200)
    return toggles


def detect_pagination(page, page_url: str) -> list:
    for idx, pager in enumerate(page.locator(PAGINATION_SELECTOR).all()[:4]):
        if not pager.is_visible() or pager.locator("a, button").count() < 1:  # page 1 may only have a "next" link
            continue
        for candidate in PAGINATION_NEXT_CANDIDATES:
            control = pager.locator(candidate).first
            if control.count() == 0 or not control.is_visible() or not control.is_enabled():
                continue
            before_url, before_text = page.url, page.locator("body").inner_text()
            control.click()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(800)
            moved = page.url.split("#")[0] != before_url.split("#")[0]  # a "#" change is not a real page change
            changed = moved or page.locator("body").inner_text() != before_text
            if moved:
                page.goto(before_url, wait_until="domcontentloaded")
            if changed:
                return [{"page_url": page_url, "container_selector": PAGINATION_SELECTOR,
                         "container_index": idx, "next_selector": candidate}]
            break
    return []


def detect_carousels(page, page_url: str) -> list:
    for idx, carousel in enumerate(page.locator(CAROUSEL_SELECTOR).all()[:6]):
        if not carousel.is_visible() or carousel.locator(CAROUSEL_SLIDE_SELECTOR).count() < 2:
            continue
        control = carousel.locator(CAROUSEL_NEXT_SELECTOR).first
        if control.count() == 0 or not control.is_visible() or not control.is_enabled():
            continue
        before = carousel.inner_html()
        control.click()
        page.wait_for_timeout(900)
        if carousel.inner_html() != before:
            return [{"page_url": page_url, "container_selector": CAROUSEL_SELECTOR, "container_index": idx,
                     "next_selector": CAROUSEL_NEXT_SELECTOR}]
    return []


def detect_uploads(page, page_url: str, limit: int = 3) -> list:
    """File inputs, visible or hidden behind a styled button. Never submits anything."""
    uploads = []
    for idx, field in enumerate(page.locator("input[type='file']").all()):
        if len(uploads) >= limit:
            break
        if field.is_disabled():
            continue
        uploads.append({"page_url": page_url, "index": idx, "accept": field.get_attribute("accept") or ""})
    return uploads
