"""
Nes-Dev QA — Universal Playwright Test Generator & Runner.

Scans any website with Playwright, then writes and runs a tailored
pytest + Playwright E2E / API test suite for it.

Package layout:
    cli.py        command-line entry point
    prompts.py    interactive folder / credential prompts
    scanner/      live site reconnaissance (DOM, links, network, login)
    generator/    writes the pytest project from the scan result
    runner.py     runs pytest on the generated project
    templates/    files copied verbatim into every generated suite
"""

__version__ = "2.0.0"
