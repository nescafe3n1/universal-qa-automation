"""The settings file (nes-qa.toml): reading it, checking it, and letting the command line win."""

import re
import types

import pytest

from qa_generator import cli, config, settings

FULL = """
url = "https://example.com"
login_url = "/login"

[run]
mode = "e2e"
timeout_ms = 45000
headed = true
folder = "my-tests"
submit_forms = true
write_tests = true
cookie_button = "Accept all"
public_only = false

[accounts.user]
username = "user@x.com"
password_env = "TEST_USER_PW"
landing = "/account"

[accounts.admin]
username = "admin@x.com"
password_env = "TEST_ADMIN_PW"

[skip]
paths = ["/logout", "admin/danger/*"]
"""


@pytest.fixture
def passwords(monkeypatch):
    monkeypatch.setenv("TEST_USER_PW", "user-secret")
    monkeypatch.setenv("TEST_ADMIN_PW", "admin-secret")


def write(tmp_path, text, name="nes-qa.toml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def args(**kwargs):
    base = dict(url=None, login_url=None, mode=None, timeout=None, output=None, cookie_button=None, headed=False,
                submit_forms=False, include_write_tests=False, no_auth=False, user=None, password=None, user_target=None,
                admin_user=None, admin_password=None, admin_target=None)
    base.update(kwargs)
    return types.SimpleNamespace(**base)


# ---- reading ---------------------------------------------------------------------------------------------------------
def test_a_full_file_is_read_into_values(tmp_path, passwords):
    loaded = settings.load(write(tmp_path, FULL))
    v = loaded.values
    assert (v["url"], v["login_url"], v["mode"], v["timeout_ms"], v["folder"]) == ("https://example.com", "/login", "e2e", 45000, "my-tests")
    assert v["headed"] and v["submit_forms"] and v["write_tests"] and not v["public_only"] and v["cookie_button"] == "Accept all"
    assert v["accounts"]["user"] == {"username": "user@x.com", "password": "user-secret", "landing": "/account"}
    assert v["accounts"]["admin"]["password"] == "admin-secret" and v["accounts"]["admin"]["landing"] is None
    assert v["skip_paths"] == ["/logout", "/admin/danger/*"]                 # a missing leading "/" is added
    assert loaded.warnings == []


def test_an_empty_file_is_fine_and_changes_nothing(tmp_path):
    loaded = settings.load(write(tmp_path, "# nothing set\n"))
    assert loaded.url is None and loaded.skip_paths == [] and loaded.values["accounts"] == {}


# ---- passwords ---------------------------------------------------------------------------------------------------------------
def test_password_comes_from_an_environment_variable_never_the_file(tmp_path, passwords):
    loaded = settings.load(write(tmp_path, FULL))
    assert "user-secret" not in (tmp_path / "nes-qa.toml").read_text(encoding="utf-8")
    assert loaded.values["accounts"]["user"]["password"] == "user-secret"


def test_password_can_come_from_a_dotenv_file_next_to_the_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_USER_PW", raising=False)
    (tmp_path / ".env").write_text('# test accounts\nTEST_USER_PW="from-dotenv"\nOTHER=1\n', encoding="utf-8")
    text = '[accounts.user]\nusername = "u@x.com"\npassword_env = "TEST_USER_PW"\n'
    assert settings.load(write(tmp_path, text)).values["accounts"]["user"]["password"] == "from-dotenv"


def test_the_real_environment_beats_the_dotenv_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_USER_PW", "from-environment")
    (tmp_path / ".env").write_text("TEST_USER_PW=from-dotenv\n", encoding="utf-8")
    text = '[accounts.user]\nusername = "u@x.com"\npassword_env = "TEST_USER_PW"\n'
    assert settings.load(write(tmp_path, text)).values["accounts"]["user"]["password"] == "from-environment"


def test_a_missing_password_says_which_variable_to_set(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_USER_PW", raising=False)
    text = '[accounts.user]\nusername = "u@x.com"\npassword_env = "TEST_USER_PW"\n'
    with pytest.raises(settings.ConfigError, match=r"TEST_USER_PW.*not set.*\.env"):
        settings.load(write(tmp_path, text))


def test_a_password_written_in_the_file_works_but_warns(tmp_path):
    text = '[accounts.user]\nusername = "u@x.com"\npassword = "plain"\n'
    loaded = settings.load(write(tmp_path, text))
    assert loaded.values["accounts"]["user"]["password"] == "plain"
    assert len(loaded.warnings) == 1 and "plain text" in loaded.warnings[0] and "password_env" in loaded.warnings[0]


@pytest.mark.parametrize("text, message", [
    ('[accounts.user]\npassword_env = "X"\n', "needs a username"),
    ('[accounts.user]\nusername = "u@x.com"\n', "needs password_env"),
])
def test_an_account_needs_a_username_and_a_password_source(tmp_path, text, message):
    with pytest.raises(settings.ConfigError, match=message):
        settings.load(write(tmp_path, text))


# ---- mistakes get a plain message --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text, message", [
    ('[run]\nmode = "everything"\n', r"run\.mode.*all, e2e, api.*everything"),
    ("[run]\ntimeout_ms = 50\n", r"timeout_ms.*1000 and 300000"),
    ('[run]\ntimeout_ms = "slow"\n', r"timeout_ms"),
    ("[run]\ntimeout_ms = true\n", r"timeout_ms"),
    ('[run]\nheaded = "yes"\n', r"run\.headed.*true or false"),
    ('[skip]\npaths = "/logout"\n', r"skip\.paths.*list"),
    ('[skip]\npaths = [1, 2]\n', r"skip\.paths.*list"),
    ('url = "nonsense"\n', r"does not look like a web address"),
    ("run = 5\n", r"'run' must be a \[run\] section"),
    ("url = \n", r"not valid TOML"),
])
def test_mistakes_are_explained(tmp_path, text, message):
    with pytest.raises(settings.ConfigError, match=message):
        settings.load(write(tmp_path, text))


