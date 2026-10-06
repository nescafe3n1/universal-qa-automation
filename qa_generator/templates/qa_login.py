"""
Shared login + access-check helpers.

This one file is used by the Nes-Dev QA scanner at generation time AND copied into
every generated test suite, so the scanner and the tests log in exactly the
same way. Only depends on Playwright.
"""

import time
from urllib.parse import urlparse

# Tried in priority order inside the form that holds the password field.
USER_FIELD_CANDIDATES = [
    "input[type='email']",
    "input[name*='email' i]",
    "input[id*='email' i]",
    "input[name*='user' i]",
    "input[id*='user' i]",
    "input[name*='login' i]",
    "input[autocomplete='username']",
    "input[type='text']",
    "input:not([type])",
]
PASSWORD_SELECTOR = "input[type='password']"
SUBMIT_CANDIDATES = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Sign in')",
    "button:has-text('Log in')",
    "button:has-text('Login')",
    "button:not([type='button'])",
]
LOGOUT_SELECTOR = (
    "button:has-text('Logout'), a:has-text('Logout'), button:has-text('Log out'), a:has-text('Log out'), "
    "button:has-text('Sign out'), a:has-text('Sign out'), [aria-label*='logout' i], a[href*='logout' i]"
)
LOGIN_URL_HINTS = ("login", "signin", "sign-in", "sign_in", "/auth")


def _first_visible(scope, candidates):
    for sel in candidates:
        loc = scope.locator(sel)
        for i in range(min(loc.count(), 5)):
            el = loc.nth(i)
            try:
                if el.is_visible() and el.is_enabled():
                    return el
            except Exception:
                continue
    return None


def password_field_visible(page) -> bool:
    try:
        return page.locator(PASSWORD_SELECTOR + ":visible").count() > 0
    except Exception:
        return False


def perform_login(page, login_url: str, username: str, password: str, timeout_ms: int = 15000):
    """
    Log in through the site's real login form.
    Returns (ok, message). ok is True only when the password form went away after submit.
    """
    page.goto(login_url, wait_until="domcontentloaded", timeout=timeout_ms * 2)
    try:
        page.locator(PASSWORD_SELECTOR).first.wait_for(state="visible", timeout=timeout_ms)
    except Exception:
        return False, f"No visible password field on {login_url}"

    form = page.locator("form").filter(has=page.locator(PASSWORD_SELECTOR))
    scope = form.first if form.count() > 0 else page

    user_el = _first_visible(scope, USER_FIELD_CANDIDATES)
    pw_el = _first_visible(scope, [PASSWORD_SELECTOR])
    if user_el is None or pw_el is None:
        return False, "Could not find a visible username/email field next to the password field"

    user_el.fill(username)
    pw_el.fill(password)
    submit = _first_visible(scope, SUBMIT_CANDIDATES)
    if submit is not None:
        submit.click()
    else:
        pw_el.press("Enter")

    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if not password_field_visible(page):
            break
        page.wait_for_timeout(250)
    else:
        return False, f"Still on the login form after submitting (wrong credentials?) — at {page.url}"

    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    return True, page.url


def is_login_url(url: str, login_url: str = "") -> bool:
    path = (urlparse(url).path or "/").lower()
    if login_url and path.rstrip("/") == (urlparse(login_url).path or "/").lower().rstrip("/"):
        return True
    return any(h in path for h in LOGIN_URL_HINTS)


def is_under_path(url: str, protected_url: str) -> bool:
    """True when url's path is the protected path or below it."""
    path = (urlparse(url).path or "/").rstrip("/") + "/"
    protected = (urlparse(protected_url).path or "/").rstrip("/") + "/"
    return path.startswith(protected)


def access_blocked(final_url: str, status, protected_url: str, login_url: str, shows_password_form: bool) -> bool:
    """
    Did a request for protected_url get refused? True when the server answered 401/403/404,
    sent the client to the login page, rendered a password form, or redirected out of the protected area.
    """
    if status in (401, 403, 404):
        return True
    if is_login_url(final_url, login_url) or shows_password_form:
        return True
    return not is_under_path(final_url, protected_url)
