"""
12-column QA test-case reporter (CSV + HTML dashboard) for Nes-Dev QA suites.

Wired up by conftest.py:
    pytest_collection_modifyitems -> assign_test_case_ids(items)
    pytest_runtest_makereport     -> record_test_result(item, report)
    pytest_sessionfinish          -> generate_csv_reports()
"""

import csv
import html
import json
import os
import re
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(ROOT_DIR, "reports")
RUNS_DIR = os.path.join(REPORTS_DIR, "runs")
EVIDENCE_DIR = os.path.join(REPORTS_DIR, "evidence")   # a screenshot and a trace for every failed test

HISTORY_FILE = os.path.join(REPORTS_DIR, ".run_history.json")
COMPARISON_MATRIX_FILE = os.path.join(REPORTS_DIR, "test_runs_comparison_matrix.csv")
LATEST_RUN_FILE = os.path.join(REPORTS_DIR, "latest_test_run.csv")
MASTER_TEST_CASES_FILE = os.path.join(REPORTS_DIR, "master_test_cases.csv")
CUMULATIVE_HISTORY_FILE = os.path.join(REPORTS_DIR, "test_runs_history.csv")
HTML_REPORT_FILE = os.path.join(REPORTS_DIR, "index.html")
HISTORY_FORMAT = 2  # v2: runs keyed by pytest node id (stable across runs)

try:
    with open(os.path.join(ROOT_DIR, "suite_config.json"), encoding="utf-8") as _f:
        _SUITE = json.load(_f)
except Exception:
    _SUITE = {}

TARGET_URL = _SUITE.get("base_url", "")
TARGET_DISPLAY = _SUITE.get("target_display") or TARGET_URL or "Web Application"
COVERAGE_NOTES = _SUITE.get("coverage_notes") or []
RUN_WARNINGS = []  # filled by conftest.py during the run (e.g. 'stopped early because the site kept timing out')

COLUMNS = [
    "Test Case ID", "Module / Feature", "Test Scenario / Objective", "Preconditions",
    "Test Steps", "Test Data", "Expected Result", "Actual Result", "Status",
    "Priority", "Severity", "Defects / Notes",
]
BROWSER_PARAMS = {"chromium", "firefox", "webkit"}

_CURRENT_RUN_RESULTS = {}
_TC_IDS = {}


def evidence_id(nodeid: str) -> str:
    """The folder name for a test's evidence: its report ID (TC-NAV-001), or a safe version of its name."""
    known = (_CURRENT_RUN_RESULTS.get(nodeid) or {}).get("Test Case ID") or _TC_IDS.get(nodeid)
    return known or re.sub(r"[^A-Za-z0-9_.-]+", "_", nodeid)[-80:]


def evidence_folder(nodeid: str) -> str:
    return os.path.join(EVIDENCE_DIR, evidence_id(nodeid))


def evidence_for(tc_id: str) -> dict:
    """What was saved for a failed test: paths relative to reports/index.html, plus the page address (empty if nothing)."""
    folder = os.path.join(EVIDENCE_DIR, tc_id)
    found = {}
    for key, name in (("screenshot", "failure.png"), ("trace", "trace.zip")):
        if os.path.exists(os.path.join(folder, name)):
            found[key] = f"evidence/{tc_id}/{name}"
    try:
        with open(os.path.join(folder, "page.txt"), encoding="utf-8") as f:
            found["page"] = f.read().strip()
    except OSError:
        pass
    return found


def _user_email() -> str:
    return os.environ.get("QA_USER_USERNAME") or "configured user"


def _admin_email() -> str:
    return os.environ.get("QA_ADMIN_USERNAME") or "configured admin"


def _is_timeout_message(message: str) -> bool:
    """Playwright navigation / request timeouts ('Timeout 30000ms exceeded'), as opposed to a failed assertion."""
    return "Timeout" in message and "exceeded" in message


def _strip_ansi(text: str) -> str:
    return re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', text)


def _simplify_error(msg: str) -> str:
    """Turn raw pytest/Playwright error text into one short, direct sentence."""
    msg = re.sub(r"^(?:[\w.]*\.)?(?:AssertionError|Error|Failed|TimeoutError):\s*", "", msg.strip())
    timeout = re.search(r"(?:\w+\.)?(\w+\.\w+): Timeout (\d+)ms exceeded", msg)
    if timeout:
        call, ms = timeout.groups()
        return f"Timed out after {int(ms) / 1000:g}s waiting on {call}."
    # Playwright's own check messages ("Locator expected to be visible ... element(s) not found") in plain words
    locator = re.match(r"Locator expected to (.+?)(?:\s+Actual value:|\s+Error:|\s+Call log:|$)", msg)
    if locator:
        wanted = locator.group(1).strip()
        if "element(s) not found" in msg:
            return f"The element was not found on the page (the test expected it to {wanted})."
        if wanted == "be visible":
            return "The element is on the page but it is not visible."
        return f"The element was not as expected: it should {wanted}."
    address = re.match(r"Page URL expected to .+?\s+Actual value:\s*(\S+)", msg)
    if address:
        return f"The page ended on {address.group(1)}, not on the expected address."
    msg = re.split(r"\s+(?:assert|\+\s*where)\s", msg, maxsplit=1)[0]
    msg = re.split(r"\s+Call log:", msg, maxsplit=1)[0].strip()
    msg = msg[:200] or "Test failed with no message."
    return msg if msg.endswith((".", "!", "?")) else msg + "."


