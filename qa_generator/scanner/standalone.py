"""
Text boxes that are not inside a <form>: a to-do box, a comment or chat box, an 'add item' field.

Typing text and pressing Enter can SEND something (a comment, a message, a new record), so, like form submits, it
only happens when the person allowed it (--submit-forms). Without that permission the box is only found, and the
generated test just types into it and checks that it kept the text.
"""

from qa_generator.utils import css_attr

PROBE = "QA test entry"          # the text typed into the box
MAX_BOXES = 2                     # per page
# Only plain text boxes: typing junk into an email / phone / number field could reach a real mailing list or be rejected.
TEXT_TYPES = ("", "text")
# Boxes that are searches or filters are tested elsewhere; zip codes and the like need real values.
SKIP_HINTS = ("search", "filter", "query", "find", "sort", "zip", "postal", "captcha", "coupon", "promo", "voucher", "otp", "code")

BOX_INFO_JS = """el => ({
    tag: el.tagName.toLowerCase(), type: (el.getAttribute('type') || '').toLowerCase(), id: el.id,
    name: el.getAttribute('name') || '', placeholder: el.getAttribute('placeholder') || '',
    aria: el.getAttribute('aria-label') || '', role: el.getAttribute('role') || '',
    inForm: !!el.closest('form'), inNav: !!el.closest('nav, [role=navigation]'),   // a header or footer element can hold a real to-do or comment box
    locked: el.readOnly || el.disabled })"""


def _selector_for(info: dict):
    """A selector that finds the same box again after a reload, or None if the box has nothing to recognise it by."""
    tag = info["tag"]
    if info["id"]:
        return f"{tag}{css_attr('id', info['id'])}"
    for attribute, value in (("placeholder", info["placeholder"]), ("aria-label", info["aria"]), ("name", info["name"])):
        if value:
            return f"{tag}{css_attr(attribute, value)}"
    return None


def _candidates(page) -> list:
    boxes = []
    for element in page.locator("input:visible, textarea:visible").all()[:60]:
        try:
            info = element.evaluate(BOX_INFO_JS)
        except Exception:
            continue
        if info["inForm"] or info["inNav"] or info["locked"] or info["role"] in ("combobox", "searchbox"):
            continue
        if info["tag"] == "input" and info["type"] not in TEXT_TYPES:
            continue
        hint = " ".join((info["id"], info["name"], info["placeholder"], info["aria"])).lower()
        if any(word in hint for word in SKIP_HINTS):
            continue
        selector = _selector_for(info)
        if selector:
            boxes.append({"selector": selector, "label": info["placeholder"] or info["aria"] or info["name"] or info["id"]})
    return boxes[:MAX_BOXES]


def _address(page) -> str:
    return page.url.split("#")[0]


def _effect_of_enter(page, page_url: str, selector: str):
    """Type the probe text, press Enter, and say what happened: 'text_appears', 'url_changed' or None. Reloads the page afterwards."""
    box = page.locator(selector).first
    start = _address(page)
    try:
        box.fill(PROBE)
        box.press("Enter")
        page.wait_for_timeout(900)
        if _address(page) != start:
            return "url_changed"
        if PROBE in page.locator("body").inner_text(timeout=2000):
            return "text_appears"
        return None
    except Exception:
        return None
    finally:
        try:
            page.goto(page_url, wait_until="domcontentloaded")
        except Exception:
            pass


def detect_standalone_inputs(page, page_url: str, press_enter: bool = False) -> list:
    """
    Text boxes outside any form. With permission (press_enter), each one is tried once: text + Enter, and the visible
    result is recorded as its 'effect'. Without permission nothing is typed and 'effect' stays None.
    """
    found = []
    for box in _candidates(page):
        effect = _effect_of_enter(page, page_url, box["selector"]) if press_enter else None
        found.append({"page_url": page_url, "selector": box["selector"], "label": box["label"],
                      "tried_enter": press_enter, "effect": effect})
    return found
