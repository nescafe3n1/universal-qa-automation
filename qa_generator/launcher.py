"""
Nes-Dev QA launcher: a splash screen (logo on the left, system and tool info on the right), then two questions
(the website to test, and whether it needs a login), then the whole test run with safe defaults.

    nes-qa.bat                      asks for the URL, then about the login
    nes-qa.bat https://example.com  skips the URL question
    nes-qa.bat https://example.com --user a@b.c --password x --login-url /login   login given up front
    nes-qa.bat https://example.com --no-auth    public pages only: no login question
    nes-qa.bat --ask                the full set of questions (mode, folder, login pages, write tests...)
"""

import importlib.metadata
import os
import platform
import sys
from pathlib import Path
from urllib.parse import urlparse

from qa_generator import ui, utils
from qa_generator import __version__, settings
from qa_generator.cli import WORKSPACE_DIR, main as run_tool
from qa_generator.logo import LOGO_LINES, LOGO_WIDTH
from qa_generator.utils import normalize_url

WORKSPACE = WORKSPACE_DIR  # where new test folders are created: the folder the tool is run from
GAP = 3  # spaces between the logo and the info panel


# ---------------------------------------------------------------------------
# Colours: the gold of the logo (true colour; plain text when colours are off)
# ---------------------------------------------------------------------------
def gold(text: str, bold: bool = False) -> str:
    if not ui.COLOR:
        return text
    return f"\x1b[{'1;' if bold else ''}38;2;232;190;123m{text}\x1b[0m"


