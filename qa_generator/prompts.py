"""Interactive prompts: output folder name and test-account credentials."""

import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright

from qa_generator.utils import cgetpass, cinput, cprint, is_interactive, resolve_endpoint_url, slugify


def quick_detect_login_url(target_url: str) -> str:
    """Quickly probes the target site to find a likely login link."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(ignore_https_errors=True)
                page.goto(target_url, wait_until="domcontentloaded", timeout=12000)
                candidate = page.locator(
                    "a[href*='login' i], a[href*='signin' i], a[href*='sign-in' i], a[href*='account' i]"
                ).first
                if candidate.count() > 0:
                    href = candidate.get_attribute("href")
                    if href:
                        return urljoin(target_url, href)
            finally:
                browser.close()
    except Exception:
        pass
    return resolve_endpoint_url(target_url, "/login")


def prompt_folder_name(args, target_url: str, base_dir: Path) -> Path:
    """Ask for the output folder name (created in the workspace root) unless -o was given."""
    if getattr(args, "output", None):
        return (base_dir / args.output).resolve()
    quick = getattr(args, "quick", False)

    parsed = urlparse(target_url)
    path_parts = [p for p in parsed.path.split('/') if p]
    host = parsed.netloc.replace('www.', '')
    suggested_slug = slugify(f"{host}_{path_parts[-1]}" if path_parts else host)

    if quick or not is_interactive():
        return (base_dir / suggested_slug).resolve()

    cprint("\n" + "=" * 65)
    cprint("   TEST PROJECT SETUP")
    cprint("=" * 65)
    cprint(f"Target URL: {target_url}")
    try:
        user_input = cinput(f"Name your test folder [default: {suggested_slug}]: ").strip()
    except (KeyboardInterrupt, EOFError):
        cprint(f"\nUsing default folder: {suggested_slug}")
        user_input = ""
    chosen_name = re.sub(r'[^\w\s-]', '_', user_input).strip() or suggested_slug
    return (base_dir / chosen_name).resolve()


def _account(role: str, username: str, password: str, target_path: str) -> dict:
    return {
        "role": role,
        "name": "Standard User Account" if role == "user" else "Administrator Account",
        "username": username,
        "password": password,
        "target_path": target_path or "",
    }


def prompt_for_credentials(args, target_url: str):
    """Return (login_url, accounts) from CLI flags, or by asking interactively."""
    accounts = []
    login_url_input = getattr(args, "login_url", None)
    quick = getattr(args, "quick", False)   # quick start: still asks about the login, but skips the extra detail questions

    # Passwords may come from QA_USER_PASSWORD / QA_ADMIN_PASSWORD so they never appear on a command line.
    user_password = getattr(args, "password", None) or os.environ.get("QA_USER_PASSWORD")
    admin_password = getattr(args, "admin_password", None) or os.environ.get("QA_ADMIN_PASSWORD")
    if getattr(args, "user", None) and user_password:
        accounts.append(_account("user", args.user, user_password, getattr(args, "user_target", "")))
    if getattr(args, "admin_user", None) and admin_password:
        accounts.append(_account("admin", args.admin_user, admin_password, getattr(args, "admin_target", "")))

    if accounts or getattr(args, "no_auth", False):
        return login_url_input or resolve_endpoint_url(target_url, "/login"), accounts

    if not is_interactive():
        return None, []

    cprint("\n" + "=" * 65)
    cprint("   AUTHENTICATION & CREDENTIALS SETUP")
    cprint("=" * 65)
    try:
        ask_auth = cinput("Does this website require login / authentication? [y/N]: ").strip().lower()
        if ask_auth not in ["y", "yes"]:
            cprint(">> Proceeding with dynamic public test suite.\n")
            return None, []

        cprint(">> Auto-detecting login route...")
        detected_login = quick_detect_login_url(target_url)
        login_path = cinput(f"Enter login path or URL [default: {detected_login}]: ").strip() or detected_login

        cprint("\n--- Account 1: Standard User / Member / Regular Role ---")
        user_name = cinput("Enter email or username: ").strip()
        user_pass = cgetpass("Enter password (hidden): ").strip()
        if user_name and user_pass:
            target_route = "" if quick else cinput("Target post-login route (leave blank to auto-detect redirect): ").strip()
            accounts.append(_account("user", user_name, user_pass, target_route))

        cprint("\n--- Account 2: Administrator / Privileged Role (Optional) ---")
        admin_name = cinput("Enter admin email or username (leave blank to skip): ").strip()
        if admin_name:
            admin_pass = cgetpass("Enter admin password (hidden): ").strip()
            admin_route = "" if quick else cinput("Target post-login route (leave blank to auto-detect redirect): ").strip()
            accounts.append(_account("admin", admin_name, admin_pass, admin_route))

        cprint(f"\n>> Configured {len(accounts)} authentication account(s). They will be saved to the suite's .env file.")
        return login_path, accounts

    except (KeyboardInterrupt, EOFError):
        cprint("\n>> Skipping authentication prompt.")
        return None, []


def _confirm(question: str, warning: str) -> bool:
    """Ask a yes/no question that defaults to NO. Anything but y/yes (or no terminal input) means no."""
    cprint(f"\n{warning}")
    try:
        return cinput(f"{question} [y/N]: ").strip().lower() in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        cprint("\n>> Skipped (treated as no).")
        return False


def prompt_write_actions(args, modes) -> tuple:
    """
    Return (include_write_tests, submit_forms). A flag on the command line means yes; otherwise, in a
    terminal, ask (default no) so nobody sends data to a live site by accident. The quick start asks too:
    these two answers decide whether data is sent, so they are never skipped. Without a terminal
    (CI, the web UI) the answer is just the flags.
    """
    write_tests = bool(getattr(args, "include_write_tests", False))
    submit_forms = bool(getattr(args, "submit_forms", False))
    if not is_interactive():
        return write_tests, submit_forms

    if "api" in modes and not write_tests:
        write_tests = _confirm(
            "Send write requests (POST/PUT/PATCH/DELETE) to the site?",
            "=" * 65 + "\n   WRITE-REQUEST TESTS\n" + "=" * 65 +
            "\nThese send POST, PUT, PATCH and DELETE requests to the real site. They can create,\n"
            "change or delete data. Say yes only on a test or staging site where that is fine.")
    if "e2e" in modes and not submit_forms:
        submit_forms = _confirm(
            "Fill in AND submit the forms found on the site?",
            "=" * 65 + "\n   FORM SUBMIT TESTS\n" + "=" * 65 +
            "\nIf yes, every form found is filled and submitted (forms that look like delete, logout or\n"
            "checkout are never submitted). This can send emails, create accounts or place orders.\n"
            "If no, forms are still filled and checked, just not submitted.")
    return write_tests, submit_forms


MODE_CHOICES = {
    "1": ("all", "All tests            (E2E + API)"),
    "2": ("e2e", "E2E testing only     (browser tests)"),
    "3": ("api", "API testing only     (HTTP tests)"),
}
MODE_TO_TYPES = {
    "all": frozenset({"e2e", "api"}),
    "e2e": frozenset({"e2e"}),
    "api": frozenset({"api"}),
}


def prompt_mode(args) -> str:
    """Return 'all', 'e2e' or 'api' from --mode, or by showing a menu."""
    if getattr(args, "mode", None):
        return args.mode
    if getattr(args, "quick", False) or not is_interactive():
        return "all"

    cprint("\n" + "=" * 65)
    cprint("   WHAT DO YOU WANT TO TEST?")
    cprint("=" * 65)
    for key, (_, label) in MODE_CHOICES.items():
        cprint(f"  [{key}] {label}")
    try:
        choice = cinput("Choose 1-3 [default: 1]: ").strip() or "1"
    except (KeyboardInterrupt, EOFError):
        choice = "1"
    return MODE_CHOICES.get(choice, MODE_CHOICES["1"])[0]
