"""The form helper copied into every suite, and the logic that decides which pages are really 'protected'."""

import struct
import zlib

import pytest

from qa_generator.generator.context import _guard_url
from qa_generator.templates import qa_forms


# ---- text_re: how generated tests find buttons ---------------------------------------------------------
@pytest.mark.parametrize("wanted, on_page", [
    ("Add to cart", "Add to cart"),
    ("Add to cart", "ADD TO CART"),            # CSS capitals: the page text is 'Add to cart', the screen shows capitals
    ("Add to cart", "  Add   to\n cart "),     # spacing differences
])
def test_text_re_matches_ignoring_case_and_spacing(wanted, on_page):
    assert qa_forms.text_re(wanted).search(on_page)


@pytest.mark.parametrize("wanted, on_page", [
    ("All", "Cameras and all lenses"),         # must match the whole label, not part of a longer one
    ("Add to cart", "Add to wishlist"),
])
def test_text_re_does_not_match_longer_text(wanted, on_page):
    assert not qa_forms.text_re(wanted).search(on_page)


def test_text_re_takes_punctuation_literally():
    assert qa_forms.text_re("What is shipping?").search("what is shipping?")
    assert not qa_forms.text_re("a.b").search("axb")


# ---- upload_payload ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("accept, name, mime", [
    ("image/*", "qa_test.png", "image/png"),
    (".jpg,.png", "qa_test.png", "image/png"),
    ("application/pdf", "qa_test.pdf", "application/pdf"),
    (".csv", "qa_test.csv", "text/csv"),
    ("", "qa_test.txt", "text/plain"),
])
def test_upload_payload_matches_what_the_field_accepts(accept, name, mime):
    payload = qa_forms.upload_payload(accept)
    assert payload["name"] == name and payload["mimeType"] == mime and payload["buffer"]


def test_test_png_is_a_valid_image():
    png = qa_forms.PNG_1X1
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and png.endswith(b"IEND\xaeB`\x82")
    # every chunk's checksum must be right, or a site that checks the image would reject it
    pos = 8
    while pos < len(png):
        length, kind = struct.unpack(">I4s", png[pos:pos + 8])
        data, crc = png[pos + 8:pos + 8 + length], struct.unpack(">I", png[pos + 8 + length:pos + 12 + length])[0]
        assert zlib.crc32(kind + data) & 0xFFFFFFFF == crc
        pos += 12 + length


def test_login_style_fields_are_not_skipped_by_the_filler_but_hidden_ones_are():
    assert "password" not in qa_forms.NON_FILLABLE      # sign-up forms need a password filled in
    assert {"hidden", "submit", "button"} <= set(qa_forms.NON_FILLABLE)


# ---- which page is a good 'guests are blocked' target ------------------------------------------------------
LANDING, OTHER = "https://s.test/cart", "https://s.test/account"


def test_guard_trusts_an_explicit_target():
    assert _guard_url(LANDING, {"guest_blocked_urls": [OTHER]}, explicit=True) == LANDING


def test_guard_uses_the_landing_page_when_guests_are_refused_from_it():
    assert _guard_url(LANDING, {"guest_blocked_urls": [LANDING, OTHER]}, explicit=False) == LANDING


def test_guard_skips_a_public_landing_page_and_uses_one_that_is_protected():
    """Login often lands on a public page (a cart). A guard test on it would fail for the wrong reason."""
    assert _guard_url(LANDING, {"guest_blocked_urls": [OTHER]}, explicit=False) == OTHER


def test_guard_is_none_when_nothing_is_protected():
    assert _guard_url(LANDING, {"guest_blocked_urls": []}, explicit=False) is None


def test_guard_keeps_old_behaviour_for_scans_that_did_not_probe():
    assert _guard_url(LANDING, {}, explicit=False) == LANDING
    assert _guard_url(LANDING, None, explicit=False) == LANDING


# ---- accessibility helper ---------------------------------------------------------------------------------------------------
def test_accessibility_description_is_one_readable_sentence():
    from qa_generator.templates import qa_a11y
    text = qa_a11y.describe({
        "label": {"id": "label", "impact": "critical", "help": "Form elements must have labels", "nodes": 3},
        "image-alt": {"id": "image-alt", "impact": "critical", "help": "Images must have alternative text", "nodes": 1}})
    assert text == ("label (critical, 3 elements: Form elements must have labels); "
                    "image-alt (critical, 1 element: Images must have alternative text)")


def test_axe_is_bundled_with_its_licence_header():
    from qa_generator.templates import qa_a11y
    assert len(qa_a11y.AXE_SOURCE) > 100_000
    header = " ".join(qa_a11y.AXE_SOURCE[:700].replace("*", " ").split())   # the header wraps lines
    assert "Mozilla Public License, v. 2.0" in header                 # the licence requires this notice to stay in the file
    assert set(qa_a11y.SERIOUS) == {"critical", "serious"}
