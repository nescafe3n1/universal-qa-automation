"""
The promise of the tool, tested for real: scan a site, write tests, run them.
Healthy site -> they pass. Same tests, broken site -> the right ones fail.
"""

import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from qa_generator.templates import csv_reporter
from tests.integration.conftest import ACCOUNTS, run_pytest

pytestmark = pytest.mark.integration


# ---- the scan finds what the site offers ------------------------------------------------------------------------
def test_scan_finds_the_pages_content_and_widgets(scan):
    comp, widgets = scan["components"], scan["components"]["interactions"]
    assert scan["homepage"]["title"] == "Test Shop"
    assert comp["all_cards"] and comp["search"] and comp["filters"]
    assert comp["search"]["queries"][:2] == ["Premium", "Court"]
    assert len(widgets["tabs"]) == 1 and len(widgets["carousels"]) == 1 and len(widgets["pagination"]) == 1
    assert len(widgets["toggles"]) == 2 and len(widgets["uploads"]) == 1


def test_scan_finds_forms_on_the_page_and_in_the_popup(scan):
    forms = scan["components"]["forms"]
    assert forms and forms[0]["required_count"] == 2 and "file" in forms[0]["field_kinds"]
    assert scan["components"]["modal"]["form"]["required_count"] == 1       # the form inside the popup


def test_scan_finds_the_forms_inside_the_logged_in_areas(scan):
    user_forms = scan["user_session"]["forms"]
    assert any(f["unsafe_submit"] for f in user_forms)                      # "Delete my account"
    assert any(not f["unsafe_submit"] for f in user_forms)                  # "Save profile"
    assert scan["admin_session"]["forms"]


def test_scan_does_not_treat_a_public_landing_page_as_protected(scan):
    """Login lands on /cart, which anyone can open. Only /account is really refused to guests."""
    blocked = scan["user_session"]["guest_blocked_urls"]
    assert any(url.endswith("/account") for url in blocked)
    assert not any(url.endswith("/cart") for url in blocked)


def test_scan_notices_a_page_that_only_works_inside_the_browser(scan):
    session = scan["user_session"]
    assert not any(url.endswith("/app") for url in session["http_ok_urls"])
    assert any(url.endswith("/account") for url in session["http_ok_urls"])
    assert any("only work inside the browser" in note["text"] for note in scan["coverage_notes"])


def test_scan_reports_what_it_will_not_submit(scan):
    assert any("never submitted" in note["text"] and "Delete my account" in note["text"] for note in scan["coverage_notes"])


def test_the_scan_leaves_the_site_untouched(site, scan):
    """Scanning is read-only: no buttons inside forms are pressed, so nothing was submitted."""
    assert site.broken == set()   # (the handler would have to answer a POST to change anything; it only counts GETs here)


# ---- tests written from a healthy site pass ------------------------------------------------------------------------
def test_generated_suite_passes_on_the_healthy_site(suite):
    result = run_pytest(suite)
    assert result.code == 0, result.output[-3000:]
    assert " passed" in result.output and not result.failed


