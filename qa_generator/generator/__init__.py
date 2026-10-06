"""
Turns a scan result into a ready-to-run pytest + Playwright project.

This package is the only part that emits test code. A future TypeScript
(@playwright/test) emitter can sit next to it and reuse the same scan dict.
"""

import shutil
from pathlib import Path

from qa_generator.generator.api import write_api_tests
from qa_generator.generator.context import SuiteContext
from qa_generator.generator.e2e import write_e2e_tests
from qa_generator.generator.project_files import write_project_files


def generate_dynamic_test_suite(target_url: str, output_dir: Path, scan: dict, accounts: list = None,
                                login_path: str = None, include_write_tests: bool = False,
                                modes=None, submit_forms: bool = False) -> SuiteContext:
    """Generate a Playwright test suite tailored to what the scan actually found."""
    print(f"\n[2/4] Generating dynamic test suite in: {output_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    tests_dir = output_dir / "tests"
    if tests_dir.exists():
        shutil.rmtree(tests_dir)
    (output_dir / "reports").mkdir(exist_ok=True)

    ctx = SuiteContext.build(target_url, output_dir, scan, accounts, login_path, include_write_tests, modes, submit_forms)
    write_project_files(ctx)
    if "e2e" in ctx.modes:
        write_e2e_tests(ctx)
    if "api" in ctx.modes:
        write_api_tests(ctx)

    print(f"      [OK] Generated {len(ctx.written)} tailored test files:")
    for path in ctx.written:
        print(f"           - {path.relative_to(output_dir).as_posix()}")
    if not include_write_tests and "api" in ctx.modes:
        print("      (Write-method tests skipped. Use --include-write-tests to add POST/PUT/PATCH/DELETE probes.)")
    if not submit_forms and ctx.scan["components"].get("forms"):
        print("      (Forms are filled but not submitted. Use --submit-forms to also submit them.)")
    return ctx
