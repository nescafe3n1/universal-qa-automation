"""
The settings file, nes-qa.toml: everything you would otherwise type on the command line, kept in one place.

    nes-qa --init          writes a commented template into the current folder
    nes-qa                 uses ./nes-qa.toml automatically when it exists
    nes-qa --config FILE   uses another file          nes-qa --no-config   ignores the file

Anything typed on the command line wins over the file. Passwords do not belong in the file: write the NAME of an
environment variable (password_env) and put the password in that variable, or in a .env file next to the settings
file. A plain `password = "..."` is allowed but gives a warning.
"""

import difflib
import os
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:   # Python 3.10 has no built-in TOML reader
    import tomli as tomllib

CONFIG_NAME = "nes-qa.toml"
MODES = ("all", "e2e", "api")

KNOWN_KEYS = {
    "": {"url", "login_url", "run", "accounts", "skip"},
    "run": {"mode", "timeout_ms", "headed", "folder", "submit_forms", "write_tests", "cookie_button", "public_only"},
    "accounts": {"user", "admin"},
    "accounts.user": {"username", "password_env", "password", "landing"},
    "accounts.admin": {"username", "password_env", "password", "landing"},
    "skip": {"paths"},
}

TEMPLATE = """# Nes-Dev QA settings. Everything here is optional: remove the "#" in front of a line to use it.
# Anything you type on the command line wins over this file.
# Keep this file out of git if it ever contains anything private (it should not: see "password_env" below).

# The website to test. With this set, `nes-qa` does not ask for it.
# url = "https://example.com"

# Where the login form is, if the tool cannot find it by itself.
# login_url = "/login"

[run]
# What to test: "all" (browser + HTTP), "e2e" (browser only) or "api" (HTTP only).
# mode = "all"

# How many milliseconds a page may take to load (1000 to 300000).
# timeout_ms = 30000

# Show the browser window while testing.
# headed = false

# Name of the folder the tests are written to (default: made from the address).
# folder = "my-site-tests"

# true = ALSO submit forms and press Enter in text boxes. This SENDS data to the site (emails, sign-ups, orders).
# submit_forms = false

# true = ALSO send POST / PUT / PATCH / DELETE probes. This SENDS data to the site.
# write_tests = false

# The button to click on a cookie banner, if the tool cannot work out which one by itself.
# cookie_button = "Accept all"

# true = never ask about a login.
# public_only = false

[accounts.user]
# A normal customer account. Use a dedicated test account, never a real person's.
# username = "tester@example.com"
# The NAME of the environment variable holding the password (or put VARIABLE=password in a .env file next to this file).
# password_env = "QA_USER_PASSWORD"
# The page this user lands on after logging in (the tool finds it by itself if left out).
# landing = "/account"

[accounts.admin]
# An administrator test account (optional).
# username = "admin@example.com"
# password_env = "QA_ADMIN_PASSWORD"
# landing = "/admin"

[skip]
# Pages the tool must never visit or test. "*" matches anything: "/admin/danger/*" skips everything below that folder.
# paths = ["/logout", "/admin/danger/*"]
"""


class ConfigError(Exception):
    """The settings file is wrong in a way the person needs to fix. The message says what and where."""


class Settings:
    def __init__(self, path: Path, values: dict, warnings: list):
        self.path, self.values, self.warnings = path, values, warnings

    @property
    def url(self):
        return self.values.get("url")

    @property
    def skip_paths(self) -> list:
        return self.values.get("skip_paths", [])


# ---------------------------------------------------------------------------
# Reading and checking the file
# ---------------------------------------------------------------------------
def _check_keys(table: dict, where: str, warnings: list) -> None:
    allowed = KNOWN_KEYS[where]
    for key in table:
        if key not in allowed:
            name = f"{where}.{key}" if where else key
            guess = difflib.get_close_matches(key, allowed, n=1)
            warnings.append(f"Unknown setting '{name}' is ignored" + (f" (did you mean '{guess[0]}'?)" if guess else "."))


def _text(table: dict, key: str, where: str):
    value = table.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"'{where}{key}' must be text, for example {key} = \"...\".")
    return value.strip()


def _flag(table: dict, key: str, where: str) -> bool:
    value = table.get(key, False)
    if not isinstance(value, bool):
        raise ConfigError(f"'{where}{key}' must be true or false (no quotes).")
    return value


def _read_env_file(path: Path) -> dict:
    """KEY=value lines (quotes allowed, # comments). A minimal reader: the real environment always wins."""
    values = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            values[key.strip()] = value
    return values


def _account(role: str, table: dict, settings_dir: Path, warnings: list) -> dict:
    where = f"accounts.{role}."
    username = _text(table, "username", where)
    if not username:
        raise ConfigError(f"[accounts.{role}] needs a username.")
    password_env, password = _text(table, "password_env", where), _text(table, "password", where)
    if password_env:
        password = os.environ.get(password_env) or _read_env_file(settings_dir / ".env").get(password_env)
        if not password:
            raise ConfigError(f"The password for the {role} account comes from the environment variable {password_env}, "
                              f"but it is not set. Set it, or add the line {password_env}=... to a .env file next to {CONFIG_NAME}.")
    elif password:
        warnings.append(f"The {role} password is written in plain text in {CONFIG_NAME}. Keep that file private "
                        "(or use password_env instead, which names an environment variable).")
    else:
        raise ConfigError(f"[accounts.{role}] needs password_env (the name of an environment variable) or password.")
    return {"username": username, "password": password, "landing": _text(table, "landing", where)}


