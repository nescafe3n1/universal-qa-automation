"""
Clean terminal output for Nes-Dev QA: colours, step headers, a live status line, a progress bar for the test
run and a short final summary.

Only used when a person is running the tool in a real terminal. When output is piped (CI, the web agent) or
--verbose is given, the tool prints its original detailed output instead, so nothing that reads it breaks.
"""

import contextlib
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from qa_generator.utils import cinput, cprint, is_interactive, left_margin

RULE = "=" * 65


# ---------------------------------------------------------------------------
# Basics: when to use the clean view, colours
# ---------------------------------------------------------------------------
def is_clean(args) -> bool:
    """Clean view = a real terminal and no --verbose."""
    return bool(sys.stdout.isatty() and is_interactive() and not getattr(args, "verbose", False))


def _enable_ansi() -> bool:
    """Colours need ANSI support; Windows consoles must be switched on first."""
    if not sys.stdout.isatty() or "NO_COLOR" in os.environ:
        return False
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            return False
    return True


COLOR = _enable_ansi()
CODES = {"green": "32", "red": "31", "yellow": "33", "dim": "2", "bold": "1"}


def paint(text: str, style: str) -> str:
    return f"\x1b[{CODES[style]}m{text}\x1b[0m" if COLOR else text


def _width() -> int:
    return shutil.get_terminal_size().columns


def _clear_line() -> str:
    """Return to the start of the line and wipe it (works on consoles without ANSI support too)."""
    return "\r\x1b[2K" if COLOR else "\r" + " " * (_width() - 1) + "\r"


def link(path: Path, label: str = None) -> str:
    """A clickable file link in terminals that support it (Windows Terminal does); plain text elsewhere."""
    label = label or str(path)
    if not COLOR:
        return label
    return f"\x1b]8;;{path.resolve().as_uri()}\x1b\\{label}\x1b]8;;\x1b\\"


# ---------------------------------------------------------------------------
# Step headers and the live status line
# ---------------------------------------------------------------------------
def step(number: int, total: int, text: str) -> None:
    cprint("")
    cprint(paint(f"[{number}/{total}] {text}", "bold"))


class _StatusStream(io.TextIOBase):
    """
    Stands in for stdout while a noisy step runs. Everything printed is kept (for the log), and the latest
    line is shown on ONE updating status line instead of scrolling the screen.
    """

    def __init__(self, real, label: str):
        self.real, self.label, self.log = real, label, []
        self.started = time.time()

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self.log.append(text)
        latest = next((ln.strip() for ln in reversed(text.splitlines()) if ln.strip()), None)
        if latest:
            self.draw(latest)
        return len(text)

    def flush(self) -> None:
        pass

    def draw(self, latest: str) -> None:
        room = max(20, _width() - left_margin() - 12)
        line = f"{self.label}: {latest}"
        if len(line) > room:
            line = line[: room - 3] + "..."
        self.real.write(_clear_line() + " " * left_margin() + paint(line, "dim"))
        self.real.flush()

    def clear(self) -> None:
        self.real.write(_clear_line())
        self.real.flush()


@contextlib.contextmanager
def working(label: str):
    """Run a noisy step quietly: its output goes to a log, and one status line shows what it is doing."""
    stream = _StatusStream(sys.stdout, label)
    try:
        with contextlib.redirect_stdout(stream):
            yield stream
    finally:
        stream.clear()


# ---------------------------------------------------------------------------
# Scan summary
# ---------------------------------------------------------------------------
def _n(count: int, singular: str, plural: str = None) -> str:
    """'1 link', '2 links'."""
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def _banner_line(scan: dict) -> str:
    banner = scan.get("consent_banner")
    return f'dismissed with "{banner["button"]}"' if banner else "none found"


def _accessibility_line(scan: dict) -> str:
    pages = scan.get("accessibility") or []
    if not pages:
        return "not checked"
    issues = sum(len(p["violations"]) for p in pages)
    return f"{_n(len(pages), 'page')} checked, " + (f"{_n(issues, 'serious problem')} already present" if issues else "no serious problems")