def test_a_missing_file_is_explained(tmp_path):
    with pytest.raises(settings.ConfigError, match="does not exist"):
        settings.load(tmp_path / "nope.toml")


def test_a_misspelt_setting_is_reported_with_a_suggestion_not_ignored_silently(tmp_path):
    loaded = settings.load(write(tmp_path, '[run]\nmodee = "all"\ntimeout = 5\n\n[sip]\npaths = []\n'))
    text = " ".join(loaded.warnings)
    assert "run.modee" in text and "did you mean 'mode'" in text
    assert "run.timeout" in text and "did you mean 'timeout_ms'" in text
    assert "'sip'" in text and "did you mean 'skip'" in text


# ---- the command line wins ------------------------------------------------------------------------------------------------------
def test_the_file_fills_in_what_the_command_line_left_out(tmp_path, passwords):
    a = args()
    settings.apply(a, settings.load(write(tmp_path, FULL)))
    assert (a.url, a.login_url, a.mode, a.timeout, a.output, a.cookie_button) == (
        "https://example.com", "/login", "e2e", 45000, "my-tests", "Accept all")
    assert a.headed and a.submit_forms and a.include_write_tests
    assert (a.user, a.password, a.user_target) == ("user@x.com", "user-secret", "/account")
    assert (a.admin_user, a.admin_password) == ("admin@x.com", "admin-secret")


def test_command_line_values_are_never_replaced(tmp_path, passwords):
    a = args(url="https://cli.example", mode="api", timeout=9000, output="cli-folder", user="cli@x.com", password="cli-pw")
    settings.apply(a, settings.load(write(tmp_path, FULL)))
    assert (a.url, a.mode, a.timeout, a.output) == ("https://cli.example", "api", 9000, "cli-folder")
    assert (a.user, a.password) == ("cli@x.com", "cli-pw")             # the file's user account is not mixed in
    assert a.user_target is None
    assert a.admin_user == "admin@x.com"                                # but the admin the command line did not mention is used


def test_a_false_in_the_file_does_not_switch_anything_on(tmp_path):
    a = args()
    settings.apply(a, settings.load(write(tmp_path, "[run]\nheaded = false\nsubmit_forms = false\n")))
    assert not a.headed and not a.submit_forms


# ---- which file ----------------------------------------------------------------------------------------------------------------------
def test_find_uses_the_file_in_the_current_folder(tmp_path):
    assert settings.find([], cwd=tmp_path) is None
    path = write(tmp_path, "")
    assert settings.find([], cwd=tmp_path) == path


def test_find_honours_config_and_no_config(tmp_path):
    write(tmp_path, "")
    assert settings.find(["--no-config"], cwd=tmp_path) is None
    assert str(settings.find(["--config", "other.toml"], cwd=tmp_path)) == "other.toml"
    assert str(settings.find(["--config=other.toml"], cwd=tmp_path)) == "other.toml"


def test_peek_url_gives_the_website_or_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert settings.peek_url([]) is None
    write(tmp_path, 'url = "https://example.com"\n')
    assert settings.peek_url([]) == "https://example.com"
    write(tmp_path, "url = \n")                                           # a broken file must not crash the launcher
    assert settings.peek_url([]) is None


