"""The report logic: plain-language errors, which side a test belongs to, labels for slow sites, HTML safety."""

import html
import types

import pytest

from qa_generator.templates import csv_reporter as R


@pytest.mark.parametrize("raw, expected", [
    ("AssertionError: Homepage returned 500 assert 500 < 400 + where 500 = <Response>.status", "Homepage returned 500."),
    ("playwright._impl._errors.TimeoutError: Page.goto: Timeout 30000ms exceeded. Call log: navigating",
     "Timed out after 30s waiting on Page.goto."),
    ("Failed: Password field still visible after login", "Password field still visible after login."),
    ("assert 404 < 400", "assert 404 < 400."),
    ("Locator expected to be visible Actual value: None Error: element(s) not found Call log: - waiting for locator('x')",
     "The element was not found on the page (the test expected it to be visible)."),
    ("Locator expected to be visible Actual value: hidden", "The element is on the page but it is not visible."),
    ("Locator expected to have text 'Hi' Actual value: Bye", "The element was not as expected: it should have text 'Hi'."),
    ("Page URL expected to be 're.compile(/account)' Actual value: http://s.test/login Call log: - waiting",
     "The page ended on http://s.test/login, not on the expected address."),
    ("", "Test failed with no message."),
])
def test_simplify_error_gives_one_direct_sentence(raw, expected):
    assert R._simplify_error(raw) == expected


def test_simplify_error_is_short():
    assert len(R._simplify_error("AssertionError: " + "x" * 1000)) <= 205


@pytest.mark.parametrize("prefix, name, side", [
    ("ADM", "admin_subpage", "admin"),
    ("API-ADM", "api_admin_page", "admin"),
    ("USR", "user_view", "user"),
    ("SEC", "user_privilege_escalation_blocked", "user"),       # a customer trying to reach admin: runs as the user
    ("SEC", "unauthenticated_admin_access_blocked", "admin"),    # a guest at the admin area: guards the admin side
    ("SEC", "unauthenticated_user_access_blocked", "user"),
    ("NAV", "homepage_title_and_hero", "public"),
    ("CMP", "search_input_filtering", "public"),
])
def test_side_for(prefix, name, side):
    assert R._side_for(prefix, name) == side


@pytest.mark.parametrize("name, expected", [
    ("user_form_inputs_1", True),
    ("admin_form_empty_submit_2", True),
    ("user_view", False),
    ("information_page", False),   # 'form' inside a word must not count
])
def test_is_form_test_matches_whole_word_only(name, expected):
    assert R._is_form_test(name) is expected


@pytest.mark.parametrize("message, expected", [
    ("Page.goto: Timeout 30000ms exceeded.", True),
    ("Homepage returned 500", False),
    ("Locator expected to be visible", False),   # a failed check is not a timeout
])
def test_is_timeout_message(message, expected):
    assert R._is_timeout_message(message) is expected


@pytest.mark.parametrize("node, prefix", [
    ("tests/e2e/test_navigation.py::test_a", "NAV"),
    ("tests/e2e/test_forms.py::test_form_inputs_group_1", "FRM"),
    ("tests/e2e/test_interactions.py::test_tabs_1", "INT"),
    ("tests/api/test_api_admin.py::test_api_admin_page", "API-ADM"),
    ("tests/e2e/test_unknown.py::test_x", "GEN"),
])
def test_prefix_for(node, prefix):
    assert R._prefix_for(node) == prefix


class FakeItem:
    """Just enough of a pytest item for the report to describe it."""

    def __init__(self, nodeid, name, doc="Verify the page loads."):
        self.nodeid, self.name = nodeid, name
        self.function = types.SimpleNamespace(__doc__=doc)


def describe(status, message="", retried=False, node="tests/e2e/test_navigation.py::test_public_route_loads"):
    item = FakeItem(node, node.split("::")[1])
    return R._derive_test_case_metadata(item, 1.25, status, message, retried)


