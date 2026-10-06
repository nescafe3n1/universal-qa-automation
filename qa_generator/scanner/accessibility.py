"""Records the serious accessibility problems each public page already has, so the tests can flag only NEW ones."""

from qa_generator.templates.qa_a11y import serious_violations

MAX_A11Y_PAGES = 8   # axe takes a second or two per page; the homepage and the first few pages are enough for a baseline


def scan_accessibility(page, page_url: str) -> dict:
    """{'page_url': ..., 'violations': [{'id', 'impact', 'help', 'nodes'}]} for the page that is open right now."""
    found = serious_violations(page)
    return {"page_url": page_url, "violations": list(found.values())}
