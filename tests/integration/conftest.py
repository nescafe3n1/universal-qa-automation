"""Shared setup for the browser tests: the local test website, a scan of it, and a suite generated from that scan."""

import os
import re
import subprocess
import sys
import types

import pytest
from playwright.sync_api import sync_playwright

from qa_generator.generator import generate_dynamic_test_suite
from qa_generator.scanner import dynamic_scan_site
from tests.integration.site import Site

ACCOUNTS = [
    {"role": "user", "name": "Standard User Account", "username": "user@x.com", "password": "pw", "target_path": ""},
    {"role": "admin", "name": "Administrator Account", "username": "admin@x.com", "password": "pw", "target_path": ""},
]


@pytest.fixture(scope="session")
def browser_ready():
    """Skip these tests, with a clear reason, if Chromium has not been installed."""
    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
    except Exception as exc:
        pytest.skip(f"Chromium is not installed ({type(exc).__name__}). Run: playwright install chromium")


@pytest.fixture(scope="session")
def site(browser_ready):
    running = Site()
    yield running
    running.stop()


@pytest.fixture(scope="module")
def scan(site):
    assert not site.broken
    return dynamic_scan_site(url=site.url, login_path="/login", accounts=ACCOUNTS, headed=False, timeout_ms=20000,
                             submit_forms=True)   # allowed to press Enter in text boxes outside forms


@pytest.fixture(scope="module")
def suite(site, scan, tmp_path_factory):
    """A test suite generated from the scan of the healthy site (forms are submitted, so submit tests exist)."""
    out = tmp_path_factory.mktemp("generated") / "suite"
    generate_dynamic_test_suite(site.url, out, scan, ACCOUNTS, "/login", include_write_tests=False,
                                modes={"e2e", "api"}, submit_forms=True)
    return out


def run_pytest(directory, *args, timeout=420, env_extra=None):
    """Run pytest inside a generated suite, like a user would. Returns the exit code, failed test names and the output."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", **(env_extra or {})}
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rf", "-p", "no:cacheprovider", *args], cwd=directory,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)
    output = done.stdout + done.stderr
    failed = re.findall(r"^FAILED \S+?::(test_\w+)", output, re.MULTILINE)
    return types.SimpleNamespace(code=done.returncode, failed=failed, output=output)