SIDES = [("public", "Guest / Public"), ("user", "User Account"), ("admin", "Admin Account")]
SIDE_LABELS = dict(SIDES)


def _side_for(prefix: str, base_name: str) -> str:
    """Which account a test belongs to: the session it runs as, or the area it guards."""
    if prefix in ("ADM", "API-ADM"):
        return "admin"
    if prefix in ("USR", "API-USR"):
        return "user"
    if prefix in ("SEC", "API-SEC"):
        if "escalation" in base_name or ("authenticated_user" in base_name and "unauthenticated" not in base_name):
            return "user"
        if "admin" in base_name:
            return "admin"
        if "unauthenticated_user" in base_name:
            return "user"
    return "public"


def _file_and_base(item):
    clean_node = item.nodeid.replace("\\", "/")
    base_name = item.name.split("[")[0].replace("test_", "", 1)
    return clean_node, base_name


def _param_label(item) -> str:
    """Readable label from parametrize ids, ignoring pytest-playwright's browser id."""
    callspec = getattr(item, "callspec", None)
    if not callspec:
        return ""
    parts = [p for p in callspec.id.split("-") if p not in BROWSER_PARAMS]
    return " ".join(parts).replace("_", " ").strip().title()


def _is_form_test(base_name: str) -> bool:
    """True for user_form_* / admin_form_* tests, not for pages that merely contain 'form' (e.g. 'information')."""
    return "_form_" in f"_{base_name}_"


def _prefix_for(clean_node: str) -> str:
    table = [
        ("test_navigation", "NAV"), ("test_components", "CMP"), ("test_forms", "FRM"),
        ("test_user_session", "USR"), ("test_admin_portal", "ADM"), ("test_access_control", "SEC"),
        ("test_api_http_methods", "API-HTTP"), ("test_api_crud", "API-CRUD"),
        ("test_api_intercepted", "API-INT"), ("test_api_public", "API-PUB"),
        ("test_interactions", "INT"), ("test_accessibility", "A11Y"), ("test_api_customer", "API-USR"), ("test_api_admin", "API-ADM"), ("test_api_access", "API-SEC"),
    ]
    return next((prefix for marker, prefix in table if marker in clean_node), "GEN")


def assign_test_case_ids(items) -> None:
    """
    Give every collected test a Test Case ID in collection order, per module prefix.
    Runs before -m/-k deselection, so filtering a run does not shift the IDs.
    """
    counters = {}
    for item in items:
        clean_node, _ = _file_and_base(item)
        prefix = _prefix_for(clean_node)
        counters[prefix] = counters.get(prefix, 0) + 1
        _TC_IDS[item.nodeid] = f"TC-{prefix}-{counters[prefix]:03d}"


def _feature_for(prefix: str, base_name: str, label: str) -> str:
    sub = f" - {label}" if label else ""
    if prefix == "NAV":
        if "responsive" in base_name:
            return "Mobile & Responsive Layout"
        if "public_route" in base_name or "nav_link" in base_name:
            return f"Public Routes{sub}"
        if "hero" in base_name or "homepage" in base_name or "cta" in base_name:
            return "Homepage & Hero Banner"
        if "console" in base_name:
            return "Console & Script Stability"
        if "skip_link" in base_name:
            return "Accessibility - Skip Link"
        return "Public Navigation"
    if prefix == "CMP":
        if "modal" in base_name:
            return "UI Components - Interactive Modal Dialog"
        if "filter_dropdown" in base_name:
            return f"UI Components - Dropdown Filter ({base_name.replace('filter_dropdown_', '').replace('_', ' ').title()})"
        if "filter" in base_name:
            return f"UI Components - Filter Control ({base_name.replace('filter_control_', '').replace('_', ' ').title()})"
        if "table" in base_name:
            return "UI Components - Data Grid Table"
        if "search" in base_name:
            return "Search & Filtering"
        if "repeating" in base_name:
            return f"Repeating Content Items ({base_name.replace('repeating_content_items_', '').replace('_', ' ').title()})"
        return "UI Components & Controls"
    if prefix == "FRM":
        kind = "Form Empty Submit" if "empty_submit" in base_name else "Form Submit" if "submit" in base_name else "Form Fields"
        group = re.sub(r"^form_(?:inputs|empty_submit|submit)_", "", base_name).replace("_", " ").title()
        return f"{kind} ({'Popup Dialog' if group == 'Modal' else group})"
    if prefix == "A11Y":
        return f"Accessibility - {label or 'Page'}"
    if prefix == "INT" and base_name.startswith("type_into_"):
        return "UI Interactions - Typing in a box"
    if prefix == "INT":
        for key, label_ in (("tabs", "Tabs"), ("toggle", "Accordion / Menu Toggle"), ("pagination", "Pagination"),
                            ("carousel", "Carousel"), ("upload", "File Upload")):
            if key in base_name:
                return f"UI Interactions - {label_}"
        return "UI Interactions"
    if prefix in ("USR", "ADM") and _is_form_test(base_name):
        return f"{'Admin' if prefix == 'ADM' else 'Customer'} Portal - Forms"
    if prefix == "USR":
        if "logout" in base_name:
            return "Customer Session Logout"
        if "login" in base_name:
            return "Customer Authentication"
        return f"Customer Portal{sub}"
    if prefix == "ADM":
        if "dashboard" in base_name:
            return "Admin Dashboard & Overview"
        return f"Admin Portal{sub}"
    if prefix in ("SEC", "API-SEC"):
        kind = "API Security" if prefix == "API-SEC" else "RBAC"
        if "escalation" in base_name:
            return f"{kind} - Privilege Escalation Guard"
        if "unauthenticated_admin" in base_name:
            return f"{kind} - Unauthenticated Admin Route Guard"
        if "unauthenticated_user" in base_name:
            return f"{kind} - Unauthenticated User Route Guard"
        if "authenticated_admin" in base_name:
            return f"{kind} - Admin Access Authorized"
        if "authenticated_user" in base_name:
            return f"{kind} - Customer Access Authorized"
        return "Role-Based Access Control (RBAC)"
    if prefix == "API-HTTP":
        for verb in ("get", "post", "put", "patch", "delete", "options", "head"):
            if f"http_{verb}_" in f"{base_name}_" or base_name.startswith(f"http_{verb}"):
                return f"HTTP Method - {verb.upper()}"
        return "HTTP Protocol Methods"
    if prefix == "API-CRUD":
        return "Write-Method Robustness Probe"
    if prefix == "API-INT":
        return f"Intercepted API{sub}"
    if prefix == "API-PUB":
        if "404" in base_name or "nonexistent" in base_name:
            return "API Error Handling (404 Not Found)"
        if "route" in base_name and label:
            return f"Public Route Status{sub}"
        return "Public API - Base Endpoint"
    if prefix == "API-USR":
        return f"Customer API{sub}" if label else "Customer API - Landing Endpoint"
    if prefix == "API-ADM":
        return f"Admin API{sub}" if label else "Admin API - Dashboard Endpoint"
    return "General Test Suite"