def load(path) -> Settings:
    """Read and check a settings file. Raises ConfigError with a plain message if something is wrong."""
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"The settings file {path} does not exist.") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"This is not valid TOML: {exc}") from None

    warnings = []
    _check_keys(raw, "", warnings)
    run, accounts, skip = raw.get("run", {}), raw.get("accounts", {}), raw.get("skip", {})
    for name, table in (("run", run), ("accounts", accounts), ("skip", skip)):
        if not isinstance(table, dict):
            raise ConfigError(f"'{name}' must be a [{name}] section.")
    _check_keys(run, "run", warnings)
    _check_keys(accounts, "accounts", warnings)
    _check_keys(skip, "skip", warnings)

    values = {"url": _text(raw, "url", ""), "login_url": _text(raw, "login_url", "")}
    if values["url"] and not values["url"].startswith(("http://", "https://")) and "." not in values["url"] and ":" not in values["url"]:
        raise ConfigError(f"'url' = \"{values['url']}\" does not look like a web address.")

    mode = _text(run, "mode", "run.")
    if mode is not None and mode not in MODES:
        raise ConfigError(f"'run.mode' must be one of {', '.join(MODES)}, not \"{mode}\".")
    timeout = run.get("timeout_ms")
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, int) or not 1000 <= timeout <= 300000):
        raise ConfigError("'run.timeout_ms' must be a whole number between 1000 and 300000 (milliseconds).")
    values.update(mode=mode, timeout_ms=timeout, folder=_text(run, "folder", "run."), cookie_button=_text(run, "cookie_button", "run."),
                  headed=_flag(run, "headed", "run."), submit_forms=_flag(run, "submit_forms", "run."),
                  write_tests=_flag(run, "write_tests", "run."), public_only=_flag(run, "public_only", "run."))

    values["accounts"] = {}
    for role in ("user", "admin"):
        if role in accounts:
            if not isinstance(accounts[role], dict):
                raise ConfigError(f"'accounts.{role}' must be a [accounts.{role}] section.")
            _check_keys(accounts[role], f"accounts.{role}", warnings)
            if accounts[role]:   # an empty heading (the template ships with them) simply means "no account"
                values["accounts"][role] = _account(role, accounts[role], path.resolve().parent, warnings)

    paths = skip.get("paths", [])
    if not isinstance(paths, list) or not all(isinstance(p, str) and p.strip() for p in paths):
        raise ConfigError("'skip.paths' must be a list of text, for example paths = [\"/logout\", \"/admin/danger/*\"].")
    values["skip_paths"] = ["/" + p.strip().lstrip("/") for p in paths]
    return Settings(path, values, warnings)


# ---------------------------------------------------------------------------
# Using it
# ---------------------------------------------------------------------------
def find(argv: list, cwd=None):
    """Which settings file applies? Returns a Path or None. --no-config turns it off; --config FILE picks one."""
    if "--no-config" in argv:
        return None
    for i, arg in enumerate(argv):
        if arg == "--config" and i + 1 < len(argv):
            return Path(argv[i + 1])
        if arg.startswith("--config="):
            return Path(arg.split("=", 1)[1])
    candidate = Path(cwd or Path.cwd()) / CONFIG_NAME
    return candidate if candidate.exists() else None


def peek_url(argv: list):
    """The website named in the settings file, if there is a usable file (used to skip the 'which website?' question)."""
    try:
        path = find(argv)
        return load(path).url if path else None
    except ConfigError:
        return None


def apply(args, settings: Settings) -> None:
    """Fill in whatever the command line left out. Command-line values are never replaced."""
    v = settings.values

    def fill(name, value):
        if getattr(args, name, None) in (None, False) and value not in (None, False):
            setattr(args, name, value)

    fill("url", v["url"])
    fill("login_url", v["login_url"])
    fill("mode", v["mode"])
    fill("timeout", v["timeout_ms"])
    fill("output", v["folder"])
    fill("cookie_button", v["cookie_button"])
    for flag, name in (("headed", "headed"), ("submit_forms", "submit_forms"), ("include_write_tests", "write_tests"), ("no_auth", "public_only")):
        fill(flag, v[name])
    for role, (user_arg, password_arg, target_arg) in {"user": ("user", "password", "user_target"),
                                                       "admin": ("admin_user", "admin_password", "admin_target")}.items():
        account = v["accounts"].get(role)
        if account and getattr(args, user_arg, None) is None:   # a --user on the command line replaces the file's whole account
            setattr(args, user_arg, account["username"])
            setattr(args, password_arg, account["password"])
            setattr(args, target_arg, account["landing"])


def write_template(path) -> int:
    """nes-qa --init: write the commented template. Never overwrites. Returns an exit code."""
    path = Path(path)
    if path.exists():
        print(f"{path.name} already exists in {path.parent}. Nothing was changed.")
        return 2
    path.write_text(TEMPLATE, encoding="utf-8")
    print(f"Created {path}\nOpen it, remove the \"#\" in front of the settings you want, and run nes-qa again.")
    return 0