# ---------------------------------------------------------------------------
# Facts shown next to the logo
# ---------------------------------------------------------------------------
def _short(value: str, limit: int = 54) -> str:
    return value if len(value) <= limit else value[: limit // 2 - 1] + "..." + value[-(limit // 2 - 2):]


def _chromium() -> str:
    """Is the browser the tests use installed? (Looks for Playwright's own download folder.)"""
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") and os.environ["PLAYWRIGHT_BROWSERS_PATH"] != "0":
        base = Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"])
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ms-playwright"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches" / "ms-playwright"
    else:
        base = Path.home() / ".cache" / "ms-playwright"
    return "Chromium (ready)" if base.exists() and any(base.glob("chromium-*")) else "Chromium (not installed: run  playwright install chromium)"


def _suites() -> list:
    return [d for d in WORKSPACE.iterdir() if d.is_dir() and (d / "suite_config.json").exists()]


def _last_run() -> str:
    """The most recent finished run among the suites in this folder, e.g. 'my-site: 46 passed, 1 failed'."""
    newest, newest_time = None, 0.0
    for suite in _suites():
        csv_file = suite / "reports" / "latest_test_run.csv"
        if csv_file.exists() and csv_file.stat().st_mtime > newest_time:
            newest, newest_time = suite, csv_file.stat().st_mtime
    if newest is None:
        return "none yet"
    rows = ui._read_results(newest)
    passed = sum(1 for r in rows if r["Status"] == "PASSED")
    failed = sum(1 for r in rows if r["Status"] == "FAILED")
    return f"{newest.name}: {passed} passed, {failed} failed"


def _version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except Exception:
        return "not installed"


def info_rows() -> list:
    return [
        ("Tool", f"Nes-Dev QA {__version__}"),
        ("Host", platform.node() or "unknown"),
        ("OS", f"{platform.system()} {platform.release()} ({platform.version()})"),
        ("Terminal", "Windows Terminal" if os.environ.get("WT_SESSION") else "Console"),
        ("Python", platform.python_version()),
        ("Playwright", _version("playwright")),
        ("Browser", _chromium()),
        ("Tests", "E2E + API"),
        ("Suites", f"{len(_suites())} generated"),
        ("Last run", _last_run()),
        ("Folder", str(WORKSPACE)),
    ]


# ---------------------------------------------------------------------------
# The splash screen
# ---------------------------------------------------------------------------
def info_lines(rows: list, max_value: int = 54) -> tuple:
    """(lines with colour codes, widest line as plain text) for the right-hand panel; long values are shortened to fit."""
    rows = [(label, _short(value, max_value)) for label, value in rows]
    title = "nes-dev@qa"
    lines = [f"{gold('nes-dev', True)}@{gold('qa', True)}", gold("-" * len(title))]
    widest = len(title)
    for label, value in rows:  # "OS: Windows 11", the colon right after the label, like fastfetch
        lines.append(f"{gold(label, True)}: {value}")
        widest = max(widest, len(label) + 2 + len(value))
    return lines, widest


MIN_VALUE_WIDTH = 24  # below this the values would be cut too short to read, so the panel goes under the logo instead


def show_splash(columns: int = None) -> None:
    columns = columns or (os.get_terminal_size().columns if sys.stdout.isatty() else 120)
    rows = info_rows()
    label_width = max(len(label) for label, _ in rows)
    # Room left beside the logo for the values: the panel shrinks to fit the window instead of dropping below the logo.
    room = columns - 2 - LOGO_WIDTH - GAP - (label_width + 2)
    side_by_side = room >= MIN_VALUE_WIDTH
    info, info_width = info_lines(rows, min(54, room) if side_by_side else 54)
    block_width = LOGO_WIDTH + GAP + info_width
    utils.CONTENT_WIDTH = max(block_width if side_by_side else max(LOGO_WIDTH, info_width), 80)  # prompts share the splash's left edge
    pad = " " * utils.left_margin()

    print()
    if side_by_side:
        top = max(0, (len(LOGO_LINES) - len(info)) // 2)  # info panel sits vertically centred beside the logo
        for row in range(max(len(LOGO_LINES), top + len(info))):
            logo = LOGO_LINES[row].ljust(LOGO_WIDTH) if row < len(LOGO_LINES) else " " * LOGO_WIDTH
            text = info[row - top] if top <= row < top + len(info) else ""
            print(f"{pad}{gold(logo)}{' ' * GAP}{text}")
    else:  # narrow window: logo above, info below (the logo is dropped if it does not fit at all)
        if columns >= LOGO_WIDTH + 2:
            for line in LOGO_LINES:
                print(pad + gold(line))
            print()
        for line in info:
            print(pad + line)
    print()


# ---------------------------------------------------------------------------
# The one question
# ---------------------------------------------------------------------------
def ask_url():
    """Ask for the website. Returns the URL, or None if the person quits."""
    pad = " " * utils.left_margin()
    print(f"{pad}{gold('Website to test', True)} {ui.paint('(for example https://example.com, or q to quit)', 'dim')}")
    while True:
        try:
            raw = input(f"{pad}{gold('>')} ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return None
        if raw.lower() in ("q", "quit", "exit"):
            return None
        if raw:
            url = normalize_url(raw)
            host = urlparse(url).netloc
            if "." in host or ":" in host or host.startswith("localhost"):
                return url
        print(f"{pad}{ui.paint('That does not look like a web address. Try again.', 'yellow')}")


def ask_again() -> bool:
    try:
        return utils.cinput("\nTest another website? [y/N]: ").strip().lower() in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if any(a in ("--version", "-h", "--help", "--terms", "--init") for a in argv):  # information only: no logo screen, no question
        return run_tool(argv)

    ask_everything = "--ask" in argv  # the full set of questions instead of the quick defaults
    argv = [a for a in argv if a != "--ask"]
    url = next((a for a in argv if a.startswith(("http://", "https://"))), None)
    configured_url = None if url else settings.peek_url(argv)   # the website named in nes-qa.toml, if any
    extra = [a for a in argv if a != url]
    if not ask_everything:
        extra.append("--quick")

    show_splash()
    code = 0
    while True:
        if configured_url:
            print(f"{' ' * utils.left_margin()}Using the website from {settings.CONFIG_NAME}: {configured_url}")
        target = url or configured_url or ask_url()
        if target is None:
            break
        code = run_tool([target] + extra)
        if url is not None or configured_url or not ask_again():  # a URL given on the command line is a one-shot run
            break
        print()
    return code


if __name__ == "__main__":
    sys.exit(main())
