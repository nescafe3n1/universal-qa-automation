"""
Writers for tests/api/*.py (HTTP-level tests with Playwright's APIRequestContext).

Write-method tests (POST/PUT/PATCH/DELETE) are only generated with
--include-write-tests, because they send real requests to the target site.
"""

from urllib.parse import urlparse

from qa_generator.config import MAX_INTERCEPTED_API_TESTS, WRITE_PROBE_KEYWORDS
from qa_generator.generator.context import SuiteContext
from qa_generator.generator.e2e import fill, header, sent_to_login
from qa_generator.templates.qa_login import is_login_url
from qa_generator.utils import UniqueNamer

API_IMPORTS = "import pytest\nfrom playwright.sync_api import APIRequestContext"
AUTH_API_IMPORTS = API_IMPORTS + "\n\nfrom qa_login import access_blocked, is_login_url"

INERTIA_CHECK = '''    if IS_INERTIA and "application/json" in response.headers.get("content-type", ""):
        data = response.json()
        assert "component" in data and "props" in data, "Not an Inertia page response"
'''


def write_api_tests(ctx: SuiteContext) -> None:
    write_public_routes(ctx)
    write_http_methods(ctx)
    write_write_probes(ctx)
    write_intercepted(ctx)
    write_customer(ctx)
    write_admin(ctx)
    write_access_control(ctx)


def write_public_routes(ctx: SuiteContext) -> None:
    namer = UniqueNamer()
    links = ctx.scan["homepage"].get("nav_links", [])
    # Links that refused a guest during the scan are auth-protected pages, not broken links.
    auth_routes = [(namer(lk["name"], "route"), lk["full_url"], lk["status"]) for lk in links if lk.get("status") in (401, 403)]
    # Links that redirected a guest to the login page also need login; the scan saw the login page's 200, not the page.
    login_routes = [(namer(lk["name"], "route"), lk["full_url"]) for lk in links
                    if lk.get("status") not in (401, 403) and sent_to_login(lk, ctx.login_url)]
    routes = [(namer(lk["name"], "route"), lk["full_url"]) for lk in links
              if lk.get("status") not in (401, 403) and not sent_to_login(lk, ctx.login_url)]
    code = header("HTTP status of the site root and every discovered link (broken-link check), plus 404 handling.",
                  ctx, API_IMPORTS + ("\n\nfrom qa_login import access_blocked" if login_routes else ""), "pytest.mark.api")
    code += '''

@pytest.mark.smoke
def test_api_public_base_status_ok(api_client: APIRequestContext, base_url: str):
    """Verify the site root responds without an error status."""
    response = api_client.get(base_url)
    assert response.status < 400, f"Site root returned HTTP {response.status}"
'''
    if routes:
        code += fill('''

ROUTES = __ROUTES__


@pytest.mark.parametrize("url", [r[1] for r in ROUTES], ids=[r[0] for r in ROUTES])
def test_api_public_route_status(api_client: APIRequestContext, url: str):
    """Verify a discovered link responds without an error status."""
    response = api_client.get(url)
    assert response.status < 400, f"{url} returned HTTP {response.status}"
''', ROUTES=routes)
    if auth_routes:
        code += fill('''

AUTH_ROUTES = __ROUTES__


@pytest.mark.parametrize("url, expected_status", [r[1:] for r in AUTH_ROUTES], ids=[r[0] for r in AUTH_ROUTES])
def test_api_public_route_requires_auth(api_client: APIRequestContext, url: str, expected_status: int):
    """Verify a link that needs authentication still refuses guests."""
    response = api_client.get(url)
    assert response.status == expected_status, f"{url} returned HTTP {response.status}, expected {expected_status} for a guest"
''', ROUTES=auth_routes)
    if login_routes:
        code += fill('''

LOGIN_ROUTES = __ROUTES__


@pytest.mark.parametrize("url", [r[1] for r in LOGIN_ROUTES], ids=[r[0] for r in LOGIN_ROUTES])
def test_api_route_requires_login(api_client: APIRequestContext, login_url: str, url: str):
    """Verify a link that needs login refuses a guest or sends them to the login page."""
    response = api_client.get(url)
    body = response.text() if "html" in response.headers.get("content-type", "") else ""
    shows_password = 'type="password"' in body or "type='password'" in body
    assert access_blocked(response.url, response.status, url, login_url, shows_password), \
        f"{url} gave a guest HTTP {response.status} without asking for login"
''', ROUTES=login_routes)
    code += '''

def test_api_nonexistent_route_404(api_client: APIRequestContext, base_url: str):
    """Verify an unknown URL returns 404 instead of a normal page."""
    response = api_client.get(base_url.rstrip("/") + "/__qa_nonexistent_route_check__")
    assert response.status in (403, 404, 410), \\
        f"Unknown URL returned HTTP {response.status}; a real 404 was expected (soft-404 pages hide broken links)"
'''
    ctx.write_test("api", "test_api_public_routes.py", code)


