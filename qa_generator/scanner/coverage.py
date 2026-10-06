"""
Honest coverage notes: things the scan SAW but the generated tests cannot cover.

A green run only means "what was tested passed". These notes list what was not tested and why,
so nobody mistakes a clean report for full coverage. They are printed after the scan, shown in the
HTML report and written to the generated suite's README.
"""

from urllib.parse import urlparse

CAPTCHA_SELECTOR = ("iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='turnstile'], "
                    ".g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey]")
DATE_PICKER_SELECTOR = ("input[readonly]:visible, input[class*='datepicker' i]:visible, "
                        "input[class*='flatpickr' i]:visible, input[class*='datetimepicker' i]:visible")
HARMLESS_IFRAMES = ("youtube", "youtu.be", "vimeo", "google.com/maps", "maps.google")
MAX_NOTES = 25


def _path(url: str) -> str:
    return urlparse(url).path or "/"


def _add(notes: list, page_url: str, kind: str, text: str) -> None:
    if not any(n["text"] == text for n in notes) and len(notes) < MAX_NOTES:
        notes.append({"page_url": page_url, "kind": kind, "text": text})


def detect_coverage_gaps(page, page_url: str, notes: list) -> None:
    """Look at the current page for things no generated test covers and append a note for each."""
    where = _path(page_url)

    if page.locator(CAPTCHA_SELECTOR).count() > 0:
        _add(notes, page_url, "captcha",
             f"CAPTCHA on {where}: forms there will usually refuse automated submits, so their submit tests may be skipped or fail.")

    pickers = page.locator(DATE_PICKER_SELECTOR).count()
    if pickers:
        _add(notes, page_url, "date-picker",
             f"{pickers} read-only or date-picker field(s) on {where} are not filled (custom date pickers are not supported).")

    loose = page.evaluate("""() => [...document.querySelectorAll('input, textarea')].filter(el =>
        !el.closest('form') && el.offsetParent !== null &&
        !['hidden','submit','button','reset','image','search','checkbox','radio'].includes(el.type) &&
        !/search|filter/i.test(el.name + el.id + (el.placeholder || '') + (el.getAttribute('aria-label') || '') +
                               (el.getAttribute('role') || ''))).length""")
    if loose:
        _add(notes, page_url, "no-form-tag",
             f"{loose} input field(s) on {where} are not inside a <form> tag, so the form tests do not fill or submit them.")

    for frame in page.locator("iframe:visible").all()[:6]:
        src = (frame.get_attribute("src") or "").strip()
        if src and not any(h in src for h in HARMLESS_IFRAMES) and "recaptcha" not in src and "hcaptcha" not in src:
            host = urlparse(src).netloc or src[:40]
            _add(notes, page_url, "iframe",
                 f"Embedded content from {host} on {where}: anything inside the iframe (forms, widgets) is not scanned.")

    hover = page.locator("nav [aria-haspopup='true']:not([aria-expanded]), header [aria-haspopup='true']:not([aria-expanded])").count()
    if hover:
        _add(notes, page_url, "hover-menu", f"{hover} menu(s) on {where} open only on hover and are not tested.")

    texts = page.evaluate("""() => [...document.querySelectorAll('button, [role=button], input[type=button]')]
        .filter(el => el.offsetParent !== null && !el.closest('form, dialog, [role=dialog], [role=tablist]') &&
                      !el.hasAttribute('aria-expanded') && !el.hasAttribute('aria-haspopup') && el.getAttribute('role') !== 'tab' &&
                      !/next|prev|previous|slide|arrow/i.test(el.getAttribute('aria-label') || '') &&
                      !/filter|pill|tab|close|dismiss|carousel|slick|swiper|pagination|pager|next|prev/i.test(el.className || ''))
        .map(el => (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' '))
        .filter(t => t && t.length < 40)""")
    unique = list(dict.fromkeys(texts))[:6]
    if unique:
        listed = ", ".join(f'"{t}"' for t in unique)
        _add(notes, page_url, "buttons",
             f"Buttons on {where} that no test clicks (their behaviour is untested): {listed}.")


def add_form_notes(scan: dict) -> None:
    """Notes about forms the generated tests fill but deliberately do not submit."""
    notes = scan.setdefault("coverage_notes", [])
    areas = [("", (scan.get("components") or {}).get("forms") or []),
             ("user area: ", (scan.get("user_session") or {}).get("forms") or []),
             ("admin area: ", (scan.get("admin_session") or {}).get("forms") or [])]
    for prefix, forms in areas:
        for frm in forms:
            if frm.get("unsafe_submit"):
                _add(notes, frm["page_url"], "unsafe-form",
                     f"Form on {_path(frm['page_url'])} ({prefix}\"{frm.get('submit_label') or 'submit'}\") is filled but never submitted: "
                     f"{frm.get('unsafe_reason') or 'it looks destructive or spends money'}.")
    modal_form = ((scan.get("components") or {}).get("modal") or {}).get("form") or {}
    if modal_form.get("unsafe_submit"):
        _add(notes, "", "unsafe-form", "The form inside the popup dialog is filled but never submitted: it looks destructive or spends money.")


def add_input_notes(scan: dict) -> None:
    """Notes about text boxes outside forms: what was only typed into, and what pressing Enter did not change."""
    notes = scan.setdefault("coverage_notes", [])
    for box in ((scan.get("components") or {}).get("interactions") or {}).get("inputs") or []:
        name = box["label"] or box["selector"]
        where = _path(box["page_url"])
        if box.get("effect"):
            continue
        if box.get("tried_enter"):
            text = (f"Pressing Enter in the \"{name}\" box on {where} showed no visible result, "
                    "so the test only checks that the box accepts typed text.")
        else:
            text = (f"The \"{name}\" box on {where} is outside any form. The test only types into it; "
                    "run with --submit-forms to also press Enter and check what happens.")
        _add(notes, box["page_url"], "typing-box", text)
