"""Small helpers: URL handling, naming, centering."""

import os

import pytest

from qa_generator import utils


@pytest.mark.parametrize("typed, expected", [
    ("example.com", "https://example.com"),
    ("https://example.com", "https://example.com"),
    ("http://example.com/shop", "http://example.com/shop"),
    ("my-site.io/shop", "https://my-site.io/shop"),
    # local addresses are plain http: a local server usually does not speak https
    ("localhost:3000", "http://localhost:3000"),
    ("127.0.0.1:8769/x", "http://127.0.0.1:8769/x"),
    ("192.168.1.5", "http://192.168.1.5"),
    ("172.20.1.1", "http://172.20.1.1"),
    ("app.local", "http://app.local"),
    # 172.40 is not a private address
    ("172.40.1.1", "https://172.40.1.1"),
])
def test_normalize_url(typed, expected):
    assert utils.normalize_url(typed) == expected


def test_normalize_url_strips_spaces():
    assert utils.normalize_url("  example.com  ") == "https://example.com"


def test_slugify_makes_safe_identifiers():
    assert utils.slugify("Hello, World! -- 2024") == "hello_world_2024"
    assert utils.slugify("") == ""


def test_meaningful_words_skip_stop_words_and_repeats():
    words = utils.extract_meaningful_words("Premium Court, with the premium court view", 3)
    assert words == ["Premium", "Court"]  # 'with' and 'view' are stop words; repeats are dropped


def test_meaningful_word_falls_back_to_default():
    assert utils.extract_meaningful_word("", default="test") == "test"
    assert utils.extract_meaningful_word("go up", default="test") == "test"  # nothing 4+ letters long


def test_css_attr_escapes_quotes_and_backslashes():
    assert utils.css_attr("name", 'a"b') == '[name="a\\"b"]'
    assert utils.css_attr("id", "x\\y") == '[id="x\\\\y"]'


def test_unique_namer_never_repeats():
    namer = utils.UniqueNamer()
    assert [namer("Sign in", "x") for _ in range(3)] == ["sign_in", "sign_in_2", "sign_in_3"]
    assert namer("", "fallback") == "fallback"


def test_resolve_endpoint_url_joins_paths():
    assert utils.resolve_endpoint_url("https://a.com/app", "/login") == "https://a.com/app/login"
    assert utils.resolve_endpoint_url("https://a.com", "https://other.com/x") == "https://other.com/x"


def test_same_site_includes_subdomains():
    assert utils.same_site("https://api.example.com/x", "https://example.com")
    assert utils.same_site("https://www.example.com", "https://example.com")
    assert not utils.same_site("https://evil.com", "https://example.com")


# ---- centering -----------------------------------------------------------------------------------
def test_no_margin_when_not_a_terminal(monkeypatch):
    monkeypatch.setattr(utils, "is_interactive", lambda: False)
    assert utils.left_margin() == 0


def test_margin_centres_the_content_column(monkeypatch):
    monkeypatch.setattr(utils, "is_interactive", lambda: True)
    monkeypatch.setattr(utils.shutil, "get_terminal_size", lambda *a, **k: os.terminal_size((200, 40)))
    monkeypatch.setattr(utils, "CONTENT_WIDTH", 80)
    assert utils.left_margin() == 60


def test_margin_is_zero_in_a_narrow_window(monkeypatch):
    monkeypatch.setattr(utils, "is_interactive", lambda: True)
    monkeypatch.setattr(utils.shutil, "get_terminal_size", lambda *a, **k: os.terminal_size((60, 40)))
    assert utils.left_margin() == 0


def test_cprint_pads_text_lines_but_not_blank_lines(monkeypatch, capsys):
    monkeypatch.setattr(utils, "left_margin", lambda: 4)
    utils.cprint("one\n\ntwo")
    assert capsys.readouterr().out == "    one\n\n    two\n"