def write_http_methods(ctx: SuiteContext) -> None:
    code = header("HTTP method handling on the site root."
                  + (" Includes write methods (--include-write-tests)." if ctx.include_write_tests else
                     " Read-only; regenerate with --include-write-tests to add POST/PUT/PATCH/DELETE probes."),
                  ctx, API_IMPORTS, "pytest.mark.api")
    code += '''

def test_http_get_method_status_ok(api_client: APIRequestContext, base_url: str):
    """Verify HTTP GET on the site root succeeds."""
    response = api_client.get(base_url)
    assert response.status < 400, f"GET returned {response.status}"


def test_http_head_method_status(plain_api_client: APIRequestContext, base_url: str):
    """Verify HTTP HEAD is supported on the site root."""
    response = plain_api_client.head(base_url)
    if response.status in (405, 501):
        # Low severity: browsers never send HEAD, but link checkers and monitors do. Reported, not failed.
        pytest.skip(f"WARNING: server answers HEAD with {response.status} (RFC 9110 says GET and HEAD should be supported)")
    assert response.status < 400, f"HEAD returned {response.status}"


def test_http_options_method_handled(plain_api_client: APIRequestContext, base_url: str):
    """Verify HTTP OPTIONS does not crash the server."""
    response = plain_api_client.fetch(base_url, method="OPTIONS")
    assert response.status < 500, f"OPTIONS returned {response.status}"
'''
    if ctx.include_write_tests:
        links = ctx.scan["homepage"].get("nav_links", [])
        sub_endpoint = links[0]["full_url"] if links else ctx.target_url
        code += fill('''

SUB_ENDPOINT = __SUB__
JSON_ACCEPT = {"Accept": "application/json, text/html, */*"}


@pytest.mark.write
def test_http_post_method_handling(api_client: APIRequestContext, base_url: str):
    """Verify an unexpected HTTP POST is rejected or handled without a server error."""
    response = api_client.post(base_url, data={"_qa_probe": "test"}, headers=JSON_ACCEPT)
    assert response.status < 500, f"POST caused a server error: {response.status}"


@pytest.mark.write
def test_http_put_method_handling(api_client: APIRequestContext):
    """Verify an unexpected HTTP PUT is rejected or handled without a server error."""
    response = api_client.put(SUB_ENDPOINT, data={"_qa_probe": "update"}, headers=JSON_ACCEPT)
    assert response.status < 500, f"PUT caused a server error: {response.status}"


@pytest.mark.write
def test_http_patch_method_handling(api_client: APIRequestContext):
    """Verify an unexpected HTTP PATCH is rejected or handled without a server error."""
    response = api_client.patch(SUB_ENDPOINT, data={"_qa_probe": "patch"}, headers=JSON_ACCEPT)
    assert response.status < 500, f"PATCH caused a server error: {response.status}"


@pytest.mark.write
def test_http_delete_method_guard(api_client: APIRequestContext, base_url: str):
    """Verify an unauthenticated DELETE on a made-up resource is refused without a server error."""
    response = api_client.delete(base_url.rstrip("/") + "/__qa_delete_guard_probe__")
    assert response.status < 500, f"DELETE caused a server error: {response.status}"
    assert response.status not in (200, 202, 204), f"DELETE on a non-existent resource reported success ({response.status})"
''', SUB=sub_endpoint)
    ctx.write_test("api", "test_api_http_methods.py", code)


def write_write_probes(ctx: SuiteContext) -> None:
    """Server robustness against write requests on a page that looks like a resource collection."""
    if not ctx.include_write_tests:
        return
    candidates = ctx.scan["homepage"].get("nav_links", []) + ctx.scan.get("sub_pages", [])
    target = next((c.get("full_url") or c.get("url") for c in candidates
                   if any(w in (c.get("full_url") or c.get("url") or "").lower() for w in WRITE_PROBE_KEYWORDS)), None)
    if not target:
        return
    code = header("Write-method robustness probes on a discovered resource page. These do NOT prove CRUD works;\n"
                  "they check that unauthenticated writes are refused without a server error.",
                  ctx, API_IMPORTS, "[pytest.mark.api, pytest.mark.write]")
    code += fill('''

TARGET = __T__
JSON_ACCEPT = {"Accept": "application/json, text/html, */*"}


def test_crud_create_probe(api_client: APIRequestContext):
    """Verify an unauthenticated create (POST) is handled without a server error."""
    response = api_client.post(TARGET, data={"name": "QA Probe Entity"}, headers=JSON_ACCEPT)
    assert response.status < 500, f"POST caused a server error: {response.status}"


def test_crud_update_probe(api_client: APIRequestContext):
    """Verify an unauthenticated update (PUT) is handled without a server error."""
    response = api_client.put(TARGET, data={"name": "QA Probe Updated"}, headers=JSON_ACCEPT)
    assert response.status < 500, f"PUT caused a server error: {response.status}"


def test_crud_delete_probe(api_client: APIRequestContext):
    """Verify an unauthenticated delete of a made-up id is refused without a server error."""
    response = api_client.delete(TARGET.rstrip("/") + "/__qa_crud_test_id__")
    assert response.status < 500, f"DELETE caused a server error: {response.status}"
    assert response.status not in (200, 202, 204), f"DELETE of a non-existent id reported success ({response.status})"
''', T=target)
    ctx.write_test("api", "test_api_crud_lifecycle.py", code)


