"""Command-line entry point: terms -> mode -> permission -> scan -> generate -> run."""

import argparse
import os
import sys
import time
from pathlib import Path

from qa_generator import __version__, config, legal, settings
from qa_generator.generator import generate_dynamic_test_suite
from qa_generator.prompts import (
    MODE_TO_TYPES, prompt_folder_name, prompt_for_credentials, prompt_mode, prompt_write_actions,
)
from qa_generator.runner import run_tests_now
from qa_generator.scanner import dynamic_scan_site
from qa_generator import ui
from qa_generator.utils import cprint, normalize_url

# Generated suites are created next to run_playwright.py (the workspace root).
# New test folders are created in the folder you run the tool from (override with QA_GENERATOR_WORKSPACE).
WORKSPACE_DIR = Path(os.environ.get("QA_GENERATOR_WORKSPACE") or Path.cwd())

EXIT_NOT_ALLOWED = 2
EXIT_BAD_SETTINGS = 2   # the settings file has a mistake the person must fix (same code as a command-line usage error)


def output_dir_is_safe(path: Path) -> bool:
    """Only create new folders, or reuse a folder this tool generated (it contains suite_config.json)."""
    if not path.exists():
        return True
    if (path / "suite_config.json").is_file():
        return True
    return path.is_dir() and not any(path.iterdir())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Nes-Dev QA - Universal Playwright Test Generator")
    parser.add_argument("--version", action="version", version=f"Nes-Dev QA {__version__}")
    parser.add_argument("url", nargs="?", help="Target website URL (e.g. https://example.com)")
    parser.add_argument("--mode", choices=["all", "e2e", "api"],
                        help="What to test (asked interactively if omitted). 'all' = e2e + api.")
    parser.add_argument("--headed", action="store_true", help="Run with visible browser window")
    parser.add_argument("--no-run", action="store_true", help="Only generate tests without executing them")
    parser.add_argument("-o", "--output", help="Custom output directory for generated tests")
    parser.add_argument("--timeout", type=int, default=None, help="Navigation timeout in milliseconds (default: 30000)")
    parser.add_argument("--include-write-tests", action="store_true",
                        help="Also generate POST/PUT/PATCH/DELETE probe tests (sends write requests to the site!)")

    parser.add_argument("--config", metavar="FILE", help="Use this settings file instead of ./nes-qa.toml")
    parser.add_argument("--no-config", action="store_true", help="Ignore nes-qa.toml")
    parser.add_argument("--init", action="store_true", help="Write a commented nes-qa.toml template into this folder, then exit")
    parser.add_argument("--cookie-button", metavar="LABEL", help="The button to click on a cookie banner, if the tool cannot work it out")
    parser.add_argument("--quick", action="store_true",
                        help="Skip the questions: test everything (E2E + API) on public pages, folder named from the URL, "
                             "no write requests and no form submits unless you pass those flags.")
    parser.add_argument("--verbose", action="store_true",
                        help="Show the full detailed output (every test line, scan log) instead of the clean summary view.")
    parser.add_argument("--submit-forms", action="store_true",
                        help="Also SUBMIT the forms found on the site (sends real data to the site!). Forms are only filled by default.")

    legal_group = parser.add_argument_group("terms & permission")
    legal_group.add_argument("--terms", action="store_true", help="Show the Terms of Use and Privacy Notice, then exit")
    legal_group.add_argument("--accept-terms", action="store_true",
                             help="Accept the Terms of Use and Privacy Notice (needed once when running without a terminal)")

    parser.add_argument("--no-auth", action="store_true", help="Skip authentication prompt and generate public tests only")
    parser.add_argument("--login-url", help="Custom login route or URL (e.g. /login or /account)")
    parser.add_argument("--user", help="Normal user email or username")
    parser.add_argument("--password", help="Normal user password")
    parser.add_argument("--user-target", help="User post-login route or URL")
    parser.add_argument("--admin-user", help="Admin email or username")
    parser.add_argument("--admin-password", help="Admin password")
    parser.add_argument("--admin-target", help="Admin post-login route or URL")
    return parser


