"""
The generator turns a scan into test code. These tests give it a hand-made scan (no browser needed) and check
the code it writes: that it compiles, and that it makes the safe and honest choices we rely on.
"""

import py_compile
from pathlib import Path

import pytest

from qa_generator.generator import generate_dynamic_test_suite
from qa_generator.scanner import empty_scan

SITE = "http://site.test"


def form(index, *, unsafe=False, required=2, label="Send", has_password=False):
    return {"index": index, "page_url": f"{SITE}/", "action": f"/form{index}", "method": "POST", "input_count": 3,
            "fillable_count": 3, "required_count": required, "field_kinds": ["text", "email"], "names": [f"f{index}"],
            "has_submit": True, "unsafe_submit": unsafe, "submit_label": label, "has_password": has_password}


def make_scan(**overrides):
    scan = empty_scan(SITE)
    scan["homepage"].update({"title": "Test Shop", "heading": "Shop", "status": 200, "nav_links": [
        {"name": "About", "full_url": f"{SITE}/about", "route": "/about", "status": 200,
         "content_type": "text/html", "final_url": f"{SITE}/about"},
        # a link that sent the guest to the login page: the status seen (200) was the login page's, not this page's
        {"name": "Account", "full_url": f"{SITE}/account", "route": "/account", "status": 200,
         "content_type": "text/html", "final_url": f"{SITE}/login"},
    ]})
    comp = scan["components"]
    comp["forms"] = [form(0), form(1, unsafe=True, label="Delete my account")]
    comp["modal"] = {"page_url": f"{SITE}/", "trigger": {"selector": "#open", "text": None},
                     "dialog_selector": "[role='dialog']:visible", "close_selector": "button", "close_method": "button",
                     "form": form(0, required=1, label="Join")}
    comp["filters"] = [{"type": "select", "text": "select_category", "page_url": f"{SITE}/", "selector": "select[name='category']",
                        "sample_value": "a", "values": ["a", "b", "c"]}]
    comp["search"] = {"selector": "#q", "page_url": f"{SITE}/", "results_selector": None, "sample_query": "premium",
                      "queries": ["premium", "court"], "negative_query": "zzz"}
    long_label = "What sports can I play at Ace Padel and Tennis Center?"   # longer than the 40 characters used in test names
    comp["interactions"] = {
        "tabs": [{"page_url": f"{SITE}/", "tablist_index": 0, "count": 2, "has_controls": True}],
        "toggles": [{"page_url": f"{SITE}/", "kind": "button", "selector": "button", "text": long_label, "label": long_label[:40],
                     "region": "accordion", "starts_open": False}],
        "pagination": [{"page_url": f"{SITE}/", "container_selector": ".pager", "container_index": 0, "next_selector": "a.next"}],
        "carousels": [{"page_url": f"{SITE}/", "container_selector": ".carousel", "container_index": 0, "next_selector": "button"}],
        "uploads": [{"page_url": f"{SITE}/", "index": 0, "accept": "image/*"}],
    }
    scan["coverage_notes"] = [{"page_url": f"{SITE}/", "kind": "captcha", "text": "CAPTCHA on /: forms may refuse automated submits."}]
    scan.update(overrides)
    return scan


def accounts():
    return [{"role": "user", "name": "User", "username": "user@x.com", "password": "pw", "target_path": ""},
            {"role": "admin", "name": "Admin", "username": "admin@x.com", "password": "pw", "target_path": ""}]


def user_session(**kw):
    session = {"login_url": f"{SITE}/login", "post_login_url": f"{SITE}/cart", "welcome_text": "", "has_logout": True,
               "sublinks": [{"name": "Account", "url": f"{SITE}/account", "path": "/account"},
                            {"name": "App", "url": f"{SITE}/app", "path": "/app"}],
               "forms": [form(0, label="Save profile"), form(1, unsafe=True, label="Delete account")],
               "guest_blocked_urls": [f"{SITE}/account"],      # the landing page (/cart) is public
               "http_ok_urls": [f"{SITE}/account"]}            # /app only works inside the browser (a single-page app)
    session.update(kw)
    return session


