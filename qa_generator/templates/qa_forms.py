"""
Form helpers shared by the generated form tests (and by the scanner):
fill every field, submit, and report what the page did in response.
"""

import re
import struct
import zlib

import pytest
from playwright.sync_api import expect

# Input types that are never filled (nothing sensible to type, or covered by the login tests).
NON_FILLABLE = ("hidden", "submit", "button", "reset", "image", "color", "range")
SUBMIT_BUTTON = "button[type='submit'], input[type='submit'], button:not([type])"
REQUIRED_FIELDS = "input[required]:visible, select[required]:visible, textarea[required]:visible"
MESSAGE_BOXES = ("[role='alert']:visible, [role='status']:visible, .alert:visible, .error:visible, "
                 ".invalid-feedback:visible, .error-message:visible, .toast:visible")

SAMPLE_VALUES = {
    "text": "QA Test",
    "search": "QA Test",
    "email": "qa_test@example.com",
    "tel": "1234567890",
    "url": "https://example.com",
    "password": "QaTest!2345",  # login forms are skipped by the scanner, so this only fills sign-up style forms
    "date": "2030-01-15",
    "time": "10:30",
    "datetime-local": "2030-01-15T10:30",
    "month": "2030-01",
    "week": "2030-W03",
}
# Text boxes are filled by what they ask for (name / placeholder / label), not just their type.
HINTS = (("email", "qa_test@example.com"), ("phone", "1234567890"), ("zip", "12345"), ("postal", "12345"),
         ("first", "QA"), ("last", "Tester"), ("name", "QA Test"), ("city", "Springfield"),
         ("address", "1 Test Street"), ("subject", "QA Test"), ("message", "QA Test message"))

SUCCESS_WORDS = re.compile(
    r"thank|success|submitted|received|message (?:has been )?sent|subscribed|we.ll be in touch|"
    r"we will (?:be in touch|contact)|check your (?:email|inbox)|confirmation", re.I)


def _png_1x1() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1, 8-bit RGB
    pixel = zlib.compress(b"\x00\xff\xff\xff")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixel) + chunk(b"IEND", b"")


PNG_1X1 = _png_1x1()


