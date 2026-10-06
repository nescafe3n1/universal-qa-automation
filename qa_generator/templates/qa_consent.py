"""
Cookie / consent banners get in the way of tests: they cover buttons, steal clicks and change what a page looks like.

The scanner uses find_and_dismiss() to find a banner and click it away, and remembers which banner and which button
worked. Every generated suite then calls dismiss() with that memory after the first page load of each test, so the
tests see the page the way a person who has already answered the banner sees it. A site without a banner is never
slowed down: if the scan found none, nothing here runs.

The button choice is the least invasive one that works: "reject / only necessary" first, then "accept", then a
close (x) button. A click only counts if the banner really disappeared afterwards.
"""

import re

CONTAINERS = ("[id*='cookie' i], [class*='cookie' i], [id*='consent' i], [class*='consent' i], [id*='gdpr' i], [class*='gdpr' i], "
              "[aria-label*='cookie' i], [aria-label*='consent' i], [data-testid*='cookie' i], [data-testid*='consent' i], "
              # popular banner libraries whose names do not contain 'cookie' or 'consent'
              "#onetrust-banner-sdk, .cc-window, .cc-banner, [id*='didomi' i], .osano-cm-window, #cmpbox, [class*='truste' i], "
              "[id*='usercentrics' i], [id*='iubenda' i], [class*='iubenda' i], [id*='termly' i], [id*='cmp-' i]")
CLICKABLE = "button, a, [role='button'], input[type='button'], input[type='submit']"
CONSENT_WORDS = re.compile(r"cookie|consent|gdpr|privacy", re.IGNORECASE)
MAX_BANNER_TEXT = 2500   # a banner is short; a whole page that happens to mention cookies is not a banner

REJECT = re.compile(
    r"^(reject|decline|deny|refuse|disagree)( all)?( non[- ]?essential| optional| unnecessary)?( cookies)?$"
    r"|^(use |accept |allow )?(only )?(strictly )?(necessary|essential|required)( cookies)?( only)?$", re.IGNORECASE)
ACCEPT = re.compile(
    r"^(accept|allow|agree|ok|okay|got it|i agree|i accept|understood|continue)( all)?( cookies)?( and continue| & continue)?$"
    r"|^yes,? i agree$", re.IGNORECASE)
CLOSE_LABEL = re.compile(r"^(close|dismiss|x|×|✕)$", re.IGNORECASE)

CONTAINER_SELECTOR_JS = """el => {
    if (el.id) return '#' + CSS.escape(el.id);
    const classes = [...el.classList].filter(c => c && !/^[0-9]/.test(c)).slice(0, 2);
    return classes.length ? el.tagName.toLowerCase() + '.' + classes.map(c => CSS.escape(c)).join('.') : null;
}"""


def _clean(label: str) -> str:
    return " ".join((label or "").split()).strip(" .!")


def _label_of(element) -> str:
    return _clean(element.text_content(timeout=500) or element.get_attribute("value") or element.get_attribute("aria-label") or "")


def _rank(label: str, aria: str, extra_labels) -> int:
    """0 = the person said which button to use, 1 = reject / necessary only, 2 = accept, 3 = close; -1 = not a banner button."""
    if any(label.lower() == _clean(extra).lower() for extra in extra_labels):
        return 0
    if REJECT.match(label):
        return 1
    if ACCEPT.match(label):
        return 2
    if CLOSE_LABEL.match(label) or CLOSE_LABEL.match(_clean(aria)):
        return 3
    return -1


def _banner_in(page, extra_labels):
    """Look once. Returns None (no banner), or {'container', 'button', 'dismissed'}."""
    for container in page.locator(CONTAINERS).all()[:15]:
        try:
            if not container.is_visible():
                continue
            text = container.inner_text(timeout=500) or ""
            if not CONSENT_WORDS.search(text) or len(text) > MAX_BANNER_TEXT:
                continue
            choices = []
            for element in container.locator(CLICKABLE).all()[:20]:
                if not element.is_visible():
                    continue
                label = _label_of(element)
                rank = _rank(label, element.get_attribute("aria-label") or "", extra_labels)
                if rank >= 0:
                    choices.append((rank, label, element))
            if not choices:
                continue
            selector = container.evaluate(CONTAINER_SELECTOR_JS) or CONTAINERS
            for rank, label, element in sorted(choices, key=lambda c: c[0]):
                try:
                    element.click(timeout=2000)
                    page.wait_for_timeout(500)
                    if not container.is_visible():
                        return {"container": selector, "button": label or "close", "dismissed": True}
                except Exception:
                    continue
            return {"container": selector, "button": choices[0][1], "dismissed": False}
        except Exception:
            continue
    return None


def find_and_dismiss(page, wait_ms: int = 1200, extra_labels=()):
    """Find a consent banner on the page and click it away. Banners often appear a moment after the page loads, so look for a while."""
    for _ in range(max(1, wait_ms // 300)):
        found = _banner_in(page, extra_labels)
        if found:
            return found
        page.wait_for_timeout(300)
    return None


def dismiss(page, banner: dict, wait_ms: int = 2000) -> bool:
    """Click the same button that worked during the scan (the banner is known, so no searching). True if it was clicked."""
    label = re.compile(r"^\s*" + r"\s+".join(re.escape(word) for word in banner["button"].split()) + r"\s*$", re.IGNORECASE)
    button = page.locator(banner["container"]).locator(CLICKABLE).filter(has_text=label).first
    try:
        button.wait_for(state="visible", timeout=wait_ms)
        button.click(timeout=3000)
        return True
    except Exception:
        return False


def install(page, banner=None, on_found=None, extra_labels=()) -> None:
    """
    After the first page.goto() on this page, dismiss the cookie banner. With a known `banner` that exact button is
    clicked; without one the page is searched, and `on_found` is told what was found. Later navigations are not
    slowed down: the banner is dealt with once per page.
    """
    original_goto = page.goto
    state = {"checked": False}

    def goto(url, **kwargs):
        response = original_goto(url, **kwargs)
        if not state["checked"]:
            state["checked"] = True
            try:
                if banner:
                    dismiss(page, banner)
                else:
                    found = find_and_dismiss(page, extra_labels=extra_labels)
                    if found and on_found:
                        on_found(found)
            except Exception:
                pass   # dealing with a banner must never break a page load
        return response

    page.goto = goto