def admin_session(**kw):
    session = {"login_url": f"{SITE}/login", "dashboard_url": f"{SITE}/admin", "has_heading": True,
               "admin_links": [f"{SITE}/admin/products"],
               "subpages": [{"name": "Products", "url": f"{SITE}/admin/products", "path": "/admin/products", "status": 200,
                             "has_heading": True, "has_table": False}],
               "forms": [form(0, label="Add product")],
               "guest_blocked_urls": [f"{SITE}/admin", f"{SITE}/admin/products"],
               "http_ok_urls": [f"{SITE}/admin", f"{SITE}/admin/products"]}
    session.update(kw)
    return session


def generate(tmp_path, scan=None, *, submit=False, writes=False, with_accounts=True):
    out = tmp_path / "suite"
    scan = scan or make_scan(user_session=user_session(), admin_session=admin_session())
    generate_dynamic_test_suite(SITE, out, scan, accounts() if with_accounts else [], "/login",
                                include_write_tests=writes, modes={"e2e", "api"}, submit_forms=submit)
    return out


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def all_tests(out: Path) -> str:
    return "\n".join(read(p) for p in sorted((out / "tests").rglob("*.py")))


# ---- the output is valid, complete code ------------------------------------------------------------------------
def test_every_generated_file_compiles(tmp_path):
    out = generate(tmp_path, submit=True, writes=True)
    files = list(out.rglob("*.py"))
    assert len(files) > 10
    for f in files:
        py_compile.compile(str(f), doraise=True)


def test_suite_comes_with_its_helpers_and_config(tmp_path):
    out = generate(tmp_path)
    for name in ("conftest.py", "csv_reporter.py", "qa_login.py", "qa_forms.py", "pytest.ini", "suite_config.json", "README.md", ".gitignore"):
        assert (out / name).exists(), name


def test_test_accounts_are_kept_out_of_version_control(tmp_path):
    out = generate(tmp_path)
    assert "QA_USER_PASSWORD" in read(out / ".env")
    assert ".env" in read(out / ".gitignore").splitlines()


def test_no_security_tests_are_generated(tmp_path):
    out = generate(tmp_path)
    assert not (out / "tests" / "security").exists()


# ---- nothing is sent unless asked ------------------------------------------------------------------------------------
def test_forms_are_filled_but_not_submitted_by_default(tmp_path):
    code = all_tests(generate(tmp_path))
    assert "def test_form_inputs_group_1" in code
    assert "def test_form_submit" not in code and "def test_form_empty_submit" not in code
    assert "pytest.mark.write" not in code                    # no test that sends data


def test_submit_tests_appear_only_with_the_flag(tmp_path):
    code = all_tests(generate(tmp_path, submit=True))
    assert "def test_form_submit_group_1" in code and "def test_form_empty_submit_group_1" in code
    assert "def test_form_submit_modal" in code


def test_form_that_looks_destructive_is_never_submitted(tmp_path):
    code = all_tests(generate(tmp_path, submit=True))
    assert "def test_form_inputs_group_2" in code            # still filled and checked
    assert "def test_form_submit_group_2" not in code        # but never submitted
    assert "not generated" in code
    assert "def test_user_form_inputs_2" in code and "def test_user_form_submit_2" not in code


def test_write_method_probes_need_their_own_flag(tmp_path):
    without = generate(tmp_path / "a")
    with_flag = generate(tmp_path / "b", writes=True)
    assert not (without / "tests" / "api" / "test_api_crud_lifecycle.py").exists()
    assert "def test_http_post" in all_tests(with_flag)