def upload_payload(accept: str = "") -> dict:
    """A tiny valid file that matches the input's accept list (image, PDF or text)."""
    accept = (accept or "").lower()
    if "image" in accept or any(ext in accept for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp")):
        return {"name": "qa_test.png", "mimeType": "image/png", "buffer": PNG_1X1}
    if "pdf" in accept:
        return {"name": "qa_test.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4\n%%EOF\n"}
    if ".csv" in accept:
        return {"name": "qa_test.csv", "mimeType": "text/csv", "buffer": b"name,value\nqa,1\n"}
    return {"name": "qa_test.txt", "mimeType": "text/plain", "buffer": b"QA test file"}


def text_re(text):
    """
    Match an element by its text, ignoring case and spacing. Pages often show labels in capitals through
    CSS (text-transform) while the HTML says "Add to cart", so an exact-case match would never find them.
    """
    return re.compile(r"^\s*" + r"\s+".join(re.escape(word) for word in text.split()) + r"\s*$", re.IGNORECASE)


def _number_value(field):
    low, high = field.get_attribute("min"), field.get_attribute("max")
    value = float(low) if low else 12345.0
    if high and value > float(high):
        value = float(high)
    return str(int(value)) if value == int(value) else str(value)


def _text_value(field, kind):
    hint = " ".join(field.get_attribute(a) or "" for a in ("name", "id", "placeholder", "aria-label")).lower()
    return next((v for key, v in HINTS if key in hint), SAMPLE_VALUES.get(kind, "QA Test"))


def _pick_combobox_option(field, tag):
    """Custom dropdown (role=combobox): open it, type to search if it is an input, pick the first option."""
    page = field.page
    field.click()
    options = page.locator("[role='option']:visible")
    if tag == "INPUT" and options.count() == 0:
        field.press_sequentially("a", delay=50)  # type-to-search dropdowns list options only after typing
    expect(options.first, "The custom dropdown shows no options").to_be_visible()
    text = " ".join(options.first.inner_text().split())
    options.first.click()
    if tag == "INPUT":
        expect(field, "The chosen option was not put into the dropdown").not_to_have_value("")
    else:
        expect(field, "The chosen option was not shown in the dropdown").to_contain_text(text)


def fill_form(form):
    """Fill every visible field with a sensible value and check it took. Returns how many fields were filled."""
    filled, radio_groups = 0, set()
    for field in form.locator("input:visible, textarea:visible, select:visible, [role='combobox']:not(input):not(select):visible").all():
        tag = field.evaluate("el => el.tagName")
        kind = (field.get_attribute("type") or "text").lower()
        if tag != "SELECT" and (field.get_attribute("role") == "combobox" or field.get_attribute("aria-haspopup") == "listbox"):
            _pick_combobox_option(field, tag)
        elif tag == "SELECT":
            options = [o.get_attribute("value") for o in field.locator("option:not([disabled])").all()]
            value = next((v for v in options[1:] if v), None)  # [0] is usually the "Choose..." placeholder
            if value is None or field.is_disabled():
                continue
            field.select_option(value)
            expect(field).to_have_value(value)
        elif tag == "INPUT" and kind in ("checkbox", "radio"):
            group = field.get_attribute("name") or ""
            if field.is_disabled() or (kind == "radio" and group in radio_groups):
                continue
            radio_groups.add(group)
            field.check(force=True)  # custom-styled boxes are often covered by a label
            expect(field).to_be_checked()
        elif tag == "INPUT" and kind == "file":
            if field.is_disabled():
                continue
            field.set_input_files(upload_payload(field.get_attribute("accept")))
            assert field.evaluate("el => el.files.length") >= 1, "The chosen file was not attached to the upload field"
        elif tag == "INPUT" and kind in NON_FILLABLE:
            continue
        elif field.is_editable():
            if tag == "TEXTAREA":
                value = "QA Test message"
            elif kind == "number":
                value = _number_value(field)
            elif kind == "text":
                value = _text_value(field, kind)
            else:
                value = SAMPLE_VALUES.get(kind, "QA Test")
            field.fill(value)
            expect(field).to_have_value(value)
        else:
            continue
        filled += 1
    return filled


def _body_text(page):
    try:
        return page.locator("body").inner_text(timeout=2000)
    except Exception:
        return ""


def _outcome(page, form, start_url, had_success_text, start_messages):
    """What the page visibly did after the submit, or None if nothing happened (yet)."""
    if page.url.split("#")[0] != start_url.split("#")[0]:  # a "#" change is not a real navigation
        return "redirected"
    if not form.is_visible():
        return "form closed"
    if form.locator(":invalid").count() or form.locator("[aria-invalid='true']").count():
        return "validation errors"
    if not had_success_text and SUCCESS_WORDS.search(_body_text(page)):
        return "success message"
    if page.locator(MESSAGE_BOXES).count() > start_messages:
        return "message shown"
    return None


def submit_and_observe(page, form, wait_ms=4000):
    """Click the form's submit button and watch for server errors, JavaScript crashes and a visible response."""
    js_errors, server_errors = [], []
    page.on("pageerror", lambda exc: js_errors.append(str(exc)))
    page.on("response", lambda r: server_errors.append(f"{r.status} {r.url}") if r.status >= 500 else None)
    start_url = page.url
    had_success_text = bool(SUCCESS_WORDS.search(_body_text(page)))
    start_messages = page.locator(MESSAGE_BOXES).count()
    form.locator(SUBMIT_BUTTON).first.click()
    outcome = None
    for _ in range(max(1, wait_ms // 250)):
        page.wait_for_timeout(250)
        outcome = _outcome(page, form, start_url, had_success_text, start_messages)
        if outcome:
            break
    return {"outcome": outcome, "server_errors": server_errors, "js_errors": js_errors}


def check_valid_submit(result):
    """A filled-in form must not crash the site and must visibly respond."""
    assert not result["server_errors"], f"Submitting the form caused a server error: {result['server_errors']}"
    assert not result["js_errors"], f"Submitting the form threw JavaScript errors: {result['js_errors']}"
    if result["outcome"] == "validation errors":
        pytest.skip("WARNING: the form rejected the sample data (validation errors), so the submit could not be fully checked")
    assert result["outcome"], "The form gave no visible response after submitting (no message, redirect or error)"


def check_empty_submit(result):
    """An empty form with required fields must be refused with a visible error."""
    assert not result["server_errors"], f"Submitting the empty form caused a server error: {result['server_errors']}"
    assert not result["js_errors"], f"Submitting the empty form threw JavaScript errors: {result['js_errors']}"
    assert result["outcome"] in ("validation errors", "message shown"), (
        "The form has required fields but accepted an empty submit "
        f"(result: {result['outcome'] or 'no visible error'})")
