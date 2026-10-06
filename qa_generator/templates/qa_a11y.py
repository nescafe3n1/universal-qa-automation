"""
Accessibility checks with axe-core (https://github.com/dequelabs/axe-core, Mozilla Public License 2.0).

Used by the scanner (to record the problems a page already has) and copied into every generated suite next to
axe.min.js (to catch NEW problems later). Only critical and serious problems against WCAG 2.0 / 2.1 level A and AA
are looked at: those are the ones that stop real people from using a page. A passing check does not mean a page is
fully accessible; automatic tools find only part of the problems.
"""

from pathlib import Path

AXE_SOURCE = (Path(__file__).with_name("axe.min.js")).read_text(encoding="utf-8")
SERIOUS = ("critical", "serious")
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]

RUN_AXE = """async (tags) => {
    const result = await axe.run(document, {runOnly: {type: 'tag', values: tags}, resultTypes: ['violations']});
    return result.violations.map(v => ({id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length}));
}"""


def _settle(page) -> None:
    """Wait until the page has stopped changing. Colours checked in the middle of an entrance animation are not the real colours."""
    try:
        page.wait_for_load_state("networkidle", timeout=4000)
    except Exception:
        pass
    try:
        page.evaluate("document.fonts ? document.fonts.ready.then(() => true) : true")
    except Exception:
        pass
    page.wait_for_timeout(1500)


def _look(page) -> dict:
    found = page.evaluate(RUN_AXE, TAGS)
    return {v["id"]: v for v in found if v["impact"] in SERIOUS}


def serious_violations(page) -> dict:
    """
    Critical and serious problems on the page: {rule id: {'impact', 'help', 'nodes'}}.
    The page is allowed to settle first, and a problem only counts if two looks, 0.7 seconds apart, both see it.
    Without that, a half-finished animation gave a false 'color-contrast' failure on a real site.
    """
    if not page.evaluate("typeof window.axe !== 'undefined'"):
        page.evaluate(AXE_SOURCE)   # evaluated through the browser's debugger, so the site's own security policy cannot block it
    _settle(page)
    first = _look(page)
    page.wait_for_timeout(700)
    second = _look(page)
    return {rule: details for rule, details in first.items() if rule in second}


def describe(violations: dict) -> str:
    """One readable sentence: 'label (critical, 3 elements: Form elements must have labels); image-alt (...)'."""
    parts = []
    for rule_id, v in violations.items():
        plural = "" if v["nodes"] == 1 else "s"
        parts.append(f"{rule_id} ({v['impact']}, {v['nodes']} element{plural}: {v['help']})")
    return "; ".join(parts)