# ---- tests are honest about what they know -------------------------------------------------------------------------------
def test_guest_guard_uses_a_page_guests_are_really_refused_from(tmp_path):
    """Login lands on /cart, which anyone can open. The guard test must use /account instead."""
    out = generate(tmp_path)
    for path in ((out / "tests/e2e/test_access_control.py"), (out / "tests/api/test_api_access_control.py")):
        text = read(path)
        assert f"'{SITE}/account'" in text
        assert f"target = '{SITE}/cart'" not in text


def test_no_guard_test_is_made_when_nothing_is_protected(tmp_path):
    scan = make_scan(user_session=user_session(guest_blocked_urls=[]))
    code = all_tests(generate(tmp_path, scan))
    assert "def test_unauthenticated_user_access_blocked" not in code
    assert "def test_api_unauthenticated_user_route_guard" not in code


def test_pages_that_only_work_in_the_browser_get_no_http_tests(tmp_path):
    """Plain HTTP gets a 404 for /app (a single-page app). An HTTP test would fail, or pass for the wrong reason."""
    out = generate(tmp_path)
    api = read(out / "tests/api/test_api_customer.py")
    assert f"{SITE}/account" in api and f"{SITE}/app" not in api
    assert "test_api_customer_landing_endpoint" not in api    # the landing page (/cart) was not fetchable either


def test_links_that_redirect_to_login_are_not_public_pages(tmp_path):
    out = generate(tmp_path)
    nav = read(out / "tests/e2e/test_navigation.py")
    assert f"{SITE}/about" in nav and f"{SITE}/account" not in nav
    api = read(out / "tests/api/test_api_public_routes.py")
    assert "def test_api_route_requires_login" in api and f"{SITE}/account" in api


def test_toggle_tests_match_the_whole_label_ignoring_case(tmp_path):
    code = read(generate(tmp_path) / "tests/e2e/test_interactions.py")
    assert "text_re('What sports can I play at Ace Padel and Tennis Center?')" in code   # not cut at 40 characters
    assert "from qa_forms import" in code


def test_every_dropdown_option_and_search_word_gets_its_own_test(tmp_path):
    code = read(generate(tmp_path) / "tests/e2e/test_components.py")
    assert "['a', 'b', 'c']" in code or '["a", "b", "c"]' in code
    assert "premium" in code and "court" in code


def test_logged_in_form_tests_run_as_the_right_account(tmp_path):
    out = generate(tmp_path, submit=True)
    assert "def test_user_form_inputs_1(login_user: Page)" in read(out / "tests/e2e/test_user_session.py")
    assert "def test_admin_form_inputs_1(login_admin: Page)" in read(out / "tests/e2e/test_admin_portal.py")


def test_password_forms_in_logged_in_areas_are_not_submitted(tmp_path):
    """A 'change password' form would lock out the test account."""
    scan = make_scan(user_session=user_session(forms=[form(0, unsafe=True, has_password=True, label="Change password")]),
                     admin_session=admin_session())
    code = all_tests(generate(tmp_path, scan, submit=True))
    assert "def test_user_form_inputs_1" in code and "def test_user_form_submit_1" not in code


def test_what_was_not_covered_is_written_into_the_suite_readme(tmp_path):
    out = generate(tmp_path)
    assert "Not covered by these tests" in read(out / "README.md")
    assert "CAPTCHA on /" in read(out / "README.md")
    assert "CAPTCHA on /" in read(out / "suite_config.json")


def test_public_only_scan_makes_no_login_tests(tmp_path):
    out = generate(tmp_path, make_scan(), with_accounts=False)
    names = {p.name for p in (out / "tests").rglob("test_*.py")}
    assert "test_user_session.py" not in names and "test_admin_portal.py" not in names


# ---- accessibility ---------------------------------------------------------------------------------------------------------------
def a11y_scan(violations_home=None):
    scan = make_scan()
    label = {"id": "label", "impact": "critical", "help": "Form elements must have labels", "nodes": 2}
    scan["accessibility"] = [{"page_url": f"{SITE}/", "violations": violations_home if violations_home is not None else [label]},
                             {"page_url": f"{SITE}/about", "violations": []}]
    return scan


