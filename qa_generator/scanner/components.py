"""
Detectors for reusable UI components (cards, search, filters, tables, forms, modals).

Each detector takes a loaded Playwright page and returns plain data describing
what it found, so the same code serves the homepage and every crawled sub-page.
"""

import re

from qa_generator.config import (
    UNSAFE_SUBMIT_PATTERN, CARD_CANDIDATES, DIALOG_CLOSE_SELECTOR, DIALOG_SELECTOR, FILTER_BUTTON_SELECTOR,
    MAX_FORMS_PER_PAGE, MODAL_TRIGGER_SELECTOR, NEGATIVE_SEARCH_QUERY, SEARCH_CANDIDATES,
    SEARCH_RESULTS_CANDIDATES, SELECT_FILTER_SELECTOR, TABLE_SELECTOR,
)
from qa_generator.templates.qa_forms import NON_FILLABLE, REQUIRED_FIELDS, SUBMIT_BUTTON

UNSAFE_SUBMIT = re.compile(UNSAFE_SUBMIT_PATTERN, re.I)
from qa_generator.utils import css_attr, extract_meaningful_word, extract_meaningful_words


def dom_text(locator) -> str:
    """
    The element's text as it is in the HTML (what Playwright's has_text matches), not as it is painted.
    inner_text() would give CSS-capitalised text and decorative arrows drawn by CSS, which no later match can find.
    """
    return " ".join((locator.text_content() or "").split())


def detect_cards(page, page_url: str) -> list:
    """Groups of 2+ repeating, visible content items (articles, grid cells, cards, listings)."""
    found = []
    for c_label, cand in CARD_CANDIDATES:
        loc = page.locator(cand)
        cnt = loc.count()
        if cnt < 2:
            continue
        visible = page.locator(_visible_variant(cand))
        if visible.count() < 2:
            continue
        found.append({
            "type": c_label,
            "selector": cand,
            "count": cnt,
            "sample_title": visible.first.inner_text().strip()[:80],
            "page_url": page_url,
        })
    return found


def detect_search(page, page_url: str, ref_text: str):
    for cand in SEARCH_CANDIDATES:
        loc = page.locator(cand).first
        if loc.count() > 0 and loc.is_visible() and loc.is_editable():
            results_sel = next((r for r in SEARCH_RESULTS_CANDIDATES if page.locator(r).count() > 0), None)
            return {
                "selector": cand,
                "page_url": page_url,
                "results_selector": results_sel,
                "sample_query": extract_meaningful_word(ref_text, default="test"),
                "queries": extract_meaningful_words(ref_text, 3) or ["test"],
                "negative_query": NEGATIVE_SEARCH_QUERY,
            }
    return None


def detect_filters(page, page_url: str, max_buttons: int = 6, max_selects: int = 3) -> list:
    filters = []
    seen_text = set()
    for fb in page.locator(FILTER_BUTTON_SELECTOR).all()[:max_buttons * 2]:
        try:
            txt = dom_text(fb)
            if txt and len(txt) < 30 and txt not in seen_text and fb.is_visible():
                seen_text.add(txt)
                filters.append({"type": "button", "text": txt, "page_url": page_url, "selector": FILTER_BUTTON_SELECTOR})
        except Exception:
            continue
        if len(filters) >= max_buttons:
            break

    # Any dropdown that is not part of a form is treated as a filter, plus filter-like names inside forms.
    selects = [s for s in page.locator("select").all()
               if s.evaluate("(el, sel) => !el.closest('form') || el.matches(sel)", SELECT_FILTER_SELECTOR)]
    for sf in selects[:max_selects]:
        try:
            s_name = sf.get_attribute("name")
            s_id = sf.get_attribute("id")
            s_sel = f"select{css_attr('name', s_name)}" if s_name else f"select{css_attr('id', s_id or '')}"
            opts = sf.locator("option").all()
            if len(opts) > 1 and sf.is_visible():
                opt_val = opts[1].get_attribute("value") or opts[1].inner_text().strip()
                values = [v for v in ((o.get_attribute("value") or o.inner_text().strip()) for o in opts[1:7]) if v]
                filters.append({
                    "type": "select",
                    "text": f"select_{s_name or s_id or 'filter'}",
                    "page_url": page_url,
                    "selector": s_sel,
                    "sample_value": opt_val,
                    "values": values or [opt_val],
                })
        except Exception:
            continue
    return filters


def detect_tables(page, page_url: str, limit: int = 2) -> list:
    tables = []
    for tbl in page.locator(TABLE_SELECTOR).all()[:limit]:
        try:
            if not tbl.is_visible():
                continue
            header_texts = [h.inner_text().strip() for h in tbl.locator("th, [role='columnheader']").all()]
            tables.append({
                "selector": TABLE_SELECTOR,
                "page_url": page_url,
                "headers": [h for h in header_texts if h][:6],
            })
        except Exception:
            continue
    return tables