def test_passed_test_has_no_defects():
    row = describe("PASSED")
    assert row["Status"] == "PASSED" and row["Defects / Notes"] == "None." and row["Actual Result"] == "Passed in 1.25s."


def test_failed_test_names_what_went_wrong_and_which_side():
    row = describe("FAILED", "AssertionError: Homepage returned 500 assert 500 < 400",
                   node="tests/e2e/test_admin_portal.py::test_admin_subpage")
    assert row["Actual Result"] == "Failed: Homepage returned 500."
    assert row["Defects / Notes"] == "Failed on the Admin Account side."
    assert row["side"] == "admin" and not row["timed_out"]


def test_timeout_is_labelled_as_not_a_confirmed_bug():
    row = describe("FAILED", "playwright._impl._errors.TimeoutError: Page.goto: Timeout 30000ms exceeded.")
    assert row["timed_out"] is True
    assert "not a confirmed bug" in row["Defects / Notes"]


def test_test_that_passed_on_retry_is_flagged():
    row = describe("PASSED", retried=True)
    assert row["retried"] is True and "second try" in row["Defects / Notes"]


def test_priority_is_critical_for_access_control():
    assert describe("PASSED", node="tests/e2e/test_access_control.py::test_user_privilege_escalation_blocked")["Priority"] == "Critical"


def test_html_row_escapes_text_from_the_site():
    """Error text comes from the tested site, so it must never become live HTML in the report."""
    row = describe("FAILED", "AssertionError: <script>alert(1)</script> broke the page")
    page_row = R._html_row(row, html.escape)
    assert "<script>" not in page_row and "&lt;script&gt;" in page_row


def test_csv_has_the_twelve_qa_columns():
    assert len(R.COLUMNS) == 12 and R.COLUMNS[0] == "Test Case ID" and R.COLUMNS[-1] == "Defects / Notes"


# ---- evidence for failed tests --------------------------------------------------------------------------------------
def make_evidence(folder, trace=True):
    folder.mkdir(parents=True)
    (folder / "failure.png").write_bytes(b"\x89PNG fake")
    (folder / "page.txt").write_text("https://site.test/cart", encoding="utf-8")
    if trace:
        (folder / "trace.zip").write_bytes(b"PK fake")


def test_evidence_for_lists_what_was_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "EVIDENCE_DIR", str(tmp_path))
    make_evidence(tmp_path / "TC-NAV-001")
    found = R.evidence_for("TC-NAV-001")
    assert found == {"screenshot": "evidence/TC-NAV-001/failure.png", "trace": "evidence/TC-NAV-001/trace.zip",
                     "page": "https://site.test/cart"}
    assert R.evidence_for("TC-NAV-999") == {}      # a test with no evidence


def test_failed_row_shows_the_screenshot_and_how_to_open_the_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "EVIDENCE_DIR", str(tmp_path))
    row = describe("FAILED", "AssertionError: Cart returned 500")
    row["Test Case ID"] = "TC-NAV-001"
    make_evidence(tmp_path / "TC-NAV-001")
    page_row = R._html_row(row, html.escape)
    assert 'src="evidence/TC-NAV-001/failure.png"' in page_row
    assert "playwright show-trace reports/evidence/TC-NAV-001/trace.zip" in page_row
    assert "https://site.test/cart" in page_row


def test_row_without_a_trace_still_shows_the_screenshot(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "EVIDENCE_DIR", str(tmp_path))
    row = describe("FAILED", "AssertionError: Cart returned 500")
    row["Test Case ID"] = "TC-NAV-002"
    make_evidence(tmp_path / "TC-NAV-002", trace=False)
    page_row = R._html_row(row, html.escape)
    assert "failure.png" in page_row and "show-trace" not in page_row


def test_passed_row_never_shows_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "EVIDENCE_DIR", str(tmp_path))
    row = describe("PASSED")
    row["Test Case ID"] = "TC-NAV-003"
    make_evidence(tmp_path / "TC-NAV-003")          # even if a stale folder is lying around
    assert "failure.png" not in R._html_row(row, html.escape)