def show_scan_summary(scan: dict, had_user: bool, had_admin: bool) -> None:
    comp = scan["components"]
    inter = comp.get("interactions") or {}

    def session(value, attempted):
        return paint("logged in", "green") if value else (paint("login failed", "red") if attempted else "not used")

    content = [n for n in (
        _n(len(comp.get("all_cards") or []), "repeating list") if comp.get("all_cards") else "",
        "search box" if comp.get("search") else "",
        _n(len(comp.get("filters") or []), "filter") if comp.get("filters") else "",
        "popup" if comp.get("modal") else "",
        _n(len(comp.get("tables") or []), "table") if comp.get("tables") else "",
    ) if n]
    popup_form = 1 if (comp.get("modal") or {}).get("form") else 0
    user_forms = len((scan.get("user_session") or {}).get("forms") or [])
    admin_forms = len((scan.get("admin_session") or {}).get("forms") or [])
    names = {"tabs": ("tab set", "tab sets"), "toggles": ("toggle", "toggles"), "pagination": ("pagination", "paginations"),
             "carousels": ("carousel", "carousels"), "uploads": ("upload field", "upload fields"),
             "inputs": ("typing box", "typing boxes")}
    widgets = [_n(len(v), *names[k]) for k, v in inter.items() if v]

    rows = [
        ("Site", scan["homepage"].get("title") or "(no title)"),
        ("Pages", f"{_n(len(scan['homepage'].get('nav_links') or []), 'link')} found, {_n(len(scan.get('sub_pages') or []), 'page')} scanned"),
        ("Content", ", ".join(content) or "nothing special found"),
        ("Forms", f"{len(comp.get('forms') or [])} on pages, {popup_form} in popups, {user_forms} in the user area, {admin_forms} in the admin area"),
        ("Widgets", ", ".join(widgets) or "none"),
        ("Cookie banner", _banner_line(scan)),
        ("Accessibility", _accessibility_line(scan)),
        ("API calls seen", str(len(scan.get("captured_apis") or []))),
        ("User account", session(scan.get("user_session"), had_user)),
        ("Admin account", session(scan.get("admin_session"), had_admin)),
    ]
    cprint("")
    for label, value in rows:
        cprint(f"  {paint(label.ljust(14), 'dim')} {value}")

    notes = scan.get("coverage_notes") or []
    if notes:
        cprint("")
        cprint(paint(f"  Not covered by the tests ({len(notes)}):", "yellow"))
        for note in notes[:6]:
            cprint(f"    - {note['text']}")
        if len(notes) > 6:
            cprint(f"    ... and {len(notes) - 6} more in the report")


# ---------------------------------------------------------------------------
# The test run: one progress line instead of one line per test
# ---------------------------------------------------------------------------
RE_COLLECTED = re.compile(r"collected (\d+) items?")
RE_TEST = re.compile(r"\b(PASSED|FAILED|ERROR|SKIPPED)\b\s+\[\s*\d+%\]")


def _bar(done: int, total: int, width: int = 24) -> str:
    filled = int(width * done / total) if total else 0
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def run_tests(project_dir: Path, headed: bool, extra_args: list) -> int:
    """Run pytest in the suite folder. Shows a progress line; the full output is saved to reports/last_run.log."""
    cmd = [sys.executable, "-m", "pytest", "-v"]
    if headed:
        cmd.append("--headed")
    cmd.extend(extra_args or [])

    counts = {"PASSED": 0, "FAILED": 0, "ERROR": 0, "SKIPPED": 0}
    total, lines, warnings = 0, [], []
    pad = " " * left_margin()
    proc = subprocess.Popen(cmd, cwd=project_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")

    def draw() -> None:
        done = sum(counts.values())
        bad = counts["FAILED"] + counts["ERROR"]
        failed = paint(f"{bad} failed", "red") if bad else "0 failed"
        sys.stdout.write(f"{_clear_line()}{pad}Running tests  {_bar(done, total)}  {done}/{total or '?'}   {failed}")
        sys.stdout.flush()

    try:
        for line in proc.stdout:
            lines.append(line)
            if m := RE_COLLECTED.search(line):
                total = int(m.group(1))
            if m := RE_TEST.search(line):
                counts[m.group(1)] += 1
                draw()
            elif line.startswith("[warning]"):
                warnings.append(line.strip())
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        sys.stdout.write(_clear_line())
        cprint(paint("Stopped by you. The tests that finished are saved in the report.", "yellow"))
        proc.wait()
    finally:
        sys.stdout.write(_clear_line())
        sys.stdout.flush()

    reports = project_dir / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "last_run.log").write_text("".join(lines), encoding="utf-8")

    code = proc.returncode
    if code not in (0, 1):  # pytest could not run the tests (site unreachable, bad setup...): show why
        reason = [ln.rstrip() for ln in lines if ln.startswith("!") or "Exit:" in ln or "Error" in ln][-4:] or [ln.rstrip() for ln in lines[-6:]]
        cprint(paint("The tests could not be run:", "red"))
        for ln in reason:
            cprint(f"  {ln.strip('! ').strip()}")
    for w in warnings:
        cprint(paint(w, "yellow"))
    return code


# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
def _changes_since_last_run(project_dir: Path):
    """Compare the last two runs recorded in the suite's history (None if there is no earlier run)."""
    from qa_generator.templates.csv_reporter import compare_runs   # same logic the HTML report uses
    try:
        history = json.loads((project_dir / "reports" / ".run_history.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return compare_runs([run for run in history if run.get("format") == 2])


def _read_results(project_dir: Path) -> list:
    path = project_dir / "reports" / "latest_test_run.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def show_final_summary(project_dir: Path, seconds: float, exit_code: int) -> None:
    rows = _read_results(project_dir)
    passed = sum(1 for r in rows if r["Status"] == "PASSED")
    failed = [r for r in rows if r["Status"] == "FAILED"]
    skipped = sum(1 for r in rows if r["Status"] == "SKIPPED")
    verdict = paint("ALL PASSED", "green") if rows and not failed else paint("SOME TESTS FAILED", "red") if failed else paint("NO RESULTS", "yellow")

    cprint("")
    cprint(RULE)
    cprint(f"   RESULT   {verdict}")
    cprint(f"   {paint('Passed', 'green')} {passed}    {paint('Failed', 'red') if failed else 'Failed'} {len(failed)}    "
           f"{paint('Skipped', 'yellow') if skipped else 'Skipped'} {skipped}    Total {len(rows)}    Time {seconds:.0f}s")
    cprint(RULE)

    if failed:
        cprint("")
        cprint(paint("Failed tests", "bold"))
        for r in failed[:10]:
            cprint(f"  {r['Test Case ID']}  {r['Test Scenario / Objective']}")
            cprint(paint(f"      {r['Actual Result']}", "red"))
        if len(failed) > 10:
            cprint(f"  ... and {len(failed) - 10} more in the report")
        if any("Timed out" in r["Defects / Notes"] for r in failed):
            cprint("")
            cprint(paint("Some failures are timeouts: the site was slow. They are not confirmed bugs; run again to check.", "yellow"))

    changes = _changes_since_last_run(project_dir)
    if changes:
        cprint("")
        cprint(paint(f"Since the last run ({changes['previous_time']})", "bold"))
        if changes["newly_failing"] or changes["fixed"]:
            for label, key, colour in (("started failing", "newly_failing", "red"), ("fixed", "fixed", "green")):
                for node in changes[key][:5]:
                    cprint(paint(f"  {label}: ", colour) + changes["labels"].get(node, node))
                if len(changes[key]) > 5:
                    cprint(f"  ... and {len(changes[key]) - 5} more {label}")
        else:
            cprint("  No change: the same tests pass and fail as before.")

    report = project_dir / "reports" / "index.html"
    log = project_dir / "reports" / "last_run.log"
    cprint("")
    if report.exists():
        cprint(f"Report      {link(report)}")
    if log.exists():
        cprint(f"Full output {link(log)}")
    evidence = project_dir / "reports" / "evidence"
    if evidence.exists() and any(evidence.iterdir()):
        cprint(f"Evidence    {link(evidence)}   (a screenshot and trace for each failed test)")


def offer_to_open(project_dir: Path) -> None:
    """Ask before opening the HTML report in the browser (default: no)."""
    report = project_dir / "reports" / "index.html"
    if not report.exists():
        return
    try:
        answer = cinput("\nOpen the report now? [y/N]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return
    if answer in ("y", "yes"):
        try:
            os.startfile(str(report)) if os.name == "nt" else subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", str(report)])
        except Exception as exc:
            cprint(f"Could not open the report automatically ({exc}). Open this file yourself: {report}")