def _derive_test_case_metadata(item, duration: float, status: str, error_msg: str, retried: bool = False) -> dict:
    clean_node, base_name = _file_and_base(item)
    prefix = _prefix_for(clean_node)
    label = _param_label(item)
    feature = _feature_for(prefix, base_name, label)
    tc_id = _TC_IDS.get(item.nodeid) or f"TC-{prefix}-X{len(_CURRENT_RUN_RESULTS) + 1:03d}"

    doc = (getattr(getattr(item, "function", None), "__doc__", "") or "").strip()
    if doc:
        scenario = doc.split("\n")[0].strip().rstrip(".")
        if scenario.lower().startswith("verify "):
            scenario = scenario[7:]
        scenario = scenario[:1].upper() + scenario[1:]
    else:
        scenario = "Verify " + re.sub(r'^(public_route_|api_|subpage_|user_view_|admin_subpage_)', '', base_name).replace("_", " ")
    if label:
        scenario = f"{scenario} — {label}"

    if prefix in ("ADM", "API-ADM"):
        preconditions = f"Application online; session authenticated as Administrator ({_admin_email()})."
    elif prefix in ("USR", "API-USR"):
        preconditions = f"Application online; session authenticated as Customer ({_user_email()})."
    elif prefix in ("SEC", "API-SEC"):
        if "escalation" in base_name:
            preconditions = f"Application online; session authenticated as standard Customer ({_user_email()})."
        elif "authenticated_admin" in base_name:
            preconditions = f"Application online; session authenticated as Administrator ({_admin_email()})."
        elif "authenticated_user" in base_name and "unauthenticated" not in base_name:
            preconditions = f"Application online; session authenticated as Customer ({_user_email()})."
        else:
            preconditions = "Application online; client session is unauthenticated / guest."
    elif prefix == "API-INT":
        preconditions = "Application online; endpoint was observed in live traffic during the site scan."
    elif prefix in ("API-HTTP", "API-CRUD"):
        preconditions = "Application online; target endpoint reachable."
    else:
        preconditions = "Target application is accessible; client session is unauthenticated / guest."

    if prefix == "API-HTTP":
        steps = "1. Send the HTTP request with the given method.\n2. Read the response status.\n3. Verify the server handles it without a 5xx error."
    elif prefix == "API-CRUD":
        steps = "1. Send POST/PUT/PATCH/DELETE probes to a discovered page.\n2. Verify the server rejects or handles them without a 5xx error."
    elif prefix == "API-INT":
        steps = "1. Replay the observed request with the matching session.\n2. Verify the status matches the recorded one.\n3. Verify the JSON payload still has the recorded keys."
    elif prefix == "A11Y":
        steps = "1. Open the page.\n2. Check it with axe-core against the WCAG 2 A and AA rules.\n3. Verify there are no new critical or serious problems."
    elif prefix == "INT" and base_name.startswith("type_into_"):
        steps = ("1. Open the page.\n2. Type text into the box and press Enter.\n3. Verify the result the scan saw "
                 "(the text appears on the page, or the page address changes)." if base_name.endswith("_and_press_enter")
                 else "1. Open the page.\n2. Type text into the box.\n3. Verify the box keeps the text.")
    elif prefix == "INT":
        steps = {
            "tabs": "1. Open the page.\n2. Click each tab in turn.\n3. Verify the tab becomes selected and its panel is shown.",
            "toggle": "1. Open the page.\n2. Click the toggle (accordion header or menu button).\n3. Verify it opens or closes.",
            "pagination": "1. Open the page.\n2. Click the next-page control.\n3. Verify the URL or the page content changes.",
            "carousel": "1. Open the page.\n2. Click the carousel's next button.\n3. Verify the slide content changes.",
            "upload": "1. Open the page.\n2. Attach a small test file to the upload field.\n3. Verify the field holds the file (nothing is submitted).",
        }.get(next((k for k in ("tabs", "toggle", "pagination", "carousel", "upload") if k in base_name), ""),
              "1. Open the page.\n2. Use the widget.\n3. Verify it responds.")
    elif prefix in ("USR", "ADM") and _is_form_test(base_name):
        role = "Administrator" if prefix == "ADM" else "Customer"
        action = ("2. Leave every field empty and click submit.\n3. Verify a validation error is shown." if "empty_submit" in base_name
                  else "2. Fill every field and click submit.\n3. Verify a visible response and no server or JavaScript error." if "submit" in base_name
                  else "2. Fill every field (text, dropdown, checkbox, radio, file...).\n3. Verify each field holds its value.")
        steps = f"1. Log in as {role} and open the page with the form.\n{action}"
    elif prefix == "FRM" and "empty_submit" in base_name:
        steps ="1. Open the page containing the form (open the popup first if it is in a dialog).\n2. Leave every field empty.\n3. Click the submit button.\n4. Verify a validation error is shown and nothing is accepted."
    elif prefix == "FRM" and "submit" in base_name:
        steps = "1. Open the page containing the form (open the popup first if it is in a dialog).\n2. Fill every field.\n3. Click the submit button.\n4. Verify a visible response (message, redirect or error) with no server error (5xx) and no JavaScript error."
    elif prefix == "FRM":
        steps = "1. Open the page containing the form.\n2. Fill every field (text, dropdown, checkbox, radio, date...).\n3. Verify each field holds the value and the submit control is visible."
    elif "modal" in base_name:
        steps = "1. Click the modal trigger.\n2. Verify a dialog becomes visible.\n3. Close it (button or Escape) and verify it is hidden."
    elif "filter" in base_name:
        steps = "1. Locate the filter control.\n2. Toggle the button or select an option.\n3. Verify the control reflects the new state."
    elif prefix in ("SEC", "API-SEC"):
        steps = "1. Prepare the client with the stated session.\n2. Request the protected URL directly.\n3. Verify access is refused (login redirect, 401/403/404) or granted, as expected."
    elif "api" in clean_node:
        steps = "1. Configure the HTTP client for the stated session.\n2. Send a GET request to the endpoint.\n3. Verify the response status (and not redirected to login)."
    elif prefix == "ADM":
        steps = "1. Log in with Administrator credentials.\n2. Open the admin page.\n3. Verify it loads without a login redirect and key elements render."
    elif prefix == "USR":
        steps = "1. Log in with Customer credentials.\n2. Open the account page.\n3. Verify it loads without a login redirect."
    elif "components" in clean_node:
        steps = "1. Open the page.\n2. Locate the component.\n3. Verify it renders the expected items."
    else:
        steps = "1. Open the target URL in Chromium.\n2. Wait for the page to load.\n3. Verify status, title and key elements."

    if prefix == "API-INT":
        test_data = f"Endpoint: {label or base_name}"
    elif prefix == "FRM":
        test_data = "Name='QA Test', Email='qa_test@example.com', Number/Tel='1234567890'"
    elif prefix in ("USR", "API-USR"):
        test_data = f"Account: {_user_email()}, Role: Customer"
    elif prefix in ("ADM", "API-ADM"):
        test_data = f"Account: {_admin_email()}, Role: Administrator"
    elif prefix in ("SEC", "API-SEC"):
        test_data = "Target: protected URL; attempted role: guest / standard user"
    elif label:
        test_data = f"Target: {label}"
    else:
        test_data = f"URL: {TARGET_URL or 'target site base URL'}"

    if prefix in ("SEC", "API-SEC"):
        expected = ("Access granted to the authorised role." if base_name.startswith(("api_authenticated", "authenticated"))
                    else "Access refused: login redirect or 401/403/404. No restricted content shown.")
    elif prefix in ("API-HTTP", "API-CRUD"):
        expected = "Request handled without a 5xx server error."
    elif prefix == "API-INT":
        expected = "Status matches the observed call and the JSON payload keeps its recorded keys."
    elif prefix == "A11Y":
        expected = "No new critical or serious accessibility problems (existing ones are shown as a warning)."
    elif prefix == "INT":
        expected = "The widget reacts to the click exactly as it did during the site scan."
    elif prefix in ("USR", "ADM") and "empty_submit" in base_name:
        expected = "Empty form is refused with a visible validation error."
    elif prefix in ("USR", "ADM") and _is_form_test(base_name) and "submit" in base_name:
        expected = "Form shows a visible response (message, redirect or error) and causes no server or JavaScript error."
    elif prefix in ("USR", "ADM") and _is_form_test(base_name):
        expected = "Fields accept and keep input; submit control is available."
    elif prefix == "FRM" and "empty_submit" in base_name:
        expected ="Empty form is refused with a visible validation error."
    elif prefix == "FRM" and "submit" in base_name:
        expected = "Form shows a visible response (message, redirect or error) and causes no server or JavaScript error."
    elif prefix == "FRM":
        expected = "Fields accept and keep input; submit control is available."
    elif "modal" in base_name:
        expected = "Dialog opens on click and closes again."
    elif "filter" in base_name:
        expected = "Filter control changes state without errors."
    else:
        expected = "Page/endpoint responds with a non-error status and renders the expected elements."

    side = _side_for(prefix, base_name)
    problem = _simplify_error(error_msg) if error_msg else ""

    if status == "PASSED":
        actual = f"Passed in {duration}s."
    elif status == "FAILED":
        actual = f"Failed: {problem or 'Test failed with no message.'}"
    else:
        actual = f"Skipped: {problem}" if problem else "Skipped."

    if prefix in ("SEC", "API-SEC") or "login" in base_name or "dashboard" in base_name:
        priority, severity = "Critical", "Critical"
    elif prefix in ("ADM", "API-ADM", "USR", "API-USR", "FRM", "API-PUB", "A11Y"):
        priority, severity = "High", "Major"
    elif prefix in ("CMP", "API-INT", "API-HTTP", "API-CRUD"):
        priority, severity = "Medium", "Minor"
    elif "responsive" in base_name or "console" in base_name:
        priority, severity = "Low", "Low"
    else:
        priority, severity = "Medium", "Minor"

    timed_out = status == "FAILED" and _is_timeout_message(error_msg)
    if status == "PASSED":
        defects = "Passed on the second try: the first attempt timed out (slow site)." if retried else "None."
    elif status == "SKIPPED":
        defects = problem or "Not executed."
    elif timed_out:
        defects = (f"Timed out on the {SIDE_LABELS[side]} side: the site was too slow or not answering. "
                   "This is not a confirmed bug; run again to check.")
    else:
        defects = f"Failed on the {SIDE_LABELS[side]} side."

    return {
        "Test Case ID": tc_id,
        "Module / Feature": feature,
        "Test Scenario / Objective": scenario,
        "Preconditions": preconditions,
        "Test Steps": steps,
        "Test Data": test_data,
        "Expected Result": expected,
        "Actual Result": actual,
        "Status": status,
        "Priority": priority,
        "Severity": severity,
        "Defects / Notes": defects,
        "duration": duration,
        "node_id": item.nodeid,
        "side": side,
        "timed_out": timed_out,
        "retried": retried,
    }