def test_evidence_folder_uses_the_report_id(monkeypatch):
    monkeypatch.setitem(R._TC_IDS, "tests/e2e/test_x.py::test_a", "TC-NAV-007")
    assert R.evidence_id("tests/e2e/test_x.py::test_a") == "TC-NAV-007"
    assert "/" not in R.evidence_id("tests/e2e/unnumbered.py::test_b[chromium]")   # a safe folder name when there is no ID


# ---- what changed since the last run -------------------------------------------------------------------------------------
def run(timestamp, **statuses):
    return {"format": 2, "run_id": "Run_" + timestamp, "timestamp": timestamp,
            "results": {node: f"{status} (1.0s)" for node, status in statuses.items()},
            "labels": {node: f"TC-{node}  Scenario {node}" for node in statuses}}


def test_no_comparison_on_the_first_run():
    assert R.compare_runs([]) is None
    assert R.compare_runs([run("t1", a="PASSED")]) is None


def test_compare_runs_sorts_every_test_into_its_group():
    before = run("t1", a="PASSED", b="FAILED", c="FAILED", d="PASSED", gone="PASSED", flaky="SKIPPED")
    after = run("t2", a="FAILED", b="PASSED", c="FAILED", d="PASSED", fresh="FAILED", flaky="FAILED")
    changes = R.compare_runs([before, after])
    assert changes["newly_failing"] == ["a", "flaky"]       # passed or skipped before, failing now
    assert changes["fixed"] == ["b"]
    assert changes["still_failing"] == ["c"]
    assert changes["new_tests"] == ["fresh"]                 # not in the earlier run: not called a regression
    assert changes["not_run"] == 1                           # 'gone' was not run this time
    assert changes["previous_time"] == "t1"


def test_compare_runs_only_looks_at_the_last_two_runs():
    changes = R.compare_runs([run("t1", a="FAILED"), run("t2", a="PASSED"), run("t3", a="PASSED")])
    assert changes["fixed"] == [] and changes["newly_failing"] == []


def test_changes_box_names_the_tests_that_started_failing_and_the_fixed_ones():
    changes = R.compare_runs([run("2026-10-01 10:00", a="PASSED", b="FAILED"), run("2026-10-02 10:00", a="FAILED", b="PASSED")])
    box = R._changes_html(changes, html.escape)
    assert "1 newly failing" in box and "1 fixed" in box and "2026-10-01 10:00" in box
    assert "Started failing since the last run" in box and "TC-a  Scenario a" in box and "TC-b  Scenario b" in box


def test_changes_box_on_a_first_run_says_so():
    assert "First run" in R._changes_html(None, html.escape)


def test_changed_rows_are_tagged_for_the_changed_filter():
    row = describe("FAILED", "AssertionError: broke")
    tagged = R._html_row(row, html.escape, "new failure")
    assert 'data-change="new failure"' in tagged and "new failure" in tagged
    assert 'data-change=""' in R._html_row(row, html.escape)


def test_accessibility_tests_have_their_own_report_group():
    node = "tests/e2e/test_accessibility.py::test_accessibility_serious_issues"
    assert R._prefix_for(node) == "A11Y"
    row = describe("PASSED", node=node)
    assert row["Module / Feature"] == "Accessibility - Page" and "axe-core" in row["Test Steps"]
    assert row["Priority"] == "High"


def test_typing_box_tests_have_their_own_wording():
    typed = describe("PASSED", node="tests/e2e/test_interactions.py::test_type_into_what_needs_to_be_done")
    entered = describe("PASSED", node="tests/e2e/test_interactions.py::test_type_into_what_needs_to_be_done_and_press_enter")
    assert typed["Module / Feature"] == entered["Module / Feature"] == "UI Interactions - Typing in a box"
    assert "keeps the text" in typed["Test Steps"] and "press Enter" in entered["Test Steps"]