def test_each_scanned_page_gets_an_accessibility_test_that_remembers_existing_problems(tmp_path):
    out = generate(tmp_path, a11y_scan(), with_accounts=False)
    code = read(out / "tests/e2e/test_accessibility.py")
    assert "def test_accessibility_serious_issues" in code
    assert "('home', 'http://site.test/', ['label'])" in code.replace('"', "'")      # the page and the problems it already had
    assert "('about', 'http://site.test/about', [])" in code.replace('"', "'")
    assert "from qa_a11y import describe, serious_violations" in code
    # a new problem fails; an existing one is only a warning
    assert "assert not new" in code and "pytest.skip(\"WARNING" in code


def test_axe_is_copied_only_into_suites_that_use_it(tmp_path):
    with_a11y = generate(tmp_path / "a", a11y_scan(), with_accounts=False)
    without = generate(tmp_path / "b", make_scan(), with_accounts=False)
    assert (with_a11y / "axe.min.js").exists() and (with_a11y / "qa_a11y.py").exists()
    assert not (without / "axe.min.js").exists() and not (without / "tests/e2e/test_accessibility.py").exists()


def test_accessibility_file_compiles(tmp_path):
    out = generate(tmp_path, a11y_scan(), with_accounts=False)
    py_compile.compile(str(out / "tests/e2e/test_accessibility.py"), doraise=True)


# ---- text boxes outside forms -------------------------------------------------------------------------------------------------------------
def scan_with_boxes():
    scan = make_scan()
    scan["components"]["interactions"]["inputs"] = [
        {"page_url": f"{SITE}/", "selector": "input#todo", "label": "What needs to be done?", "tried_enter": True, "effect": "text_appears"},
        {"page_url": f"{SITE}/", "selector": "input#nick", "label": "Your nickname", "tried_enter": True, "effect": None},
        {"page_url": f"{SITE}/", "selector": "input#go", "label": "Jump to", "tried_enter": True, "effect": "url_changed"},
    ]
    return scan


def test_every_typing_box_gets_a_type_and_check_test(tmp_path):
    code = read(generate(tmp_path, scan_with_boxes(), with_accounts=False) / "tests/e2e/test_interactions.py")
    for name in ("what_needs_to_be_done", "your_nickname", "jump_to"):
        assert f"def test_type_into_{name}(page: Page)" in code
    assert "box.fill('QA test entry')" in code.replace('"', "'") and "to_have_value" in code


def test_enter_is_only_pressed_with_permission_and_when_the_scan_saw_a_result(tmp_path):
    allowed = read(generate(tmp_path / "a", scan_with_boxes(), submit=True, with_accounts=False) / "tests/e2e/test_interactions.py")
    assert "def test_type_into_what_needs_to_be_done_and_press_enter" in allowed
    assert "get_by_text" in allowed and "pytest.mark.write" in allowed          # the text must show up, and the test is marked as sending data
    assert "def test_type_into_jump_to_and_press_enter" in allowed and "start_url" in allowed   # a page-change result
    assert "your_nickname_and_press_enter" not in allowed                        # Enter did nothing visible: nothing to assert

    refused = read(generate(tmp_path / "b", scan_with_boxes(), submit=False, with_accounts=False) / "tests/e2e/test_interactions.py")
    assert "press_enter" not in refused and "box.press" not in refused           # no permission: the box is only typed into
    assert "def test_type_into_what_needs_to_be_done(page: Page)" in refused


def test_typing_box_tests_compile(tmp_path):
    out = generate(tmp_path, scan_with_boxes(), submit=True, with_accounts=False)
    py_compile.compile(str(out / "tests/e2e/test_interactions.py"), doraise=True)
