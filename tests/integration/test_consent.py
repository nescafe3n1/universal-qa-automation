"""Cookie banners: finding them, choosing the right button, and never clicking things that are not banners."""

import urllib.parse

import pytest

from qa_generator.templates import qa_consent

pytestmark = pytest.mark.integration


@pytest.fixture
def page(browser_ready):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser.new_page()
        browser.close()


def show(page, body: str) -> None:
    """Load a page made of just `body`. data: addresses are real navigations, so page.goto() hooks run."""
    page.goto("data:text/html;charset=utf-8," + urllib.parse.quote(f"<!doctype html><html><body>{body}</body></html>"))


# a button that records which one was clicked, then removes its banner
def pick(banner_selector):
    return f"document.body.dataset.clicked = this.innerText; document.querySelector('{banner_selector}').remove()"


def clicked(page):
    return page.evaluate("document.body.dataset.clicked || ''")


def test_finds_a_banner_by_its_id_and_clicks_accept(page):
    show(page, f"""<h1>Shop</h1><div id="onetrust-banner-sdk">We use cookies to improve your experience.
        <button id="onetrust-accept-btn-handler" onclick="{pick('#onetrust-banner-sdk')}">Accept All</button>
        <button>Cookie Settings</button></div>""")
    found = qa_consent.find_and_dismiss(page)
    assert found == {"container": "#onetrust-banner-sdk", "button": "Accept All", "dismissed": True}
    assert clicked(page) == "Accept All"


def test_prefers_reject_over_accept(page):
    show(page, f"""<div class="cookie-consent-bar">This site uses cookies.
        <button onclick="{pick('.cookie-consent-bar')}">Accept all</button>
        <button onclick="{pick('.cookie-consent-bar')}">Reject all</button></div>""")
    found = qa_consent.find_and_dismiss(page)
    assert found["button"] == "Reject all" and found["dismissed"] and clicked(page) == "Reject all"


def test_falls_back_to_accept_when_reject_does_not_close_the_banner(page):
    show(page, f"""<div id="cookie-bar">We use cookies.
        <button onclick="document.body.dataset.opened = 'preferences'">Reject all</button>
        <button onclick="{pick('#cookie-bar')}">Accept</button></div>""")
    found = qa_consent.find_and_dismiss(page)
    assert found["button"] == "Accept" and found["dismissed"]
    assert page.evaluate("document.body.dataset.opened") == "preferences"       # reject was tried first


def test_can_close_a_banner_that_only_has_a_close_button(page):
    show(page, f"""<div id="cookie-notice">We use cookies.
        <button aria-label="Close" onclick="{pick('#cookie-notice')}">x</button></div>""")
    assert qa_consent.find_and_dismiss(page)["dismissed"] is True


def test_finds_a_banner_that_appears_a_moment_after_the_page_loads(page):
    show(page, """<h1>Shop</h1><script>setTimeout(() => { document.body.insertAdjacentHTML('beforeend',
        '<div id="consent-wall">Your privacy matters. <button onclick="this.parentElement.remove()">I agree</button></div>'); }, 600);</script>""")
    found = qa_consent.find_and_dismiss(page, wait_ms=2000)
    assert found and found["button"] == "I agree" and found["dismissed"]


def test_reports_a_banner_it_could_not_dismiss(page):
    show(page, """<div id="cookie-banner">We use cookies. <button>Accept all</button></div>""")   # the button does nothing
    found = qa_consent.find_and_dismiss(page)
    assert found["dismissed"] is False and found["button"] == "Accept all"


def test_does_not_click_things_that_only_look_like_cookie_pages(page):
    """A bakery page that mentions cookies has buttons, but none of them is an accept/reject answer."""
    show(page, """<section class="cookies-menu"><h2>Our cookies</h2><p>Fresh cookies and consent forms.</p>
        <button onclick="document.body.dataset.clicked = 'wrong'">Add to cart</button>
        <button onclick="document.body.dataset.clicked = 'wrong'">View recipe</button></section>""")
    assert qa_consent.find_and_dismiss(page, wait_ms=600) is None
    assert clicked(page) == ""


def test_a_page_without_a_banner_is_left_alone(page):
    show(page, "<h1>Hello</h1><button onclick=\"document.body.dataset.clicked = 'wrong'\">Accept</button>")
    assert qa_consent.find_and_dismiss(page, wait_ms=600) is None and clicked(page) == ""


def test_a_custom_button_label_from_the_person_wins(page):
    show(page, f"""<div id="cookie-bar">We use cookies.
        <button onclick="{pick('#cookie-bar')}">Accept all</button>
        <button onclick="{pick('#cookie-bar')}">Fine by me</button></div>""")
    found = qa_consent.find_and_dismiss(page, extra_labels=["Fine by me"])
    assert found["button"] == "Fine by me" and clicked(page) == "Fine by me"


def test_a_known_banner_is_dismissed_without_searching(page):
    show(page, f"""<div id="cookie-bar">We use cookies.
        <button onclick="{pick('#cookie-bar')}">Reject all</button><button>Accept all</button></div>""")
    assert qa_consent.dismiss(page, {"container": "#cookie-bar", "button": "Reject all", "dismissed": True}) is True
    assert clicked(page) == "Reject all"


def test_dismiss_gives_up_quickly_when_the_banner_is_not_there(page):
    show(page, "<h1>No banner today</h1>")
    assert qa_consent.dismiss(page, {"container": "#cookie-bar", "button": "Accept", "dismissed": True}, wait_ms=300) is False


def test_install_dismisses_the_banner_once_per_page(page):
    seen = []
    qa_consent.install(page, on_found=seen.append)
    show(page, f"""<div id="cookie-bar">We use cookies. <button onclick="{pick('#cookie-bar')}">Accept all</button></div>""")
    assert [s["button"] for s in seen] == ["Accept all"] and clicked(page) == "Accept all"
    show(page, f"""<div id="cookie-bar">We use cookies. <button onclick="{pick('#cookie-bar')}">Accept all</button></div>""")
    assert len(seen) == 1       # the second page load is not searched again: no extra waiting on every navigation
