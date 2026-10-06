"""
Shared fixtures and reporting hooks for this generated suite (Nes-Dev QA).

Site settings live in suite_config.json; credentials live in .env (never in code):
    QA_USER_USERNAME / QA_USER_PASSWORD
    QA_ADMIN_USERNAME / QA_ADMIN_PASSWORD
"""

import html
import json
import os
import re
import shutil
import time

import pytest
from playwright.sync_api import APIRequestContext, Page, Playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from csv_reporter import (EVIDENCE_DIR, RUN_WARNINGS, assign_test_case_ids, evidence_folder, generate_csv_reports,
                          record_test_result)
from qa_login import perform_login

ROOT = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(ROOT, "suite_config.json"), encoding="utf-8") as _f:
    SUITE = json.load(_f)

BASE_URL = SUITE["base_url"]
LOGIN_URL = SUITE["login_url"]
IS_INERTIA = SUITE.get("is_inertia", False)
CONSENT = SUITE.get("consent_banner")   # the cookie banner the scan dismissed, if the site has one
if CONSENT:
    import qa_consent


def _load_env_file(path: str) -> None:
    """Minimal .env reader: KEY="value" lines; real environment variables win."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)


_load_env_file(os.path.join(ROOT, ".env"))


def _credentials(role: str):
    username = os.environ.get(f"QA_{role}_USERNAME")
    password = os.environ.get(f"QA_{role}_PASSWORD")
    if not username or not password:
        pytest.skip(f"Set QA_{role}_USERNAME and QA_{role}_PASSWORD in .env to run {role.lower()} tests")
    return username, password


# ---------------------------------------------------------------------------
# Reporting hooks
# ---------------------------------------------------------------------------
def pytest_sessionstart(session):
    shutil.rmtree(os.path.join(ROOT, "test-results"), ignore_errors=True)
    shutil.rmtree(EVIDENCE_DIR, ignore_errors=True)  # evidence belongs to the latest run only


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(session, config, items):
    assign_test_case_ids(items)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    record_test_result(item, report)
    setattr(item, f"rep_{report.when}", report)  # lets the page fixture see, at teardown, whether the test failed
    return report


def pytest_sessionfinish(session, exitstatus):
    generate_csv_reports()


# ---------------------------------------------------------------------------
# Reliability: a slow or unreachable site must not look like dozens of broken pages
# ---------------------------------------------------------------------------
MAX_TIMEOUT_RETRIES = 3        # after this many, the site is clearly struggling and retrying only adds waiting
MAX_TIMEOUTS_BEFORE_STOP = 8   # after this many timeouts the run stops: more waiting would not tell us anything new
_timeout_retries = {"used": 0}
_timeouts_seen = {"total": 0}


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, PlaywrightTimeoutError) or ("Timeout" in str(exc) and "exceeded" in str(exc))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    """Retry a test once when it failed because of a timeout (not because of a failed check)."""
    try:
        return (yield)
    except Exception as exc:
        if not _is_timeout(exc):
            raise
        _timeouts_seen["total"] += 1
        if _timeouts_seen["total"] >= MAX_TIMEOUTS_BEFORE_STOP:
            RUN_WARNINGS.append(
                f"The run was stopped early: {_timeouts_seen['total']} tests timed out, so the site is too slow or not "
                "answering to test reliably right now. The remaining tests were not run. Try again later.")
            item.session.shouldstop = "the site keeps timing out"  # finish this test, then stop cleanly
            raise
        if _timeout_retries["used"] >= MAX_TIMEOUT_RETRIES:
            raise
        _timeout_retries["used"] += 1
        item.runtest()  # one more attempt with the same fixtures; if it fails again, that failure is reported
        item.user_properties.append(("retried_after_timeout", "yes"))


@pytest.fixture(scope="session", autouse=True)
def site_is_reachable(playwright: Playwright, request):
    """Stop early, with a clear message, if the site does not answer at all (nothing was tested, nothing is broken)."""
    ctx = playwright.request.new_context(ignore_https_errors=True)
    started = time.time()
    try:
        ctx.get(BASE_URL, timeout=25000)
    except Exception as exc:
        pytest.exit(f"The site could not be reached ({BASE_URL}): {str(exc).splitlines()[0]}. "
                    "No tests were run, so nothing is confirmed broken. Check the address or the network and try again.",
                    returncode=3)
    finally:
        ctx.dispose()
    elapsed = time.time() - started
    if elapsed > 8:
        terminal = request.config.pluginmanager.get_plugin("terminalreporter")
        if terminal:
            terminal.write_line(f"[warning] The site took {elapsed:.0f}s to answer. Results may include timeouts; "
                                "they are labelled in the report.", yellow=True)


# ---------------------------------------------------------------------------
# Browser / page fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def login_url():
    return LOGIN_URL


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "ignore_https_errors": True}


TRACE_ENABLED = os.environ.get("NESQA_TRACE", "1") != "0"   # NESQA_TRACE=0 turns the step-by-step trace off (screenshots stay)


def _save_evidence(page: Page, nodeid: str, tracing_on: bool) -> None:
    """A failed test leaves a screenshot, the page address and (if on) a Playwright trace. Never breaks the test run."""
    folder = evidence_folder(nodeid)
    os.makedirs(folder, exist_ok=True)
    try:
        page.screenshot(path=os.path.join(folder, "failure.png"), timeout=5000)
    except Exception:
        pass
    try:
        with open(os.path.join(folder, "page.txt"), "w", encoding="utf-8") as f:
            f.write(page.url)
    except Exception:
        pass
    if tracing_on:
        try:
            page.context.tracing.stop(path=os.path.join(folder, "trace.zip"))
        except Exception:
            pass


def _prepare_page(page: Page) -> None:
    """
    - page.goto() waits for the page content (domcontentloaded), not for every last image, ad or tracking script
      ('load'). One slow third-party resource would otherwise fail a page that works.
    - the cookie banner is dismissed once, after the page's first load (only for sites where the scan found one).
    """
    original_goto = page.goto

    def goto(url, **kwargs):
        kwargs.setdefault("wait_until", "domcontentloaded")
        return original_goto(url, **kwargs)

    page.goto = goto
    if CONSENT:
        qa_consent.install(page, CONSENT)


@pytest.fixture
def page(page: Page, request) -> Page:
    """
    pytest-playwright's page, with two changes:
    - page.goto() waits for the page content (domcontentloaded), not for every last image, ad or tracking script
      ('load'). One slow third-party resource would otherwise fail a page that works.
    - when the test fails, a screenshot and a Playwright trace are saved in reports/evidence/<test id>/ for the report.
    """
    _prepare_page(page)
    tracing_on = False
    if TRACE_ENABLED:
        try:
            page.context.tracing.start(screenshots=True, snapshots=True)
            tracing_on = True
        except Exception:
            pass
    yield page

    failed = any(getattr(request.node, f"rep_{phase}", None) is not None and getattr(request.node, f"rep_{phase}").failed
                 for phase in ("setup", "call"))
    if failed:
        _save_evidence(page, request.node.nodeid, tracing_on)
    elif tracing_on:
        try:
            page.context.tracing.stop()  # a passing test: throw the trace away
        except Exception:
            pass


def _login_page(page: Page, role: str) -> Page:
    username, password = _credentials(role)
    ok, message = perform_login(page, LOGIN_URL, username, password)
    assert ok, f"{role.title()} login failed: {message}"
    return page


@pytest.fixture
def login_user(page: Page) -> Page:
    """Page logged in as the standard user. Fails the test if login does not succeed."""
    return _login_page(page, "USER")


@pytest.fixture
def login_admin(page: Page) -> Page:
    """Page logged in as the administrator. Fails the test if login does not succeed."""
    return _login_page(page, "ADMIN")


# ---------------------------------------------------------------------------
# API (HTTP) client fixtures
# ---------------------------------------------------------------------------
def _live_inertia_version(playwright: Playwright) -> str:
    ctx = playwright.request.new_context(ignore_https_errors=True)
    try:
        match = re.search(r'data-page="([^"]+)"', ctx.get(BASE_URL).text())
        return json.loads(html.unescape(match.group(1))).get("version", "") if match else ""
    except Exception:
        return ""
    finally:
        ctx.dispose()


@pytest.fixture(scope="session")
def api_headers(playwright: Playwright) -> dict:
    headers = {"Accept": "application/json, text/html;q=0.9, */*;q=0.8"}
    if IS_INERTIA:
        # Inertia answers X-Inertia requests with JSON; a stale version would give 409 Conflict.
        headers.update({"X-Inertia": "true", "X-Requested-With": "XMLHttpRequest"})
        version = _live_inertia_version(playwright) or SUITE.get("inertia_version", "")
        if version:
            headers["X-Inertia-Version"] = version
    return headers


@pytest.fixture(scope="session")
def api_client(playwright: Playwright, api_headers: dict) -> APIRequestContext:
    """Unauthenticated HTTP client."""
    ctx = playwright.request.new_context(base_url=BASE_URL, extra_http_headers=api_headers, ignore_https_errors=True)
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="session")
def plain_api_client(playwright: Playwright) -> APIRequestContext:
    """
    Unauthenticated client WITHOUT the framework headers (X-Inertia...). HEAD and OPTIONS are protocol checks:
    some servers redirect HEAD forever when those headers are present, which is not a bug in the site.
    """
    ctx = playwright.request.new_context(base_url=BASE_URL, extra_http_headers={"Accept": "*/*"}, ignore_https_errors=True)
    yield ctx
    ctx.dispose()


def _authenticated_api_client(playwright, browser, api_headers, role) -> APIRequestContext:
    username, password = _credentials(role)
    context = browser.new_context(ignore_https_errors=True)
    try:
        page = context.new_page()
        _prepare_page(page)
        ok, message = perform_login(page, LOGIN_URL, username, password)
        state = context.storage_state()
        # Some frameworks bind the session to the User-Agent (session-hijacking protection),
        # so the HTTP client must present the same one as the browser that logged in.
        user_agent = page.evaluate("navigator.userAgent")
    finally:
        context.close()
    assert ok, f"{role.title()} login failed: {message}"
    return playwright.request.new_context(
        base_url=BASE_URL, storage_state=state, extra_http_headers=api_headers,
        user_agent=user_agent, ignore_https_errors=True,
    )


@pytest.fixture(scope="session")
def user_api_client(playwright: Playwright, browser, api_headers: dict) -> APIRequestContext:
    """HTTP client carrying the standard user's session cookies."""
    ctx = _authenticated_api_client(playwright, browser, api_headers, "USER")
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="session")
def admin_api_client(playwright: Playwright, browser, api_headers: dict) -> APIRequestContext:
    """HTTP client carrying the administrator's session cookies."""
    ctx = _authenticated_api_client(playwright, browser, api_headers, "ADMIN")
    yield ctx
    ctx.dispose()