def _recover_url(args, unknown: list):
    """
    Recover gracefully if the user typed e.g. `run-playwright python run_playwright.py <URL>`.
    Returns (url, remaining_args_for_pytest).
    """
    real_url = None
    passthrough = []
    for item in [args.url] + unknown:
        if item is None:
            continue
        if item.startswith(("http://", "https://")):
            real_url = real_url or item
        elif item.lower() in ["python", "python3", "py"] or item.endswith(".py"):
            continue
        elif not real_url and not item.startswith("-") and ("." in item or ":" in item):
            real_url = item
        else:
            passthrough.append(item)
    return (normalize_url(real_url) if real_url else None), passthrough


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # never crash on characters an old Windows code page can't show
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    parser = build_parser()
    args, unknown = parser.parse_known_args(argv)

    if args.terms:
        legal.print_documents()
        return 0

    if args.init:
        return settings.write_template(Path.cwd() / settings.CONFIG_NAME)

    # The settings file fills in whatever the command line left out (the command line always wins).
    config_path = None if args.no_config else (Path(args.config) if args.config else
                                               (Path.cwd() / settings.CONFIG_NAME if (Path.cwd() / settings.CONFIG_NAME).exists() else None))
    loaded = None
    if config_path:
        try:
            loaded = settings.load(config_path)
        except settings.ConfigError as exc:
            print(f"{config_path.name}: {exc}", file=sys.stderr)
            return EXIT_BAD_SETTINGS
        settings.apply(args, loaded)
        cprint(f"Using settings from {config_path.name}")
        for warning in loaded.warnings:
            cprint(f"  Note: {warning}")
    args.timeout = args.timeout or 30000

    url, pytest_args = _recover_url(args, unknown)
    if not url:
        parser.error("the following arguments are required: url (or set url in nes-qa.toml)")
    config.set_skip_paths(loaded.skip_paths if loaded else [], url)

    # 1. Terms of Use & Privacy Notice (once per version) — before anything touches the network.
    if not legal.ensure_terms_accepted(args.accept_terms):
        return EXIT_NOT_ALLOWED

    # 2. What to test.
    mode = prompt_mode(args)
    modes = set(MODE_TO_TYPES[mode])

    output_dir = prompt_folder_name(args, url, WORKSPACE_DIR)
    if not output_dir_is_safe(output_dir):
        print(f"\n[Stopped] {output_dir} already exists and is not a folder generated by this tool.")
        print("          Choose a different folder name (-o). Nothing was changed.")
        return EXIT_NOT_ALLOWED
    login_path, accounts = prompt_for_credentials(args, url)
    # Actions that send data to the site are asked about here (default no) unless a flag already said yes.
    include_write_tests, submit_forms = prompt_write_actions(args, modes)

    cprint("\n" + "=" * 65)
    cprint("   NES-DEV QA — UNIVERSAL DYNAMIC TEST GENERATOR")
    cprint("=" * 65)
    cprint(f"Target URL   : {url}")
    cprint(f"Test Folder  : {output_dir}")
    cprint(f"Test Types   : {', '.join(t for t in ('e2e', 'api') if t in modes)}")
    cprint(f"Run Tests    : {'No' if args.no_run else 'Yes (automatic)'}")
    if "api" in modes:
        cprint(f"Write Tests  : {'Included' if include_write_tests else 'Off (read-only)'}")
    if "e2e" in modes:
        cprint(f"Form Submit  : {'ON - forms are submitted' if submit_forms else 'Off (forms are filled only)'}")

    if ui.is_clean(args):
        return _run_clean(args, url, output_dir, login_path, accounts, modes, include_write_tests, submit_forms, pytest_args)

    scan_results = dynamic_scan_site(
        url=url,
        login_path=login_path,
        accounts=accounts,
        headed=args.headed,
        timeout_ms=args.timeout,
        submit_forms=submit_forms,
        cookie_button=args.cookie_button,
    )

    generate_dynamic_test_suite(
        target_url=url,
        output_dir=output_dir,
        scan=scan_results,
        accounts=accounts,
        login_path=login_path,
        include_write_tests=include_write_tests,
        modes=modes,
        submit_forms=submit_forms,
    )

    if args.no_run:
        print(f"\n[Done] Tests generated at {output_dir}. Run anytime with:")
        print(f"       cd \"{output_dir}\" && pytest")
        return 0
    return run_tests_now(project_dir=output_dir, headed=args.headed, extra_args=pytest_args)


def _run_clean(args, url, output_dir, login_path, accounts, modes, include_write_tests, submit_forms, pytest_args) -> int:
    """The same steps as main(), shown as three short stages with a live status line and a final summary."""
    stages = 2 if args.no_run else 3

    ui.step(1, stages, "Scanning the site")
    with ui.working("Scanning"):
        scan_results = dynamic_scan_site(url=url, login_path=login_path, accounts=accounts,
                                         headed=args.headed, timeout_ms=args.timeout, submit_forms=submit_forms,
                                         cookie_button=args.cookie_button)
    ui.show_scan_summary(scan_results, any(a["role"] != "admin" for a in accounts), any(a["role"] == "admin" for a in accounts))

    ui.step(2, stages, "Writing the tests")
    with ui.working("Writing"):
        ctx = generate_dynamic_test_suite(
            target_url=url, output_dir=output_dir, scan=scan_results, accounts=accounts, login_path=login_path,
            include_write_tests=include_write_tests, modes=modes, submit_forms=submit_forms)
    cprint(f"  Wrote {len(ctx.written)} test files to {output_dir}")

    if args.no_run:
        cprint("")
        cprint(f'Run them any time with:  cd "{output_dir}" && pytest')
        return 0

    ui.step(3, stages, "Running the tests")
    started = time.time()
    code = ui.run_tests(output_dir, args.headed, pytest_args)
    ui.show_final_summary(output_dir, time.time() - started, code)
    ui.offer_to_open(output_dir)
    return code
