"""Questions the tool asks (and does not ask), and the command line."""

import subprocess
import sys
import types

import pytest

from qa_generator import __version__, prompts
from qa_generator.cli import build_parser


def args(**kwargs):
    base = dict(quick=False, mode=None, output=None, include_write_tests=False, submit_forms=False,
                no_auth=False, login_url=None, user=None, password=None, admin_user=None, admin_password=None)
    base.update(kwargs)
    return types.SimpleNamespace(**base)


@pytest.fixture
def terminal(monkeypatch):
    """Pretend a person is at a terminal, and fail loudly if the tool asks anything unexpected."""
    monkeypatch.setattr(prompts, "is_interactive", lambda: True)

    def no_questions(prompt=""):
        raise AssertionError(f"The tool asked a question it should not have asked: {prompt!r}")

    monkeypatch.setattr(prompts, "cinput", no_questions)
    monkeypatch.setattr(prompts, "cprint", lambda *a, **k: None)


# ---- --quick: no questions at all --------------------------------------------------------------
def test_quick_mode_skips_the_mode_and_folder_questions(terminal, tmp_path):
    a = args(quick=True)
    assert prompts.prompt_mode(a) == "all"
    assert prompts.prompt_folder_name(a, "https://example.com/shop", tmp_path) == (tmp_path / "example_com_shop").resolve()


def test_quick_mode_still_asks_the_two_questions_about_sending_data(monkeypatch):
    """The quick start must not silently decide whether data is sent: it asks, y means yes, Enter means no."""
    monkeypatch.setattr(prompts, "is_interactive", lambda: True)
    monkeypatch.setattr(prompts, "cprint", lambda *a, **k: None)
    asked = []

    def answer(question=""):
        asked.append(question)
        return "y" if "write requests" in question else ""

    monkeypatch.setattr(prompts, "cinput", answer)
    assert prompts.prompt_write_actions(args(quick=True), {"e2e", "api"}) == (True, False)
    assert len(asked) == 2 and all(q.endswith("[y/N]: ") for q in asked)


def test_quick_mode_still_asks_whether_the_site_needs_a_login(monkeypatch):
    """The quick start must not silently drop login testing: it asks once, and 'no' (the default) keeps it to public pages."""
    asked = []
    monkeypatch.setattr(prompts, "is_interactive", lambda: True)
    monkeypatch.setattr(prompts, "cprint", lambda *a, **k: None)
    monkeypatch.setattr(prompts, "cinput", lambda q="": asked.append(q) or "")
    login_path, accounts = prompts.prompt_for_credentials(args(quick=True), "https://example.com")
    assert accounts == [] and len(asked) == 1 and "login" in asked[0].lower()


def test_quick_mode_login_answers_become_accounts_without_the_extra_questions(monkeypatch):
    asked = []
    answers = iter(["y", "", "me@x.com", ""])   # needs a login? / login page (default) / username / admin account (blank = none)
    monkeypatch.setattr(prompts, "is_interactive", lambda: True)
    monkeypatch.setattr(prompts, "cprint", lambda *a, **k: None)
    monkeypatch.setattr(prompts, "cinput", lambda q="": asked.append(q) or next(answers))
    monkeypatch.setattr(prompts, "cgetpass", lambda q="": "secret")
    monkeypatch.setattr(prompts, "quick_detect_login_url", lambda url: "https://example.com/login")
    login_path, accounts = prompts.prompt_for_credentials(args(quick=True), "https://example.com")
    assert login_path == "https://example.com/login"
    assert [(a["role"], a["username"], a["password"], a["target_path"]) for a in accounts] == [("user", "me@x.com", "secret", "")]
    assert not any("post-login" in q for q in asked)   # the tool finds the landing page itself in the quick start


def test_full_mode_still_asks_where_login_lands(monkeypatch):
    asked = []
    answers = iter(["y", "", "me@x.com", "/dashboard", ""])
    monkeypatch.setattr(prompts, "is_interactive", lambda: True)
    monkeypatch.setattr(prompts, "cprint", lambda *a, **k: None)
    monkeypatch.setattr(prompts, "cinput", lambda q="": asked.append(q) or next(answers))
    monkeypatch.setattr(prompts, "cgetpass", lambda q="": "secret")
    monkeypatch.setattr(prompts, "quick_detect_login_url", lambda url: "https://example.com/login")
    _, accounts = prompts.prompt_for_credentials(args(), "https://example.com")
    assert accounts[0]["target_path"] == "/dashboard" and any("post-login" in q for q in asked)


def test_quick_mode_still_honours_explicit_flags(terminal):
    a = args(quick=True, include_write_tests=True, submit_forms=True)
    assert prompts.prompt_write_actions(a, {"e2e", "api"}) == (True, True)   # the terminal fixture fails if it asks


def test_quick_mode_uses_login_flags_when_given(terminal):
    a = args(quick=True, user="me@x.com", password="pw", login_url="/login")
    login_path, accounts = prompts.prompt_for_credentials(a, "https://example.com")
    assert [acc["role"] for acc in accounts] == ["user"] and login_path == "/login"


# ---- the two questions about sending data default to NO -------------------------------------------
@pytest.mark.parametrize("answer, expected", [("", False), ("n", False), ("maybe", False), ("y", True), ("YES", True)])
def test_confirm_defaults_to_no(monkeypatch, answer, expected):
    monkeypatch.setattr(prompts, "cinput", lambda q="": answer)
    monkeypatch.setattr(prompts, "cprint", lambda *a, **k: None)
    assert prompts._confirm("Send it?", "warning") is expected


def test_confirm_treats_ctrl_c_as_no(monkeypatch):
    def interrupted(q=""):
        raise KeyboardInterrupt
    monkeypatch.setattr(prompts, "cinput", interrupted)
    monkeypatch.setattr(prompts, "cprint", lambda *a, **k: None)
    assert prompts._confirm("Send it?", "warning") is False


def test_write_questions_only_asked_for_the_modes_that_need_them(monkeypatch):
    asked = []
    monkeypatch.setattr(prompts, "is_interactive", lambda: True)
    monkeypatch.setattr(prompts, "_confirm", lambda question, warning: asked.append(question) or False)
    prompts.prompt_write_actions(args(), {"e2e"})
    assert len(asked) == 1 and "submit" in asked[0].lower()
    asked.clear()
    prompts.prompt_write_actions(args(), {"api"})
    assert len(asked) == 1 and "write" in asked[0].lower()


def test_no_questions_without_a_terminal(monkeypatch):
    monkeypatch.setattr(prompts, "is_interactive", lambda: False)
    monkeypatch.setattr(prompts, "_confirm", lambda *a: pytest.fail("asked without a terminal"))
    assert prompts.prompt_write_actions(args(), {"e2e", "api"}) == (False, False)
    assert prompts.prompt_mode(args()) == "all"


# ---- command line ----------------------------------------------------------------------------------
def test_parser_knows_the_documented_options():
    parsed, _ = build_parser().parse_known_args(["https://example.com", "--quick", "--verbose", "--submit-forms", "--mode", "e2e"])
    assert parsed.quick and parsed.verbose and parsed.submit_forms and parsed.mode == "e2e"


def test_security_mode_was_removed():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["https://example.com", "--mode", "security"])


def test_version_flag_prints_the_version():
    done = subprocess.run([sys.executable, "-m", "qa_generator", "--version"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and __version__ in done.stdout
