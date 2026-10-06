"""The clean terminal view and the launcher screen."""

import csv

import pytest

from qa_generator import launcher, ui
from qa_generator.logo import LOGO_LINES, LOGO_WIDTH
from qa_generator.templates import csv_reporter


# ---- ui ------------------------------------------------------------------------------------------
def test_progress_bar_fills_up():
    assert ui._bar(0, 10, 10) == "[----------]"
    assert ui._bar(5, 10, 10) == "[#####-----]"
    assert ui._bar(10, 10, 10) == "[##########]"
    assert ui._bar(3, 0, 10) == "[----------]"   # total not known yet


@pytest.mark.parametrize("count, word, expected", [(1, "link", "1 link"), (2, "link", "2 links"), (0, "link", "0 links")])
def test_plurals(count, word, expected):
    assert ui._n(count, word) == expected


def test_paint_only_adds_colour_when_colour_is_on(monkeypatch):
    monkeypatch.setattr(ui, "COLOR", False)
    assert ui.paint("hi", "red") == "hi"
    monkeypatch.setattr(ui, "COLOR", True)
    assert ui.paint("hi", "red").startswith("\x1b[") and "hi" in ui.paint("hi", "red")


def test_clean_view_needs_a_real_terminal_and_no_verbose(monkeypatch):
    class Args:
        verbose = False
    monkeypatch.setattr(ui.sys.stdout, "isatty", lambda: False, raising=False)
    assert ui.is_clean(Args()) is False   # piped output (CI, other programs) always gets the detailed format


def write_results(suite_dir, rows):
    (suite_dir / "reports").mkdir(parents=True)
    with open(suite_dir / "reports" / "latest_test_run.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=csv_reporter.COLUMNS)
        writer.writeheader()
        for i, (status, scenario, actual, notes) in enumerate(rows, start=1):
            writer.writerow({c: "" for c in csv_reporter.COLUMNS} | {
                "Test Case ID": f"TC-{i:03d}", "Test Scenario / Objective": scenario, "Status": status,
                "Actual Result": actual, "Defects / Notes": notes})


def test_final_summary_lists_failures_in_plain_words(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ui, "COLOR", False)
    write_results(tmp_path, [("PASSED", "Home loads", "Passed in 1s.", "None."),
                             ("FAILED", "Cart opens", "Failed: Cart returned 500.", "Failed on the Guest / Public side.")])
    ui.show_final_summary(tmp_path, 12.0, 1)
    out = capsys.readouterr().out
    assert "SOME TESTS FAILED" in out and "Passed 1" in out and "Failed 1" in out
    assert "TC-002" in out and "Cart opens" in out and "Cart returned 500." in out


def test_final_summary_says_all_passed(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ui, "COLOR", False)
    write_results(tmp_path, [("PASSED", "Home loads", "Passed in 1s.", "None.")])
    ui.show_final_summary(tmp_path, 3.0, 0)
    assert "ALL PASSED" in capsys.readouterr().out


def test_final_summary_explains_timeouts(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ui, "COLOR", False)
    write_results(tmp_path, [("FAILED", "Home loads", "Failed: Timed out.", "Timed out on the Guest / Public side: the site was slow.")])
    ui.show_final_summary(tmp_path, 3.0, 1)
    assert "not confirmed bugs" in capsys.readouterr().out


def test_final_summary_without_results_is_honest(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ui, "COLOR", False)
    (tmp_path / "reports").mkdir()
    ui.show_final_summary(tmp_path, 1.0, 3)
    assert "NO RESULTS" in capsys.readouterr().out


# ---- logo and launcher -------------------------------------------------------------------------------
def test_logo_is_a_plain_rectangle_of_text():
    assert len(LOGO_LINES) >= 20 and LOGO_WIDTH == max(len(line) for line in LOGO_LINES)


def info_value(label):
    return dict(launcher.info_rows())[label]


def test_info_panel_has_the_expected_facts():
    labels = [label for label, _ in launcher.info_rows()]
    assert labels == ["Tool", "Host", "OS", "Terminal", "Python", "Playwright", "Browser", "Tests", "Suites", "Last run", "Folder"]
    assert "Nes-Dev QA" in info_value("Tool")


def test_splash_puts_info_beside_the_logo_in_a_normal_window(capsys, monkeypatch):
    monkeypatch.setattr(ui, "COLOR", False)
    launcher.show_splash(columns=110)
    lines = capsys.readouterr().out.split("\n")
    header = next(line for line in lines if "nes-dev@qa" in line)
    assert any(ch in header for ch in "▀▄█")           # logo characters on the same row
    assert max(len(line) for line in lines) <= 110                   # and it fits the window


def test_splash_stacks_in_a_narrow_window(capsys, monkeypatch):
    monkeypatch.setattr(ui, "COLOR", False)
    launcher.show_splash(columns=80)
    header = next(line for line in capsys.readouterr().out.split("\n") if "nes-dev@qa" in line)
    assert not any(ch in header for ch in "▀▄█")      # info is under the logo, not beside it


def test_url_prompt_retries_until_it_gets_a_web_address(monkeypatch, capsys):
    answers = iter(["not a url", "", "example.com"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert launcher.ask_url() == "https://example.com"
    assert "does not look like a web address" in capsys.readouterr().out


@pytest.mark.parametrize("typed", ["q", "quit", "EXIT"])
def test_url_prompt_can_be_quit(monkeypatch, typed):
    monkeypatch.setattr("builtins.input", lambda prompt="": typed)
    assert launcher.ask_url() is None


def test_url_prompt_treats_ctrl_c_as_quit(monkeypatch):
    def interrupted(prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", interrupted)
    assert launcher.ask_url() is None


def test_info_flags_skip_the_logo_screen(monkeypatch):
    seen = []
    monkeypatch.setattr(launcher, "run_tool", lambda argv: seen.append(argv) or 0)
    monkeypatch.setattr(launcher, "show_splash", lambda *a: pytest.fail("showed the logo for --version"))
    assert launcher.main(["--version"]) == 0 and seen == [["--version"]]


def test_final_summary_points_to_the_evidence_folder(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ui, "COLOR", False)
    write_results(tmp_path, [("FAILED", "Cart opens", "Failed: Cart returned 500.", "Failed on the Guest / Public side.")])
    (tmp_path / "reports" / "evidence" / "TC-001").mkdir(parents=True)
    (tmp_path / "reports" / "evidence" / "TC-001" / "failure.png").write_bytes(b"x")
    ui.show_final_summary(tmp_path, 3.0, 1)
    assert "Evidence" in capsys.readouterr().out


def test_final_summary_has_no_evidence_line_when_everything_passed(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ui, "COLOR", False)
    write_results(tmp_path, [("PASSED", "Home loads", "Passed in 1s.", "None.")])
    ui.show_final_summary(tmp_path, 3.0, 0)
    assert "Evidence" not in capsys.readouterr().out