def write_intercepted(ctx: SuiteContext) -> None:
    """Replay same-site XHR/fetch calls seen during the scan, grouped by the session that made them."""
    clients = {"public": "api_client", "user": "user_api_client", "admin": "admin_api_client"}
    available = {"public": True, "user": bool(ctx.user_acc), "admin": bool(ctx.admin_acc)}
    groups = {role: [] for role in clients}
    namer = UniqueNamer()
    skipped = 0

    for call in ctx.scan.get("captured_apis", []):
        role = call.get("role", "public")
        if not available.get(role):
            continue
        if call.get("needs_bearer_token") or is_login_url(call["url"], ctx.login_url):
            skipped += 1
            continue
        if call["method"] not in ("GET", "HEAD") and not ctx.include_write_tests:
            skipped += 1
            continue
        if sum(len(g) for g in groups.values()) >= MAX_INTERCEPTED_API_TESTS:
            break
        test_id = namer(f"{call['method']}_{urlparse(call['url']).path.replace('/', '_')}", "endpoint")
        groups[role].append((test_id, call["method"], call["url"], call["status"], call["sample_keys"], call["json_is_list"]))

    if not any(groups.values()):
        return

    code = header("Replays API calls the site made during the scan and checks status + JSON shape.\n"
                  f"{skipped} call(s) were not replayed (token-authenticated, login, or write methods).",
                  ctx, API_IMPORTS, "pytest.mark.api")
    code += '''


def _check(response, method, url, expected_status, keys, is_list):
    assert response.status == expected_status or (expected_status < 400 and response.status < 400), \\
        f"{method} {url} returned {response.status}, scan saw {expected_status}"
    if keys and "json" in response.headers.get("content-type", ""):
        data = response.json()
        if is_list:
            assert isinstance(data, list), "Expected a JSON list"
            if not data:
                return
            data = data[0]
        missing = [k for k in keys if k not in data]
        assert not missing, f"JSON response is missing keys seen during the scan: {missing}"
'''
    for role, calls in groups.items():
        if not calls:
            continue
        client = clients[role]
        marks = "\n@pytest.mark.auth" if role != "public" else ""
        code += fill('''

''' + role.upper() + '''_CALLS = __CALLS__

''' + marks + '''
@pytest.mark.parametrize("method, url, expected_status, keys, is_list", [c[1:] for c in ''' + role.upper() + '''_CALLS],
                         ids=[c[0] for c in ''' + role.upper() + '''_CALLS])
def test_api_intercepted_''' + role + '''(''' + client + ''': APIRequestContext, method, url, expected_status, keys, is_list):
    """Verify an API call observed during the scan still answers the same way."""
    response = ''' + client + '''.fetch(url, method=method)
    _check(response, method, url, expected_status, keys, is_list)
''', CALLS=calls)
    ctx.write_test("api", "test_api_intercepted.py", code)


def _http_fetchable(session, url) -> bool:
    """True if the scan saw the logged-in session fetch this URL over plain HTTP (older scans: assume yes)."""
    urls = (session or {}).get("http_ok_urls")
    return True if urls is None else url in urls


def _role_pages_file(ctx: SuiteContext, role: str, landing: str, pages: list, filename: str, doc: str) -> None:
    client = f"{role}_api_client"
    prefix = "customer" if role == "user" else "admin"
    code = header(doc, ctx, AUTH_API_IMPORTS, "[pytest.mark.api, pytest.mark.auth]")
    code += fill('''
IS_INERTIA = __INERTIA__
''', INERTIA=ctx.is_inertia)
    if landing:
        code += fill('''

def test_api_''' + prefix + '''_landing_endpoint(''' + client + ''': APIRequestContext, login_url: str):
    """Verify the logged-in session can fetch the landing page directly."""
    response = ''' + client + '''.get(__URL__)
    assert response.status < 400, f"Landing page returned {response.status}"
    assert not is_login_url(response.url, login_url), "Session rejected: redirected to login"
''', URL=landing) + INERTIA_CHECK
    if pages:
        code += fill('''

PAGES = __PAGES__


@pytest.mark.parametrize("url", [p[1] for p in PAGES], ids=[p[0] for p in PAGES])
def test_api_''' + prefix + '''_page(''' + client + ''': APIRequestContext, login_url: str, url: str):
    """Verify the logged-in session can fetch a page directly."""
    response = ''' + client + '''.get(url)
    assert response.status < 400, f"{url} returned {response.status}"
    assert not is_login_url(response.url, login_url), f"Session rejected at {url}: redirected to login"
''', PAGES=pages) + INERTIA_CHECK
    ctx.write_test("api", filename, code)


