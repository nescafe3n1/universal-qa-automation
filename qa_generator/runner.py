"""Runs pytest on a generated suite."""

import subprocess
import sys
import time
from pathlib import Path


def run_tests_now(project_dir: Path, headed: bool = False, extra_args: list = None) -> int:
    """Execute pytest inside the generated project and return its exit code."""
    print("\n[3/4] Executing test suite with pytest...")
    print("=" * 65)

    cmd = [sys.executable, "-m", "pytest"]
    if headed:
        cmd.append("--headed")
    if extra_args:
        cmd.extend(extra_args)

    start_time = time.time()
    # cwd = suite folder, so pytest.ini, .env and test-results/ all resolve inside it.
    result = subprocess.run(cmd, cwd=project_dir)
    duration = time.time() - start_time

    print("=" * 65)
    print(f"[4/4] Completed in {duration:.2f}s | Exit Code: {result.returncode}")
    if result.returncode == 0:
        print("[SUCCESS] All generated tests passed.")
    else:
        print("[NOTICE] Some tests failed or errored — see the output above and the report.")

    report_path = project_dir / "reports" / "index.html"
    if report_path.exists():
        print(f"\n>> Visual HTML Report: file:///{report_path.as_posix()}")

    return result.returncode