def record_test_result(item, report) -> None:
    is_call = report.when == "call"
    setup_problem = report.when == "setup" and (report.failed or report.skipped)
    if not (is_call or setup_problem):
        return
    duration = round(getattr(report, "duration", 0.0), 3)
    status = "PASSED" if report.passed else ("SKIPPED" if report.skipped else "FAILED")
    error_msg = ""
    if report.failed:
        crash = getattr(report.longrepr, "reprcrash", None)
        error_msg = str(crash.message if crash else report.longrepr)
    elif report.skipped and isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
        error_msg = str(report.longrepr[2]).removeprefix("Skipped: ")
    error_msg = _strip_ansi(error_msg.replace("\n", " "))[:300]
    retried = any(key == "retried_after_timeout" for key, _ in getattr(report, "user_properties", []))
    _CURRENT_RUN_RESULTS[item.nodeid] = _derive_test_case_metadata(item, duration, status, error_msg, retried)


def _row(res: dict) -> list:
    return [res[c] for c in COLUMNS]


def _load_history() -> list:
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f_in:
            data = json.load(f_in)
        return [run for run in data if run.get("format") == HISTORY_FORMAT]
    except Exception:
        return []


def _status_of(result_text: str) -> str:
    """'PASSED (1.2s)' -> 'PASSED'."""
    return result_text.split(" ")[0]