def write_customer(ctx: SuiteContext) -> None:
    session = ctx.scan.get("user_session")
    if not (ctx.user_acc and session):
        return
    namer = UniqueNamer()
    pages = [(namer(lk["name"], "page"), lk["url"]) for lk in session.get("sublinks", [])[:6]]
    pages = [p for p in pages if _http_fetchable(session, p[1])]
    landing = ctx.user_target_url if _http_fetchable(session, ctx.user_target_url) else None
    _role_pages_file(ctx, "user", landing, pages, "test_api_customer.py",
                     "Standard user's session used directly over HTTP.")


def write_admin(ctx: SuiteContext) -> None:
    session = ctx.scan.get("admin_session")
    if not (ctx.admin_acc and session):
        return
    namer = UniqueNamer()
    pages = [(namer(sp["path"].replace("/", "_"), "page"), sp["url"])
             for sp in session.get("subpages", []) if sp.get("status") is None or sp["status"] < 400]
    pages = [p for p in pages if _http_fetchable(session, p[1])]
    landing = ctx.admin_target_url if _http_fetchable(session, ctx.admin_target_url) else None
    _role_pages_file(ctx, "admin", landing, pages, "test_api_admin.py",
                     "Administrator's session used directly over HTTP.")


def write_access_control(ctx: SuiteContext) -> None:
    tests = []
    user_t, admin_t = ctx.user_guard_url, ctx.admin_guard_url  # pages the scan saw guests being refused from

    sessions = {"user": ctx.scan.get("user_session"), "admin": ctx.scan.get("admin_session")}
    for role, guard, target in (("user", user_t, ctx.user_target_url), ("admin", admin_t, ctx.admin_target_url)):
        # A page that only exists inside the browser (404 over plain HTTP) would be "refused" for everyone,
        # so a guest test on it would pass for the wrong reason. Only pages the session fetched over HTTP count.
        if ctx.is_protected_target(guard) and _http_fetchable(sessions[role], guard):
            tests.append(fill('''
def test_api_unauthenticated_''' + role + '''_route_guard(api_client: APIRequestContext, login_url: str):
    """Verify a guest HTTP request to the ''' + role + ''' area is refused or sent to login."""
    target = __T__
    response = api_client.get(target)
    assert _blocked(response, target, login_url), f"Guest got {response.url} (HTTP {response.status}) without logging in"
''', T=guard))
        acc = ctx.user_acc if role == "user" else ctx.admin_acc
        if acc and ctx.is_protected_target(target) and _http_fetchable(sessions[role], target):
            tests.append(fill('''
@pytest.mark.auth
def test_api_authenticated_''' + role + '''_access(''' + role + '''_api_client: APIRequestContext, login_url: str):
    """Verify the ''' + role + ''' session can open its own area."""
    response = ''' + role + '''_api_client.get(__T__)
    assert response.status < 400, f"HTTP {response.status}"
    assert not is_login_url(response.url, login_url), "Session rejected: redirected to login"
''', T=target))

    if (ctx.user_acc and ctx.is_protected_target(admin_t) and urlparse(admin_t).path != urlparse(ctx.user_target_url or "").path
            and _http_fetchable(sessions["admin"], admin_t)):
        tests.append(fill('''
@pytest.mark.auth
def test_api_user_privilege_escalation_guard(user_api_client: APIRequestContext, login_url: str):
    """Verify a standard user's session cannot fetch the admin area."""
    target = __T__
    response = user_api_client.get(target)
    assert _blocked(response, target, login_url), f"Standard user got {response.url} (HTTP {response.status})"
''', T=admin_t))

    if not tests:
        return
    code = header("HTTP-level access control for protected areas.", ctx, AUTH_API_IMPORTS, "pytest.mark.api")
    code += '''


def _blocked(response, target, login_url):
    body = response.text() if "html" in response.headers.get("content-type", "") else ""
    shows_password = 'type="password"' in body or "type='password'" in body
    return access_blocked(response.url, response.status, target, login_url, shows_password)

''' + "\n".join(tests)
    ctx.write_test("api", "test_api_access_control.py", code)
