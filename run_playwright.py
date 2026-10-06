#!/usr/bin/env python
"""
Nes-Dev QA — Universal Playwright Test Generator & Runner.

Entry point kept here so `run-playwright <URL>` and `python run_playwright.py <URL>`
keep working. The code lives in the qa_generator/ package.

Usage:
    run-playwright https://example.com
    run-playwright https://example.com --headed
    run-playwright https://example.com --no-run
    run-playwright https://example.com -o my-test-suite
"""

import sys

from qa_generator.cli import main

if __name__ == "__main__":
    sys.exit(main())