def compare_runs(history: list):
    """
    What changed between the last two runs, as lists of test node ids:
    newly failing (passed or skipped before), fixed (failed before), still failing, and new tests.
    Returns None when there is no earlier run to compare with.
    """
    if len(history) < 2:
        return None
    previous, current = history[-2], history[-1]
    changes = {"previous_time": previous.get("timestamp", ""), "newly_failing": [], "fixed": [], "still_failing": [],
               "new_tests": [], "not_run": 0, "labels": {**previous.get("labels", {}), **current.get("labels", {})}}
    for node, result in current["results"].items():
        now = _status_of(result)
        if node not in previous["results"]:
            changes["new_tests"].append(node)
            continue
        before = _status_of(previous["results"][node])
        if now == "FAILED" and before != "FAILED":
            changes["newly_failing"].append(node)
        elif now != "FAILED" and before == "FAILED":
            changes["fixed"].append(node)
        elif now == "FAILED":
            changes["still_failing"].append(node)
    changes["not_run"] = sum(1 for node in previous["results"] if node not in current["results"])
    return changes


def generate_csv_reports() -> None:
    if not _CURRENT_RUN_RESULTS:
        return

    os.makedirs(RUNS_DIR, exist_ok=True)
    now = datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
    file_timestamp = now.strftime("%Y%m%d_%H%M%S")
    results = sorted(_CURRENT_RUN_RESULTS.values(), key=lambda r: r["Test Case ID"])

    run_file_path = os.path.join(RUNS_DIR, f"test_run_{file_timestamp}.csv")
    for path in (run_file_path, LATEST_RUN_FILE, MASTER_TEST_CASES_FILE):
        with open(path, mode="w", newline="", encoding="utf-8-sig") as f_out:
            writer = csv.writer(f_out)
            writer.writerow(COLUMNS)
            writer.writerows(_row(r) for r in results)

    file_exists = os.path.isfile(CUMULATIVE_HISTORY_FILE)
    with open(CUMULATIVE_HISTORY_FILE, mode="a", newline="", encoding="utf-8-sig") as f_hist:
        writer = csv.writer(f_hist)
        if not file_exists:
            writer.writerow(["Run Timestamp"] + COLUMNS)
        writer.writerows([timestamp_str] + _row(r) for r in results)

    history = _load_history()
    history.append({
        "format": HISTORY_FORMAT,
        "run_id": f"Run_{file_timestamp}",
        "timestamp": timestamp_str,
        "results": {r["node_id"]: f"{r['Status']} ({r['duration']}s)" for r in results},
        "labels": {r["node_id"]: f"{r['Test Case ID']}  {r['Test Scenario / Objective']}" for r in results},
    })
    with open(HISTORY_FILE, "w", encoding="utf-8") as f_out:
        json.dump(history, f_out, indent=2)

    with open(COMPARISON_MATRIX_FILE, mode="w", newline="", encoding="utf-8-sig") as f_mat:
        writer = csv.writer(f_mat)
        writer.writerow(["Test Case ID", "Module / Feature", "Test Scenario / Objective"]
                        + [f"{run['run_id']} [{run['timestamp']}]" for run in history])
        for r in results:
            writer.writerow([r["Test Case ID"], r["Module / Feature"], r["Test Scenario / Objective"]]
                            + [run["results"].get(r["node_id"], "N/A") for run in history])

    passed = sum(1 for r in results if r["Status"] == "PASSED")
    failed = sum(1 for r in results if r["Status"] == "FAILED")
    skipped = sum(1 for r in results if r["Status"] == "SKIPPED")
    total_duration = round(sum(r["duration"] for r in results), 2)
    _generate_html_report(results, timestamp_str, passed, failed, skipped, total_duration, compare_runs(history))

    print("\n[Reports Generated with 12 QA Columns]")
    print(f" - Latest CSV Report : {LATEST_RUN_FILE}")
    print(f" - Master Test Cases : {MASTER_TEST_CASES_FILE}")
    print(f" - Comparison Matrix : {COMPARISON_MATRIX_FILE}")
    print(f" - Visual Dashboard  : {HTML_REPORT_FILE}")