# ---- the template stays honest --------------------------------------------------------------------------------------------------------
def test_every_setting_in_the_template_is_valid_when_switched_on(tmp_path, passwords):
    keys = "url|login_url|mode|timeout_ms|headed|folder|submit_forms|write_tests|cookie_button|public_only|username|password_env|landing|paths"
    switched_on = "\n".join(re.sub(rf"^# ({keys}) = ", r"\1 = ", line) for line in settings.TEMPLATE.splitlines())
    assert switched_on != settings.TEMPLATE                               # something really was switched on
    monkeypatch_env = {"QA_USER_PASSWORD": "u", "QA_ADMIN_PASSWORD": "a"}
    import os
    os.environ.update(monkeypatch_env)
    try:
        loaded = settings.load(write(tmp_path, switched_on))
    finally:
        for name in monkeypatch_env:
            os.environ.pop(name)
    assert loaded.warnings == [] and loaded.url == "https://example.com"
    assert set(loaded.values["accounts"]) == {"user", "admin"} and loaded.skip_paths == ["/logout", "/admin/danger/*"]


def test_the_template_as_written_changes_nothing(tmp_path):
    loaded = settings.load(write(tmp_path, settings.TEMPLATE))
    assert loaded.url is None and loaded.values["accounts"] == {} and loaded.skip_paths == [] and loaded.warnings == []


def test_init_writes_the_template_and_never_overwrites(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--init"]) == 0 and (tmp_path / "nes-qa.toml").read_text(encoding="utf-8") == settings.TEMPLATE
    (tmp_path / "nes-qa.toml").write_text("url = \"https://mine.example\"\n", encoding="utf-8")
    assert cli.main(["--init"]) == 2
    assert "already exists" in capsys.readouterr().out
    assert "mine.example" in (tmp_path / "nes-qa.toml").read_text(encoding="utf-8")


def test_a_broken_settings_file_stops_the_run_before_anything_is_scanned(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write(tmp_path, '[run]\nmode = "everything"\n')
    assert cli.main(["https://example.com"]) == 2
    assert "nes-qa.toml" in capsys.readouterr().err


# ---- pages to skip --------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def skipping():
    yield config.set_skip_paths
    config.set_skip_paths([])             # never leak patterns into other tests


@pytest.mark.parametrize("path, skipped", [
    ("/logout", True), ("/logout/", True), ("/logout?next=/", True), ("/logout#x", True),
    ("/admin/danger", True), ("/admin/danger/delete-all", True), ("/admin/danger/a/b", True),
    ("/admin", False), ("/admin/dangerous", False), ("/about", False), ("/", False),
])
def test_skip_patterns(skipping, path, skipped):
    skipping(["/logout", "/admin/danger/*"])
    assert config.is_skipped_path(path) is skipped


def test_skip_patterns_work_for_a_site_inside_a_folder(skipping):
    skipping(["/logout", "/private/*"], "https://example.com/shop")
    assert config.is_skipped_path("/shop/logout") and config.is_skipped_path("/shop/private/x")
    assert not config.is_skipped_path("/shop/about")


def test_nothing_is_skipped_without_patterns(skipping):
    skipping([])
    assert not config.is_skipped_path("/logout")


# ---- the launcher ---------------------------------------------------------------------------------------------------------------------
def test_launcher_does_not_ask_for_the_website_when_the_settings_file_names_one(tmp_path, monkeypatch):
    from qa_generator import launcher
    monkeypatch.chdir(tmp_path)
    write(tmp_path, 'url = "https://example.com"\n')
    calls = []
    monkeypatch.setattr(launcher, "run_tool", lambda argv: calls.append(argv) or 0)
    monkeypatch.setattr(launcher, "show_splash", lambda *a: None)
    monkeypatch.setattr(launcher, "ask_url", lambda: pytest.fail("asked for the website although the settings file names one"))
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("asked 'test another website?' for a configured website"))
    assert launcher.main([]) == 0
    assert calls == [["https://example.com", "--quick"]]


def test_launcher_still_asks_when_the_settings_file_has_no_website(tmp_path, monkeypatch):
    from qa_generator import launcher
    monkeypatch.chdir(tmp_path)
    write(tmp_path, "# only a login here\n")
    asked = []
    monkeypatch.setattr(launcher, "run_tool", lambda argv: 0)
    monkeypatch.setattr(launcher, "show_splash", lambda *a: None)
    monkeypatch.setattr(launcher, "ask_url", lambda: asked.append(True) or None)
    launcher.main([])
    assert asked == [True]


def test_launcher_passes_init_straight_through_without_the_logo_screen(monkeypatch):
    from qa_generator import launcher
    calls = []
    monkeypatch.setattr(launcher, "run_tool", lambda argv: calls.append(argv) or 0)
    monkeypatch.setattr(launcher, "show_splash", lambda *a: pytest.fail("showed the logo for --init"))
    assert launcher.main(["--init"]) == 0 and calls == [["--init"]]
