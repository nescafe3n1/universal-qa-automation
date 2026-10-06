"""
Terms-of-use acceptance (stored locally).

* Terms: accepted once per terms version (stored locally); asked again when the text changes.
Everything is stored on the user's own machine. Nothing is sent anywhere.
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from qa_generator.utils import is_interactive

LEGAL_DIR = Path(__file__).resolve().parent / "legal"
DOCS = ("TERMS_OF_USE.md", "PRIVACY.md")
AGREE_PHRASE = "I AGREE"


def config_dir() -> Path:
    return Path(os.environ.get("QA_GENERATOR_HOME") or Path.home() / ".3am-automation")


def read_doc(name: str) -> str:
    """Document text without the publisher-only HTML comment at the top."""
    text = (LEGAL_DIR / name).read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->\s*", "", text, flags=re.DOTALL).strip()


def terms_version() -> str:
    """Changes automatically whenever either document changes, which forces re-acceptance."""
    digest = hashlib.sha256()
    for name in DOCS:
        digest.update(read_doc(name).encode("utf-8"))
    return digest.hexdigest()[:12]


def print_documents() -> None:
    for name in DOCS:
        print("\n" + "=" * 65)
        print(read_doc(name))
    print("\n" + "=" * 65)


def _acceptance_file() -> Path:
    return config_dir() / "accepted_terms.json"


def has_accepted_terms() -> bool:
    try:
        return json.loads(_acceptance_file().read_text(encoding="utf-8")).get("version") == terms_version()
    except Exception:
        return False


def _write_private(path: Path, text: str, append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a" if append else "w", encoding="utf-8") as f:
        f.write(text)


def _record_acceptance(via: str) -> None:
    record = {"version": terms_version(), "accepted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "via": via}
    _write_private(_acceptance_file(), json.dumps(record, indent=2))


def accept_terms(via: str) -> None:
    """Record acceptance of the current terms (used by the local web UI after the user types the phrase)."""
    _record_acceptance(via)


def ensure_terms_accepted(accept_flag: bool = False) -> bool:
    """True when the user has accepted the current Terms of Use and Privacy Notice."""
    if has_accepted_terms():
        return True
    if accept_flag:
        _record_acceptance("--accept-terms flag")
        print(">> Terms of Use and Privacy Notice accepted via --accept-terms (stored locally).")
        return True
    if not is_interactive():
        print("\n[!] You must accept the Terms of Use and Privacy Notice before using this tool.")
        print("    Read them with:  run-playwright --terms")
        print("    Then accept by adding:  --accept-terms")
        return False

    print("\n" + "=" * 65)
    print("   TERMS OF USE & PRIVACY NOTICE  (please read)")
    print("=" * 65)
    print_documents()
    print("In short: test only sites you own or have written permission to test; you are responsible for your use;")
    print("results are not guaranteed; nothing you do here is sent to the publisher.")
    try:
        answer = input(f'\nType "{AGREE_PHRASE}" to accept (anything else exits): ').strip()
    except (KeyboardInterrupt, EOFError):
        answer = ""
    if answer != AGREE_PHRASE:
        print(">> Terms not accepted. Exiting without doing anything.")
        return False
    _record_acceptance("interactive")
    print(">> Thank you. Your acceptance is stored locally in", _acceptance_file())
    return True