def _generate_html_report(results, run_timestamp, total_passed, total_failed, total_skipped, total_duration, changes=None) -> None:
    e = html.escape
    total_tests = len(results)
    pass_pct = round(total_passed / total_tests * 100, 1) if total_tests else 0

    change_of = {}
    if changes:
        change_of = {**{n: "new failure" for n in changes["newly_failing"]}, **{n: "fixed" for n in changes["fixed"]},
                     **{n: "new test" for n in changes["new_tests"]}}
    rows = []
    for side, side_label in SIDES:
        group = [r for r in results if r["side"] == side]
        if not group:
            continue
        n_fail = sum(1 for r in group if r["Status"] == "FAILED")
        n_pass = sum(1 for r in group if r["Status"] == "PASSED")
        n_skip = len(group) - n_fail - n_pass
        summary = f"{len(group)} tests, {n_pass} passed, {n_fail} failed"
        if n_skip:
            summary += f", {n_skip} skipped"
        rows.append(f"""
        <tr class="divider{' has-fail' if n_fail else ''}">
            <td colspan="7"><strong>{e(side_label)}</strong><span>{e(summary)}</span></td>
        </tr>""")
        rows.extend(_html_row(r, e, change_of.get(r.get('node_id'), '')) for r in group)

    notices = []
    timeouts = sum(1 for r in results if r.get("timed_out"))
    retried = sum(1 for r in results if r.get("retried") and r["Status"] == "PASSED")
    if timeouts or retried or RUN_WARNINGS:
        parts = list(RUN_WARNINGS)
        if timeouts:
            parts.append(f"{timeouts} of the {total_failed} failures are timeouts: the site was slow or not answering. "
                         "They are not confirmed bugs. Run the tests again to check.")
        if retried:
            parts.append(f"{retried} test(s) passed only on a second try after a timeout, so the site was slow while testing.")
        notices.append("<details class=\"notice\" open><summary>Reliability warning</summary><ul>"
                       + "".join(f"<li>{e(p)}</li>" for p in parts) + "</ul></details>")
    if COVERAGE_NOTES:
        items = "".join(f"<li>{e(n)}</li>" for n in COVERAGE_NOTES)
        notices.append(f"<details class=\"notice\"><summary>Not covered by these tests ({len(COVERAGE_NOTES)})</summary>"
                       f"<p>The scan saw these but the tests cannot check them. A passing run does not cover them.</p><ul>{items}</ul></details>")

    page = HTML_TEMPLATE
    for key, value in {
        "__NOTICES__": "".join(notices),
        "__CHANGES__": _changes_html(changes, e),
        "__CHANGED_BUTTON__": (f"""<button onclick='setStatus("CHANGED", this)'>Changed ({len(change_of)})</button>""" if change_of else ""),
        "__TARGET__": e(TARGET_DISPLAY),
        "__TIMESTAMP__": e(run_timestamp),
        "__TOTAL__": str(total_tests),
        "__PASSED__": str(total_passed),
        "__FAILED__": str(total_failed),
        "__SKIPPED__": str(total_skipped),
        "__PASS_PCT__": str(pass_pct),
        "__DURATION__": str(round(total_duration, 1)),
        "__ROWS__": "".join(rows),
    }.items():
        page = page.replace(key, value)

    with open(HTML_REPORT_FILE, "w", encoding="utf-8") as f_html:
        f_html.write(page)