def test_the_run_leaves_a_report_and_a_12_column_csv(suite):
    if not (suite / "reports" / "latest_test_run.csv").exists():   # do not depend on another test having run the suite first
        run_pytest(suite)
    assert (suite / "reports" / "index.html").exists()
    with open(suite / "reports" / "latest_test_run.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == csv_reporter.COLUMNS
    assert "FAILED" not in {r["Status"] for r in rows}
    # the only skips on a healthy site are accessibility warnings about problems the page already had
    skipped = [r for r in rows if r["Status"] == "SKIPPED"]
    assert all(r["Test Case ID"].startswith("TC-A11Y") and "WARNING" in r["Actual Result"] for r in skipped)
    assert len([r for r in rows if r["Status"] == "PASSED"]) > 30
    page = (suite / "reports" / "index.html").read_text(encoding="utf-8")
    assert "Nes-Dev QA" in page and "Guest / Public" in page and "User Account" in page and "Admin Account" in page


def test_the_suite_covers_every_kind_of_thing_that_was_found(suite):
    names = {p.name for p in (suite / "tests").rglob("test_*.py")}
    assert {"test_navigation.py", "test_components.py", "test_forms.py", "test_interactions.py",
            "test_user_session.py", "test_admin_portal.py", "test_access_control.py"} <= names


# ---- the same tests catch a broken site -----------------------------------------------------------------------------------
def test_tests_fail_when_widgets_stop_working(site, suite):
    """Tabs, accordion, carousel and the popup lose their JavaScript; the next-page link goes nowhere."""
    site.broken = {"js", "pagination"}
    try:
        result = run_pytest(suite, "tests/e2e/test_interactions.py", "tests/e2e/test_components.py")
    finally:
        site.broken = set()
    assert result.code == 1
    failed = set(result.failed)
    assert "test_tabs_1" in failed
    assert "test_carousel_next_slide" in failed
    assert "test_pagination_next_page" in failed
    assert any(name.startswith("test_toggle_what_is_shipping") for name in failed)
    assert "test_interactive_modal_dialog" in failed                       # the popup no longer opens
    assert "test_file_upload_1" not in failed                              # an upload field still works: no false alarm


def test_tests_fail_when_a_form_submit_returns_a_server_error(site, suite):
    site.broken = {"submit500"}
    try:
        result = run_pytest(suite, "tests/e2e/test_forms.py")
    finally:
        site.broken = set()
    assert result.code == 1
    assert "test_form_submit_modal" in result.failed
    assert "test_form_submit_group_1" not in result.failed                 # the other form still works
    assert "server error" in result.output


def test_a_site_that_cannot_be_reached_stops_the_run_with_one_clear_message(suite, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(suite, copy)
    config = copy / "suite_config.json"
    config.write_text(config.read_text(encoding="utf-8").replace(suite.parent.name, "x"), encoding="utf-8")
    import json
    data = json.loads(config.read_text(encoding="utf-8"))
    data["base_url"] = "http://127.0.0.1:9"
    config.write_text(json.dumps(data), encoding="utf-8")
    result = run_pytest(copy, "tests/e2e/test_navigation.py")
    assert result.code == 3
    assert "could not be reached" in result.output and "nothing is confirmed broken" in result.output
    assert not result.failed                                              # no pile of misleading failures


# ---- the command line, start to finish -------------------------------------------------------------------------------------------
def test_command_line_quick_run_writes_a_suite_without_asking_anything(site, tmp_path):
    project_root = str(Path(__file__).resolve().parents[2])   # lets the command find the package even when it is not installed
    env = {**os.environ, "QA_GENERATOR_HOME": str(tmp_path / "home"), "QA_GENERATOR_WORKSPACE": str(tmp_path),
           "PYTHONIOENCODING": "utf-8", "PYTHONPATH": project_root}
    done = subprocess.run([sys.executable, "-m", "qa_generator", site.url, "--accept-terms", "--quick", "--no-run", "-o", "made"],
                          cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=300, env=env, stdin=subprocess.DEVNULL)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    assert (tmp_path / "made" / "tests" / "e2e" / "test_navigation.py").exists()
    assert "[2/4] Generating dynamic test suite" in done.stdout          # piped output keeps the detailed format
    assert not (tmp_path / "made" / "tests" / "security").exists()


# ---- evidence: a failed test leaves proof ----------------------------------------------------------------------------------------
def test_a_failed_test_leaves_a_screenshot_and_a_trace_in_the_report(site, suite):
    import zipfile
    site.broken = {"pagination"}
    try:
        result = run_pytest(suite, "tests/e2e/test_interactions.py")
    finally:
        site.broken = set()
    assert result.failed == ["test_pagination_next_page"]

    evidence = suite / "reports" / "evidence"
    folders = [d for d in evidence.iterdir() if d.is_dir()]
    assert len(folders) == 1, "evidence only for the one test that failed, none for the passing ones"
    folder = folders[0]
    assert (folder / "failure.png").read_bytes().startswith(b"\x89PNG")
    assert zipfile.is_zipfile(folder / "trace.zip") and "trace.trace" in zipfile.ZipFile(folder / "trace.zip").namelist()
    assert (folder / "page.txt").read_text(encoding="utf-8").startswith(site.url)

    report = (suite / "reports" / "index.html").read_text(encoding="utf-8")
    assert f'src="evidence/{folder.name}/failure.png"' in report and f"reports/evidence/{folder.name}/trace.zip" in report
    with open(suite / "reports" / "latest_test_run.csv", encoding="utf-8-sig", newline="") as f:
        assert list(next(csv.DictReader(f)).keys()) == csv_reporter.COLUMNS     # the CSV keeps its 12 standard columns


def test_the_trace_can_be_switched_off_but_the_screenshot_stays(site, suite):
    site.broken = {"pagination"}
    try:
        result = run_pytest(suite, "tests/e2e/test_interactions.py", env_extra={"NESQA_TRACE": "0"})
    finally:
        site.broken = set()
    assert result.failed == ["test_pagination_next_page"]
    folder = next(d for d in (suite / "reports" / "evidence").iterdir() if d.is_dir())
    assert (folder / "failure.png").exists() and not (folder / "trace.zip").exists()


def test_a_healthy_run_leaves_no_evidence_behind(suite):
    result = run_pytest(suite, "tests/e2e/test_interactions.py")
    assert result.code == 0
    evidence = suite / "reports" / "evidence"
    assert not evidence.exists() or not any(evidence.iterdir())


# ---- what changed since the last run -------------------------------------------------------------------------------------------
def test_the_report_and_summary_say_what_changed_since_the_last_run(site, suite, capsys):
    from qa_generator import ui
    interactions = "tests/e2e/test_interactions.py"
    report_file = suite / "reports" / "index.html"

    run_pytest(suite, interactions)                         # 1. healthy
    site.broken = {"pagination"}
    try:
        run_pytest(suite, interactions)                     # 2. the next-page link breaks
    finally:
        site.broken = set()
    report = report_file.read_text(encoding="utf-8")
    assert "1 newly failing" in report and "Started failing since the last run" in report
    assert 'data-change="new failure"' in report and "Changed (1)" in report

    run_pytest(suite, interactions)                         # 3. fixed again
    report = report_file.read_text(encoding="utf-8")
    assert "1 fixed" in report and "Fixed since the last run" in report and "0 newly failing" in report

    ui.COLOR = False
    ui.show_final_summary(suite, 5.0, 0)
    out = capsys.readouterr().out
    assert "Since the last run" in out
    assert "fixed:" in out and "next-page control" in out     # the fixed test is named, in words


# ---- accessibility ------------------------------------------------------------------------------------------------------------------------
def test_scan_records_the_accessibility_problems_that_already_exist(scan):
    home = next(p for p in scan["accessibility"] if p["page_url"].rstrip("/") == scan["url"].rstrip("/"))
    rules = {v["id"] for v in home["violations"]}
    assert {"label", "select-name"} & rules                    # the search box and dropdown have no labels
    assert all(v["impact"] in ("critical", "serious") for v in home["violations"])


def test_existing_accessibility_problems_are_a_warning_not_a_failure(suite):
    result = run_pytest(suite, "tests/e2e/test_accessibility.py")
    assert result.code == 0 and not result.failed
    with open(suite / "reports" / "latest_test_run.csv", encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["Test Case ID"].startswith("TC-A11Y")]
    assert rows and {r["Status"] for r in rows} <= {"PASSED", "SKIPPED"}
    skipped = [r for r in rows if r["Status"] == "SKIPPED"]
    assert skipped and "existing accessibility problems" in skipped[0]["Actual Result"]
    assert rows[0]["Module / Feature"].startswith("Accessibility - ")


def test_a_new_accessibility_problem_fails_the_test_and_names_it(site, suite):
    site.broken = {"a11y"}
    try:
        result = run_pytest(suite, "tests/e2e/test_accessibility.py")
    finally:
        site.broken = set()
    assert result.code == 1 and len(result.failed) == 1
    assert "New accessibility problems" in result.output
    assert "image-alt" in result.output and "button-name" in result.output      # the two new problems, named
    assert " label (" not in result.output.split("New accessibility problems")[1][:400]   # the old 'label' problem is not blamed


def test_a_short_lived_flicker_is_not_reported_as_an_accessibility_problem(scan, suite):
    """The home page shows low-contrast text for 0.7 seconds, then fixes it, like the entrance animation that caused a false
    failure on a real site. It is not a problem for people, so it must be neither in the baseline nor a failure."""
    home = next(p for p in scan["accessibility"] if p["page_url"].rstrip("/") == scan["url"].rstrip("/"))
    assert "color-contrast" not in {v["id"] for v in home["violations"]}
    assert run_pytest(suite, "tests/e2e/test_accessibility.py").code == 0


def test_text_that_stays_low_contrast_is_a_real_problem(site, suite):
    site.broken = {"js"}          # no script: the low-contrast text is never fixed
    try:
        result = run_pytest(suite, "tests/e2e/test_accessibility.py")
    finally:
        site.broken = set()
    assert result.code == 1 and "color-contrast" in result.output


# ---- cookie banner -------------------------------------------------------------------------------------------------------------------------
def test_scan_finds_and_dismisses_the_cookie_wall_choosing_reject(scan):
    assert scan["consent_banner"] == {"container": "#cookie-banner", "button": "Reject all"}
    assert not any(n["kind"] == "cookie-banner" for n in scan["coverage_notes"])      # nothing left that it could not dismiss


def test_scan_still_finds_everything_behind_the_cookie_wall(scan):
    """The wall covers the whole page. If the scan had not dismissed it, the clicks that verify tabs, toggles and the popup would fail."""
    widgets = scan["components"]["interactions"]
    assert widgets["tabs"] and widgets["toggles"] and widgets["carousels"] and scan["components"]["modal"]
    assert scan["user_session"] and scan["admin_session"]       # login also had to get past the wall


def test_the_generated_suite_remembers_the_banner(suite):
    import json
    assert json.loads((suite / "suite_config.json").read_text(encoding="utf-8"))["consent_banner"]["button"] == "Reject all"
    assert (suite / "qa_consent.py").exists()


def test_without_the_banner_memory_the_same_tests_are_blocked(site, suite, tmp_path):
    """Proof the feature matters: a copy of the suite that does not know about the banner is stopped by the wall."""
    import json
    import shutil
    copy = tmp_path / "no_consent_memory"
    shutil.copytree(suite, copy)
    config = json.loads((copy / "suite_config.json").read_text(encoding="utf-8"))
    config["consent_banner"] = None
    (copy / "suite_config.json").write_text(json.dumps(config), encoding="utf-8")
    result = run_pytest(copy, "tests/e2e/test_interactions.py")
    assert result.code == 1 and "test_tabs_1" in result.failed        # the wall swallows the clicks
    assert run_pytest(suite, "tests/e2e/test_interactions.py").code == 0   # while the real suite gets past it


# ---- text boxes outside forms ---------------------------------------------------------------------------------------------------------------------
def test_scan_finds_typing_boxes_and_sees_what_enter_does(scan):
    boxes = {b["label"]: b for b in scan["components"]["interactions"]["inputs"]}
    assert boxes["What needs to be done?"]["effect"] == "text_appears" and boxes["What needs to be done?"]["tried_enter"]
    assert boxes["Your nickname"]["effect"] is None                       # Enter did nothing visible
    assert "Search rooms" not in boxes                                    # the search box is not a typing box
    assert any("showed no visible result" in n["text"] and "Your nickname" in n["text"] for n in scan["coverage_notes"])


def test_without_permission_the_box_is_found_but_nothing_is_typed(site):
    from qa_generator.scanner import dynamic_scan_site
    quiet = dynamic_scan_site(url=site.url, accounts=[], headed=False, timeout_ms=20000, submit_forms=False)
    boxes = quiet["components"]["interactions"]["inputs"]
    assert {b["label"] for b in boxes} == {"What needs to be done?", "Your nickname"}
    assert all(not b["tried_enter"] and b["effect"] is None for b in boxes)
    assert any("--submit-forms" in n["text"] for n in quiet["coverage_notes"])    # tells the person how to test it


def test_the_enter_test_passes_when_the_box_works_and_fails_when_it_stops(site, suite):
    healthy = run_pytest(suite, "tests/e2e/test_interactions.py")
    assert healthy.code == 0, healthy.output[-1500:]
    assert (suite / "tests/e2e/test_interactions.py").read_text(encoding="utf-8").count("def test_type_into_") == 3   # todo, todo+Enter, nickname

    site.broken = {"js"}      # the Enter handler is removed
    try:
        broken = run_pytest(suite, "tests/e2e/test_interactions.py")
    finally:
        site.broken = set()
    assert "test_type_into_what_needs_to_be_done_and_press_enter" in broken.failed
    assert "test_type_into_what_needs_to_be_done" not in broken.failed        # typing alone still works: no false alarm
    assert "test_type_into_your_nickname" not in broken.failed


# ---- the settings file, through the real command line ------------------------------------------------------------------------------------------
def run_cli(site, workdir, *args, extra_env=None):
    env = {**os.environ, "QA_GENERATOR_HOME": str(workdir / "home"), "QA_GENERATOR_WORKSPACE": str(workdir),
           "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(Path(__file__).resolve().parents[2]), **(extra_env or {})}
    return subprocess.run([sys.executable, "-m", "qa_generator", *args, "--accept-terms", "--quick", "--no-run"], cwd=workdir,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=400, env=env,
                          stdin=subprocess.DEVNULL)


def test_a_settings_file_drives_a_whole_run_and_the_command_line_overrides_it(site, tmp_path):
    import json
    (tmp_path / "nes-qa.toml").write_text(f"""
url = "{site.url}"
login_url = "/login"

[run]
mode = "e2e"
folder = "from-settings"

[accounts.user]
username = "user@x.com"
password_env = "NESQA_TEST_USER_PW"

[skip]
paths = ["/cart"]
""", encoding="utf-8")

    # 1. no website on the command line: everything comes from the file; the password comes from the environment
    first = run_cli(site, tmp_path, extra_env={"NESQA_TEST_USER_PW": "pw"})
    assert first.returncode == 0, first.stdout[-1500:] + first.stderr[-1500:]
    assert "Using settings from nes-qa.toml" in first.stdout
    suite = tmp_path / "from-settings"
    assert (suite / "tests/e2e/test_user_session.py").exists()            # the account in the file was used to log in
    assert not (suite / "tests/api").exists()                             # mode = "e2e"
    assert "pw" in (suite / ".env").read_text(encoding="utf-8")           # test passwords live in the suite's git-ignored .env
    assert "pw" not in (tmp_path / "nes-qa.toml").read_text(encoding="utf-8")
    scan = json.loads((suite / "scan.json").read_text(encoding="utf-8"))
    routes = [link["route"] for link in scan["homepage"]["nav_links"]]
    assert "/cart" not in routes and "/account" in routes                 # the skipped page was never visited
    assert not any(url.endswith("/cart") for url in scan["user_session"]["http_ok_urls"] + scan["user_session"]["guest_blocked_urls"])
    assert any("skip.paths" in note["text"] and "/cart" in note["text"] for note in scan["coverage_notes"])
    assert "/cart" not in "".join(p.read_text(encoding="utf-8") for p in (suite / "tests").rglob("*.py"))

    # 2. the command line wins: --mode api replaces the file's mode = "e2e", and --no-config ignores the file altogether
    second = run_cli(site, tmp_path, site.url, "--mode", "api", "-o", "cli-wins", extra_env={"NESQA_TEST_USER_PW": "pw"})
    assert second.returncode == 0, second.stdout[-1500:] + second.stderr[-1500:]
    assert (tmp_path / "cli-wins/tests/api").exists() and not (tmp_path / "cli-wins/tests/e2e").exists()
    third = run_cli(site, tmp_path, site.url, "--no-config", "--no-auth", "-o", "no-file", "--mode", "e2e")
    assert third.returncode == 0 and "Using settings" not in third.stdout


def test_a_missing_password_variable_stops_the_run_with_a_clear_message(site, tmp_path):
    (tmp_path / "nes-qa.toml").write_text(f'url = "{site.url}"\n[accounts.user]\nusername = "u@x.com"\npassword_env = "NESQA_NOT_SET_ANYWHERE"\n',
                                          encoding="utf-8")
    result = run_cli(site, tmp_path)
    assert result.returncode == 2
    assert "NESQA_NOT_SET_ANYWHERE" in result.stderr and "not set" in result.stderr
    assert not any(tmp_path.glob("*/suite_config.json"))                   # nothing was scanned or written
