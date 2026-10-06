"""Everything the test writers need, resolved once from the scan result and CLI options."""

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from qa_generator.config import is_skipped_path
from qa_generator.utils import resolve_endpoint_url


def _guard_url(target, session, explicit: bool):
    """
    The URL a 'guests are refused' test should use. The page login lands on is often public
    (e.g. a cart), so it is only used if the scan saw guests being refused from it; otherwise the first
    refused page found is used, or None. An explicit --user-target / --admin-target is always trusted.
    """
    blocked = (session or {}).get("guest_blocked_urls")
    if explicit or blocked is None:  # told by the user, or an older scan that did not probe
        return target
    return target if target in blocked else (blocked[0] if blocked else None)


@dataclass
class SuiteContext:
    target_url: str
    output_dir: Path
    scan: dict
    accounts: list
    login_url: str
    include_write_tests: bool = False
    submit_forms: bool = False
    modes: frozenset = frozenset({"e2e", "api"})
    user_acc: dict = None
    admin_acc: dict = None
    user_target_url: str = None
    admin_target_url: str = None
    user_guard_url: str = None   # a user-area URL that guests really are refused from (None = none found)
    admin_guard_url: str = None
    written: list = field(default_factory=list)

    @classmethod
    def build(cls, target_url, output_dir, scan, accounts, login_path, include_write_tests, modes=None,
              submit_forms=False):
        accounts = accounts or []
        ctx = cls(
            target_url=target_url,
            output_dir=output_dir,
            scan=scan,
            accounts=accounts,
            login_url=resolve_endpoint_url(target_url, login_path or "/login"),
            include_write_tests=include_write_tests,
            submit_forms=submit_forms,
            modes=frozenset(modes) if modes else frozenset({"e2e", "api"}),
            user_acc=next((a for a in accounts if a["role"] in ["user", "customer"]), None),
            admin_acc=next((a for a in accounts if a["role"] == "admin"), None),
        )
        # Explicit post-login targets win; otherwise use where the login actually landed.
        if ctx.user_acc and ctx.user_acc.get("target_path"):
            ctx.user_target_url = resolve_endpoint_url(target_url, ctx.user_acc["target_path"])
        elif scan.get("user_session"):
            ctx.user_target_url = scan["user_session"]["post_login_url"]
        if ctx.admin_acc and ctx.admin_acc.get("target_path"):
            ctx.admin_target_url = resolve_endpoint_url(target_url, ctx.admin_acc["target_path"])
        elif scan.get("admin_session"):
            ctx.admin_target_url = scan["admin_session"]["dashboard_url"]
        # A page the person asked to skip is not a test target, even when login lands on it.
        if ctx.user_target_url and is_skipped_path(urlparse(ctx.user_target_url).path):
            ctx.user_target_url = None
        if ctx.admin_target_url and is_skipped_path(urlparse(ctx.admin_target_url).path):
            ctx.admin_target_url = None
        ctx.user_guard_url = _guard_url(ctx.user_target_url, scan.get("user_session"), bool(ctx.user_acc and ctx.user_acc.get("target_path")))
        ctx.admin_guard_url = _guard_url(ctx.admin_target_url, scan.get("admin_session"), bool(ctx.admin_acc and ctx.admin_acc.get("target_path")))
        return ctx

    @property
    def is_inertia(self) -> bool:
        return bool(self.scan.get("is_inertia"))

    @property
    def tests_dir(self) -> Path:
        return self.output_dir / "tests"

    def is_protected_target(self, url: str) -> bool:
        """A post-login URL is only worth a guard test if it isn't the site root."""
        if not url:
            return False
        path = (urlparse(url).path or "/").rstrip("/")
        root = (urlparse(self.target_url).path or "/").rstrip("/")
        return path not in ("", root)

    def write_test(self, kind: str, filename: str, code: str) -> None:
        path = self.tests_dir / kind / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")
        self.written.append(path)