def detect_forms(page, page_url: str, limit: int = MAX_FORMS_PER_PAGE) -> list:
    """Forms with at least one visible input. 'index' is the form's position among ALL forms on the page."""
    forms = []
    for idx, frm in enumerate(page.locator("form").all()):
        if len(forms) >= limit:
            break
        try:
            details = describe_form(frm)
        except Exception:
            continue
        if details:
            forms.append({"index": idx, "page_url": page_url, **details})
    return forms


def describe_form(frm):
    """Facts about one form, or None if it has no visible input or is a login form (the auth tests cover those)."""
    inputs = frm.locator("input:visible, select:visible, textarea:visible").all()
    if not inputs:
        return None
    # A login form is "one password + at most one other box (username / email)". Sign-up, contact-with-password
    # or change-password forms have more fields, so they are real forms to test.
    password_count = frm.locator("input[type='password']").count()
    plain_inputs = frm.locator("input:visible:not([type='password']):not([type='hidden']):not([type='submit'])"
                               ":not([type='button']):not([type='checkbox']):not([type='radio']), textarea:visible, select:visible").count()
    if password_count == 1 and plain_inputs <= 1:
        return None
    names = [n for n in (inp.get_attribute("name") for inp in inputs) if n]
    kinds = [inp.evaluate("el => el.tagName === 'INPUT' ? (el.type || 'text') : el.tagName.toLowerCase()")
             for inp in inputs]
    action = frm.get_attribute("action") or ""
    buttons = frm.locator(SUBMIT_BUTTON).all()[:3]
    button_text = " ".join(" ".join((b.text_content() or b.get_attribute("value") or "").split()) for b in buttons)  # real text, not CSS capitals
    label = f"{action} {button_text}"
    return {
        "action": action,
        "unsafe_submit": bool(UNSAFE_SUBMIT.search(label)),
        "has_password": password_count > 0,
        "submit_label": button_text[:60],
        "method": (frm.get_attribute("method") or "GET").upper(),
        "input_count": len(inputs),
        "fillable_count": sum(1 for k in kinds if k not in NON_FILLABLE),
        "required_count": frm.locator(REQUIRED_FIELDS).count(),
        "field_kinds": sorted(set(kinds)),
        "names": names[:6],
        "has_submit": frm.locator(SUBMIT_BUTTON).count() > 0,
    }


def detect_modal(page, page_url: str, max_triggers: int = 3):
    """
    Click likely modal triggers until one opens a dialog. Records whether the dialog
    could be closed again (close button or Escape) so the generated test only asserts that when it is true.
    """
    fallback = None
    for dt in page.locator(MODAL_TRIGGER_SELECTOR).all()[:max_triggers]:
        try:
            if not dt.is_visible():
                continue
            if dt.evaluate("el => !!el.closest('form')"):
                continue  # a button inside a form submits it; the scan must never do that
            start_url = page.url
            btn_id = dt.get_attribute("id")
            btn_txt = dom_text(dt)
            dt.scroll_into_view_if_needed()
            dt.click()
            page.wait_for_timeout(800)

            if page.url != start_url:
                # Trigger navigated instead of opening a dialog; go back and try the next one.
                page.goto(start_url, wait_until="domcontentloaded")
                continue

            dialog = page.locator(DIALOG_SELECTOR).first
            if dialog.count() == 0:
                continue

            # A form inside the dialog is described while the dialog is open (it is hidden once closed).
            dialog_form = dialog.locator("form").first
            modal_form = describe_form(dialog_form) if dialog_form.count() > 0 else None

            close_method = None
            close_btn = dialog.locator(DIALOG_CLOSE_SELECTOR).first
            if close_btn.count() > 0 and close_btn.is_visible():
                close_btn.click()
                page.wait_for_timeout(400)
                if page.locator(DIALOG_SELECTOR).count() == 0:
                    close_method = "button"
            if close_method is None:
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
                if page.locator(DIALOG_SELECTOR).count() == 0:
                    close_method = "escape"

            if btn_id:
                trigger = {"selector": css_attr("id", btn_id), "text": None}
            else:
                trigger = {"selector": MODAL_TRIGGER_SELECTOR, "text": btn_txt if btn_txt and len(btn_txt) < 30 else None}

            found = {
                "page_url": page_url,
                "trigger": trigger,
                "dialog_selector": DIALOG_SELECTOR,
                "close_selector": DIALOG_CLOSE_SELECTOR,
                "close_method": close_method,
                "form": modal_form,
            }
            # Prefer a popup that holds a form; keep looking while the page is still usable (dialog closed).
            if modal_form or close_method is None:
                return found
            fallback = fallback or found
        except Exception:
            continue
    return fallback


def _visible_variant(selector_list: str) -> str:
    """Append :visible to every comma-separated part of a CSS selector list."""
    return ", ".join(part.strip() + ":visible" for part in selector_list.split(","))