def _changes_html(changes, e) -> str:
    """The 'Since the last run' box: counts, then the tests that started failing and the ones that got fixed."""
    if changes is None:
        return '<div class="changes"><b>First run for this suite.</b> Run it again later to see what changed.</div>'

    def names(nodes):
        return "".join(f"<li>{e(changes['labels'].get(n, n))}</li>" for n in nodes[:8]) + (
            f"<li>... and {len(nodes) - 8} more</li>" if len(nodes) > 8 else "")

    counts = (f'<span class="fail">{len(changes["newly_failing"])} newly failing</span> &middot; '
              f'<span class="pass">{len(changes["fixed"])} fixed</span> &middot; {len(changes["still_failing"])} still failing &middot; '
              f'{len(changes["new_tests"])} new tests &middot; {changes["not_run"]} not run this time')
    body = ""
    if changes["newly_failing"]:
        body += f'<p class="fail">Started failing since the last run:</p><ul>{names(changes["newly_failing"])}</ul>'
    if changes["fixed"]:
        body += f'<p class="pass">Fixed since the last run:</p><ul>{names(changes["fixed"])}</ul>'
    return f'<div class="changes"><b>Since the last run</b> ({e(changes["previous_time"])}): {counts}{body}</div>'


def _html_row(r: dict, e, change: str = "") -> str:
    """One test: a short row, plus a hidden row with the rest of the details (click the row to show it)."""
    status_cls = {"PASSED": "pass", "SKIPPED": "skip"}.get(r["Status"], "fail")
    steps = "<br>".join(e(s) for s in r["Test Steps"].split("\n"))
    details = (
        ("Preconditions", e(r["Preconditions"])),
        ("Steps", steps),
        ("Test data", e(r["Test Data"])),
        ("Expected result", e(r["Expected Result"])),
        ("Severity", e(r["Severity"])),
    )
    detail_html = "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in details)
    notes = e(r["Defects / Notes"])
    evidence = evidence_for(r["Test Case ID"]) if r["Status"] == "FAILED" else {}
    if evidence.get("screenshot"):
        shot = e(evidence["screenshot"], quote=True)
        trace_cmd = e(f"playwright show-trace reports/{evidence['trace']}") if evidence.get("trace") else ""
        detail_html += (f'<dt>Evidence</dt><dd class="evidence"><a href="{shot}" target="_blank"><img src="{shot}" alt="Screenshot at the moment of failure" loading="lazy"></a>'
                        + (f"<br>Page: {e(evidence['page'])}" if evidence.get("page") else "")
                        + (f"<br>Trace (step-by-step replay): run <code>{trace_cmd}</code> in the suite folder" if trace_cmd else "") + "</dd>")
        notes += f' <a href="{shot}" target="_blank" onclick="event.stopPropagation()">screenshot</a>'
    change_tag = f'<br><small class="chg {"pass" if change == "fixed" else "fail" if change == "new failure" else ""}">{e(change)}</small>' if change else ""
    return f"""
        <tr class="t" data-status="{e(r['Status'])}" data-change="{e(change)}" onclick="toggleRow(this)">
            <td class="id">{e(r['Test Case ID'])}</td>
            <td>{e(r['Module / Feature'])}</td>
            <td>{e(r['Test Scenario / Objective'])}</td>
            <td class="status {status_cls}">{e(r['Status'].title())}{change_tag}</td>
            <td>{e(r['Priority'])}</td>
            <td>{e(r['Actual Result'])}</td>
            <td>{notes}</td>
        </tr>
        <tr class="d"><td colspan="7"><dl>{detail_html}</dl></td></tr>"""


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nes-Dev QA - Test Report</title>
<style>
    :root { color-scheme: light dark; --bg: #ffffff; --text: #1f2933; --muted: #6b7280; --line: #e5e7eb; --soft: #f3f4f6;
            --pass: #15803d; --fail: #b91c1c; --skip: #b45309; }
    @media (prefers-color-scheme: dark) {
        :root { --bg: #111827; --text: #e5e7eb; --muted: #9ca3af; --line: #374151; --soft: #1f2937;
                --pass: #4ade80; --fail: #f87171; --skip: #fbbf24; }
    }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 24px; background: var(--bg); color: var(--text);
           font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
    main { max-width: 1200px; margin: 0 auto; }
    h1 { font-size: 22px; margin: 0; }
    .brand { color: var(--muted); font-size: 13px; }
    .meta { color: var(--muted); margin: 4px 0 20px; }
    .summary { display: flex; flex-wrap: wrap; gap: 8px 32px; padding: 12px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
    .summary div { min-width: 70px; }
    .summary b { display: block; font-size: 20px; }
    .summary span { color: var(--muted); font-size: 12px; }
    .pass { color: var(--pass); } .fail { color: var(--fail); } .skip { color: var(--skip); }
    .changes { margin-top: 12px; padding: 10px 14px; background: var(--soft); border-radius: 4px; }
    .changes p { margin: 8px 0 2px; font-weight: 600; }
    .changes ul { margin: 0 0 0 18px; padding: 0; }
    small.chg { font-weight: 600; }
    .notice { border: 1px solid var(--line); border-left: 3px solid var(--skip); padding: 8px 12px; margin-top: 12px; }
    .notice summary { cursor: pointer; font-weight: 600; }
    .notice p { color: var(--muted); margin: 8px 0 0; }
    .notice ul { margin: 8px 0 0 18px; padding: 0; }
    .tools { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; margin: 20px 0 10px; }
    .tools button { background: none; border: 0; border-bottom: 2px solid transparent; padding: 4px 2px; color: var(--muted); cursor: pointer; font: inherit; }
    .tools button.active { color: var(--text); border-bottom-color: var(--text); font-weight: 600; }
    .tools input { margin-left: auto; padding: 6px 8px; border: 1px solid var(--line); border-radius: 4px; background: var(--bg); color: var(--text); width: 240px; max-width: 100%; font: inherit; }
    .tools a { color: var(--muted); }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; }
    th { text-align: left; font-size: 12px; font-weight: 600; color: var(--muted); padding: 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
    td { padding: 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
    tr.t { cursor: pointer; }
    tr.t:hover td { background: var(--soft); }
    td.id { white-space: nowrap; color: var(--muted); }
    td.status { font-weight: 600; white-space: nowrap; }
    tr.divider td { background: var(--soft); padding: 10px 8px; }
    tr.divider span { color: var(--muted); margin-left: 12px; }
    tr.divider.has-fail span { color: var(--fail); }
    tr.d { display: none; }
    tr.d.open { display: table-row; }
    tr.d td { background: var(--soft); }
    dl { margin: 0; display: grid; grid-template-columns: 140px 1fr; gap: 4px 12px; }
    dt { color: var(--muted); }
    dd { margin: 0; }
    .evidence img { max-width: 420px; width: 100%; border: 1px solid var(--line); margin-bottom: 6px; }
    code { background: var(--bg); padding: 1px 5px; border: 1px solid var(--line); border-radius: 3px; }
    .hint { color: var(--muted); font-size: 12px; margin-top: 8px; }
</style>
</head>
<body>
<main>
    <div class="brand">Nes-Dev QA</div>
    <h1>Test Report</h1>
    <div class="meta">__TARGET__ &middot; __TIMESTAMP__</div>

    <div class="summary">
        <div><b>__TOTAL__</b><span>Total</span></div>
        <div><b class="pass">__PASSED__</b><span>Passed</span></div>
        <div><b class="fail">__FAILED__</b><span>Failed</span></div>
        <div><b class="skip">__SKIPPED__</b><span>Skipped</span></div>
        <div><b>__PASS_PCT__%</b><span>Pass rate</span></div>
        <div><b>__DURATION__s</b><span>Duration</span></div>
    </div>

    __CHANGES__

    __NOTICES__

    <div class="tools">
        <button class="active" onclick="setStatus('ALL', this)">All</button>
        <button onclick="setStatus('PASSED', this)">Passed</button>
        <button onclick="setStatus('FAILED', this)">Failed</button>
        <button onclick="setStatus('SKIPPED', this)">Skipped</button>
        __CHANGED_BUTTON__
        <input type="text" id="search" placeholder="Search tests" oninput="applyFilters()">
        <a href="latest_test_run.csv" download>Download CSV</a>
        <a href="test_runs_comparison_matrix.csv" download>Run comparison</a>
    </div>

    <div class="table-wrap">
        <table id="tests">
            <thead>
                <tr><th>ID</th><th>Feature</th><th>Scenario</th><th>Status</th><th>Priority</th><th>Result</th><th>Notes</th></tr>
            </thead>
            <tbody>
                __ROWS__
            </tbody>
        </table>
    </div>
    <p class="hint">Click a test to see its steps, test data and expected result.</p>
</main>

<script>
    let status = 'ALL';

    function toggleRow(row) { row.nextElementSibling.classList.toggle('open'); }

    function setStatus(value, button) {
        status = value;
        document.querySelectorAll('.tools button').forEach(b => b.classList.remove('active'));
        button.classList.add('active');
        applyFilters();
    }

    function applyFilters() {
        const query = document.getElementById('search').value.toLowerCase();
        let divider = null, shown = 0;
        const closeDivider = () => { if (divider) divider.style.display = shown ? '' : 'none'; };
        document.querySelectorAll('#tests tbody tr').forEach(row => {
            if (row.classList.contains('divider')) { closeDivider(); divider = row; shown = 0; return; }
            if (!row.classList.contains('t')) return;
            const detail = row.nextElementSibling;
            const visible = (status === 'ALL' || (status === 'CHANGED' ? !!row.dataset.change : row.dataset.status === status)) &&
                            (!query || (row.innerText + ' ' + detail.textContent).toLowerCase().includes(query));
            row.style.display = visible ? '' : 'none';
            detail.style.display = visible ? '' : 'none';
            if (visible) shown++;
        });
        closeDivider();
    }
</script>
</body>
</html>
"""
