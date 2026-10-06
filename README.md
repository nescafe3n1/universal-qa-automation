# Nes-Dev QA — Multi-Site Playwright Test Generator & Runner

A one-command QA tool: it crawls any website with Playwright, records links, components,
logins and same-site API calls, then **generates and runs** a pytest + Playwright
**E2E** and **API** test suite for that site.

Generated tests assert what the scan actually found. If the scan saw a search box,
the test fails when the search box disappears. Nothing is wrapped in "if it exists".

---

## Easiest way to start: nes-qa.bat

Double-click **nes-qa.bat** (or run `.\nes-qa.bat` in a terminal opened in this folder). It shows the Nes-Dev QA logo and
system info, asks for **the website to test**, then asks **whether the site needs a login** (press Enter for no; say yes
to give a test user, and optionally an admin, so the logged-in areas are tested too). Then it scans, writes the tests
and runs them with safe defaults: E2E + API, no write requests, no form submits.

```cmd
.\nes-qa.bat                                   :: asks for the website, the login, then two y/N questions (send write requests? submit forms?)
.\nes-qa.bat https://example.com               :: skips the website question (still asks the rest)
.\nes-qa.bat https://example.com --user me@x.com --password pw --login-url /login   :: login given up front: nothing more is asked
.\nes-qa.bat https://example.com --no-auth     :: public pages only, no login question
.\nes-qa.bat --ask                             :: ask every question (mode, folder, login pages, write tests, form submits)
```

First time only: `pip install -r requirements.txt` and `playwright install chromium` (the batch file tells you if they are missing).
`--quick` is the option behind this; you can pass it to `run-playwright` too.

---

## Install

```bash
pip install .                  # from this folder: adds the nes-qa and run-playwright commands
playwright install chromium    # once: the browser the tests use
```

Then, from any folder:

```bash
nes-qa                                         # logo screen, asks for the website and the login
nes-qa https://example.com                     # skips the question
run-playwright https://example.com --headed    # the full command line (see Options below)
nes-qa --version
```

New test folders are created in the folder you run the command from, so run it from a folder you keep for test projects, not from the project folder.

Without installing: `pip install -r requirements.txt`, `playwright install chromium`, then run `python run_playwright.py <URL>`, or start `nes-qa.bat` from this folder.
Use `pip install -e .` while developing, or `pipx install .` to keep it separate from your other Python packages.

Needs Python 3.10 or newer. It has only been tested on Windows with Python 3.14, so treat other systems as untested.

---

## Options & Flags

| Command / Flag | Description |
| :--- | :--- |
| `run-playwright <URL>` | Scans the site, asks for a folder name and (optionally) login accounts, generates E2E + API tests, runs them. |
| `--no-auth` | Skip the credentials prompt; public tests only. |
| `--login-url <path>` | Login page path or URL (e.g. `/login`, `/account`). |
| `--user <email> --password <pass>` | Standard user account (skips the prompt). |
| `--user-target <path>` | Page the user should land on after login (default: wherever login redirects). |
| `--admin-user <email> --admin-password <pass>` | Administrator account. |
| `--admin-target <path>` | Admin landing page (default: wherever admin login redirects). |
| `--include-write-tests` | **Also** generate POST/PUT/PATCH/DELETE probe tests. Off by default because they send write requests to the real site. In a terminal you are **asked** (default: no) when you don't pass the flag. |
| `--submit-forms` | **Also** submit the forms found on the site (after filling every field). Off by default: submitting can send emails, create accounts or place orders. In a terminal you are **asked** (default: no) when you don't pass the flag. |
| `--mode all\|e2e\|api` | What to test. If omitted, a menu asks. `all` = E2E + API. |
| `--accept-terms` | Accept the Terms of Use and Privacy Notice (needed once when running without a terminal, e.g. CI). |
| `--terms` | Show the Terms of Use and Privacy Notice, then exit. |
| `--verbose` | Show the full detailed output (every test line and the scan log) instead of the clean summary. The clean view is used only in a real terminal; piped output (for example in CI) always gets the detailed format. |
| `--init` | Write a commented `nes-qa.toml` settings file into this folder, then exit. Never overwrites an existing one. |
| `--config <file>` / `--no-config` | Use another settings file / ignore `nes-qa.toml`. See **The settings file** below. |
| `--cookie-button <label>` | The button to click on a cookie banner, if the tool cannot work out which one by itself. |
| `--quick` | Safe defaults without questions (what `nes-qa` uses). `nes-qa --ask` is the opposite: it asks everything. |
| `--version` | Print the version, then exit. |
| `--headed` | Show the browser while scanning and testing. |
| `--no-run` | Generate the suite without running it. |
| `-o`, `--output <folder>` | Output folder for the generated suite. |
| `--timeout 45000` | Navigation timeout in ms (default 30000). |

In a terminal the run shows three short stages, a live progress bar and a final summary (failed tests in plain words, report link, and an offer to open the report). The full test output is saved to `reports/last_run.log` in the suite folder.

Any other flags are passed to pytest, e.g. `run-playwright <URL> -m api -x`.
The exit code is pytest's, so a CI job fails when a test fails.

---

## Project Structure

```
3am-automation-projects/
├── run_playwright.py          # Entry point (thin wrapper around qa_generator.cli)
├── nes-qa.bat                 # Start here: logo screen, asks for the website and login, runs everything
├── nes-qa.toml                # (optional, yours) the settings file: see 'The settings file'
├── pyproject.toml             # Packaging: pip install . adds the nes-qa and run-playwright commands
├── tests/                     # The tool's own tests (unit, generator, and browser end-to-end)
├── .github/workflows/ci.yml   # Runs the tests on every push
├── run-playwright.bat / .ps1  # Windows launchers (full command-line options)
├── requirements.txt
├── LICENSE
├── README.md
└── qa_generator/
    ├── cli.py                 # Arguments, scan -> generate -> run, exit code
    ├── launcher.py            # The nes-qa command: logo screen and the few questions
    ├── ui.py, logo.py         # Terminal output: logo, progress bar, summary
    ├── settings.py            # Reads nes-qa.toml
    ├── legal.py               # Terms acceptance (stored locally)
    ├── server/                # Unfinished local web agent (not packaged, not part of the tool)
    ├── legal/                 # TERMS_OF_USE.md, PRIVACY.md (edit these; changes force re-acceptance)
    ├── prompts.py             # Folder name & credential prompts (passwords hidden)
    ├── config.py              # ALL selectors and keyword lists — tune detection here
    ├── utils.py               # URL helpers, slugify, unique test names, safe CSS selectors
    ├── runner.py              # Runs pytest inside the generated suite
    ├── scanner/               # Live site reconnaissance
    │   ├── __init__.py        #   dynamic_scan_site(): orchestrates the crawl
    │   ├── homepage.py        #   title, headings, landmarks, links, Ziggy routes
    │   ├── components.py      #   cards, search, filters, tables, forms, modals
    │   ├── standalone.py      #   text boxes outside forms (typed into; Enter only with --submit-forms)
    │   ├── coverage.py        #   what the scan saw but cannot test (CAPTCHA, date pickers, iframes...)
    │   ├── accessibility.py   #   axe-core scan of each public page (records existing problems)
    │   ├── interactions.py    #   tabs, toggles, pagination, carousels, uploads (each verified by clicking once)
    │   ├── auth.py            #   user / admin login crawl
    │   └── network.py         #   same-site XHR / fetch sniffing
    ├── generator/             # Writes the pytest project from the scan result
    │   ├── __init__.py        #   generate_dynamic_test_suite()
    │   ├── context.py         #   resolved settings shared by the writers
    │   ├── project_files.py   #   pytest.ini, .env, suite_config.json, runners, README
    │   ├── e2e.py             #   tests/e2e/*.py
    │   └── api.py             #   tests/api/*.py
    └── templates/             # Copied verbatim into every generated suite
        ├── conftest.py        #   fixtures + report hooks
        ├── qa_login.py        #   login helper (also used by the scanner)
        ├── qa_forms.py        #   form fill / submit / outcome helpers (also used by the scanner)
        ├── qa_consent.py      #   cookie-banner dismissal (copied only when the scan found a banner)
        ├── qa_a11y.py         #   accessibility helper (copied with axe.min.js only when used)
        ├── axe.min.js         #   axe-core, bundled unchanged (see Third-party software)
        └── csv_reporter.py    #   CSV + HTML report
```

### Generated suite

```
<your-folder>/
├── conftest.py, qa_login.py, qa_forms.py, csv_reporter.py   # copied from templates/
├── qa_consent.py, qa_a11y.py, axe.min.js   # only when the scan found a cookie banner / accessibility checks apply
├── suite_config.json          # base URL, login URL, scan facts
├── .env                       # test account credentials (git-ignored)
├── pytest.ini                 # markers: e2e, api, auth, smoke, write
├── run.bat, run_live.bat, run_api.bat, open_report.bat
├── reports/                   # index.html, latest_test_run.csv, history, comparison matrix
└── tests/
    ├── e2e/  test_navigation.py, test_components.py, test_forms.py, test_interactions.py,
    │         test_accessibility.py, test_user_session.py, test_admin_portal.py, test_access_control.py
    └── api/  test_api_public_routes.py, test_api_http_methods.py, test_api_intercepted.py,
              test_api_customer.py, test_api_admin.py, test_api_access_control.py,
              test_api_crud_lifecycle.py (only with --include-write-tests)
```
Files are only created when the scan found something to test in them.

---

## What Gets Tested

**E2E (browser)**
- Homepage status, title and main heading; primary call-to-action opens its page; skip-link target exists.
- Every visible navigation link: click → URL changes to the link's route.
- Every discovered page loads with a non-error status.
- Repeating items (cards / articles / grid), search box, filter tabs and dropdowns, dialogs (open **and** close), tables (with header text), non-login forms (every text, number, date, dropdown, checkbox and radio field is filled and must keep its value; forms are submitted only with `--submit-forms`; then each form must show a visible response (message, redirect or validation error) with no server or JavaScript error, and a form with required fields must refuse an empty submit). Forms inside a popup dialog and forms inside the logged-in user / admin areas get the same tests (file uploads are filled with a tiny test file). A form whose button or action looks destructive or spends money (delete, logout, checkout, pay, buy...) is filled but **never submitted**. Custom dropdowns (`role=combobox`, including type-to-search) inside forms are opened and an option is picked. Dropdowns outside forms are tested as filters: one test per option.
- Text boxes outside any form (a to-do box, a comment box): the test types into the box and checks it kept the text. With `--submit-forms` the scan also presses **Enter** once, and if the result is clearly visible (the text appears on the page, or the address changes) a second test checks that. Without `--submit-forms` nothing is pressed or sent. Only plain text boxes are used (never email, phone or number fields), and search/filter boxes are tested elsewhere.
- Interactive widgets, each tested only if clicking it worked during the scan: tabs (select + panel shows), accordion / menu toggles (open and close), pagination (next page changes the URL or content), carousels (next slide changes), file uploads (the field accepts a file; nothing is submitted).
- No horizontal scrolling at 375px width; no uncaught JavaScript errors.
- Accessibility: each scanned public page is checked with axe-core (WCAG 2 A and AA, critical and serious problems only). The scan records the problems a page **already has**; the test fails only on **new** ones, and existing ones show as a yellow warning. A problem must show up in two looks 0.7 seconds apart, so a page caught in the middle of an animation is not blamed. Automatic checks find only part of the accessibility problems, so a pass does not mean a page is fully accessible.
- With accounts: login really succeeds, account pages open without bouncing to login, logout ends the session, admin pages show the headings/tables seen during the scan.
- Access control: guests and standard users are refused (401/403/404, login redirect, password form, or redirect out of the protected area).

**API (HTTP)**
- Site root and **every** discovered link return < 400 (broken-link check). Links that refused guests during the scan (401/403) are tested to keep refusing them.
- Unknown URLs return a real 404 (catches soft-404 pages).
- GET / HEAD / OPTIONS handling.
- Same-site XHR/fetch calls seen during the scan are replayed: same status, same JSON keys. (Calls that used a bearer token, login calls, and write methods are not replayed.)
- Logged-in sessions can fetch their pages; guests and standard users can't fetch protected ones.

---

## Cookie banners

A cookie or consent banner covers buttons, steals clicks and changes what a page looks like, so it causes false failures. During the scan the tool looks for one on every page it opens, clicks the least invasive button that works (**reject / only necessary** first, then **accept**, then a close button) and checks that the banner really went away. It remembers which banner and button worked, and every generated test then dismisses that same banner after its first page load. A site without a banner is never slowed down, because nothing runs unless the scan found one.

- The terminal summary shows what it did (`Cookie banner: dismissed with "Reject all"`). If a banner could not be dismissed, "Not covered" says so.
- If it picks the wrong button, name the right one: `--cookie-button "Accept all"` or `cookie_button` in the settings file.
- A button only counts if its label is a clear answer (reject, accept, agree, got it...), and only inside something that looks like a consent banner, so a page that merely mentions cookies is left alone.
- Not handled: banners inside a shadow DOM or an iframe. Tested against banner markup modelled on common libraries, not against every real banner there is.

---

## The settings file

Instead of typing options every time, keep them in `nes-qa.toml` next to where you run the tool. `nes-qa --init` writes a commented template (everything is switched off until you remove the `#`). The file is read automatically; `--config FILE` uses another one and `--no-config` ignores it. **Anything typed on the command line wins over the file.**

```toml
url = "https://example.com"        # with this set, nes-qa does not ask for the website
login_url = "/login"

[run]
mode = "all"                       # all, e2e or api
timeout_ms = 30000
folder = "my-site-tests"
submit_forms = false               # true = also submit forms / press Enter (sends data)
cookie_button = "Accept all"       # only if the tool cannot work it out

[accounts.user]
username = "tester@example.com"
password_env = "QA_USER_PASSWORD"  # the NAME of an environment variable, not the password
landing = "/account"

[skip]
paths = ["/logout", "/admin/danger/*"]   # never visited or tested; * matches anything
```

- **Passwords stay out of the file.** `password_env` names an environment variable; if it is not set, a `.env` file next to the settings file is checked. A plain `password = "..."` works but prints a warning. If the variable is missing the run stops before anything is scanned and tells you which one to set.
- **Mistakes are explained, not ignored.** A wrong value (for example `mode = "everything"`) stops the run with a plain message; a misspelt setting (`modee`) is reported with a "did you mean" suggestion.
- **Skipped pages are really skipped.** They are not visited, probed or tested, even when login happens to land on one. "Not covered" lists what you asked it to skip. Patterns are relative to the site, so they also work for a site under a sub-folder.
- With a website and accounts in the file, `nes-qa` starts straight away: no website question and no login question.
- Python 3.10 needs the small `tomli` package to read TOML; it is installed automatically with `pip install .`.

---

## The report

`reports/index.html` is a plain page you can open or share:
- **Summary line and filters** (All, Passed, Failed, Skipped, and **Changed** once there is an earlier run), plus search.
- **Guest / User / Admin dividers**, so you can see which side failed. Click a row for steps, test data and the expected result.
- **Evidence for every failed test:** a screenshot of the page at the moment of failure (shown in the row), and a Playwright trace you can replay step by step with `playwright show-trace reports/evidence/<test id>/trace.zip`. It costs about 10% more run time; set `NESQA_TRACE=0` to keep only the screenshots. Evidence belongs to the latest run only.
- **Since the last run:** what started failing, what was fixed, what still fails, which tests are new. The same comparison is printed at the end of a terminal run.
- **Reliability warning** (timeouts, retries, early stop) and **Not covered** (what the scan saw but cannot test).
- The CSV files keep the 12 standard QA columns.

---

## Third-party software

The accessibility checks use **axe-core** by Deque Systems, bundled unchanged as `qa_generator/templates/axe.min.js` (version 4.10.2). It is licensed under the Mozilla Public License 2.0, and its licence notice stays at the top of the file. Source: https://github.com/dequelabs/axe-core

---

## Licence

Nes-Dev QA is released under the MIT licence (see `LICENSE`). The bundled axe-core keeps its own MPL-2.0 licence (see above).

## Terms & Privacy

- **First run:** you are shown the [Terms of Use](qa_generator/legal/TERMS_OF_USE.md) and [Privacy Notice](qa_generator/legal/PRIVACY.md) and must type `I AGREE`. This is asked again whenever the text changes. Read them anytime with `run-playwright --terms`.
- **Privacy:** nothing is sent to the publisher. No telemetry, no account. Your acceptance record lives in `~/.3am-automation/` (override with `QA_GENERATOR_HOME`). Generated HTML reports load no external resources.
- **Without a terminal (CI):** pass `--accept-terms`. Without it the tool exits with code 2 and does nothing.

---

## Reliability (slow or flaky sites)

A test that fails because the site is slow is not a bug in the site. Every generated suite protects against this:
- **Preflight:** if the site cannot be reached at all, the run stops at once (exit code 3) with a clear message; nothing is reported as broken.
- **Page loads wait for the page, not for every image or ad** (`domcontentloaded`), so one slow third-party resource does not fail a working page.
- **Timeouts are retried once** (first 3 per run). A test that passes on the second try is flagged "passed on the second try" in the report.
- **Timeouts are labelled** "not a confirmed bug" and counted in a "Reliability warning" panel at the top of the report.
- **Stops early** after 8 timeouts, because more waiting tells nothing new. The report says the run was stopped and which tests were not run.
- **Only real facts become tests:** HTTP-level tests are generated only for pages the logged-in session could really fetch over HTTP, and "guests are blocked" tests only for pages the scan saw guests being refused from. Single-page apps and public landing pages therefore do not produce false failures or false passes.

If results change between two runs on the same site, read the report's reliability panel first: it is almost always the site or the network.

---

## Known Limits (read before trusting a green run)

- Tests come from **one scan**. They catch regressions in what was found; they don't know your business rules.
- Detection is heuristic (see `config.py`). Unusual markup can be missed. Check the scan summary.
- Login supports a single form with username/email + password. Multi-step logins, CAPTCHA, SSO and 2FA are not supported.
- Content that changes on every visit (rotating banners, live data) can make tests flaky.
- **Read the "Not covered" list.** After every scan the tool prints what it saw but cannot test (CAPTCHAs, custom date pickers, inputs outside `<form>` tags, embedded iframes, hover-only menus, buttons no test clicks, forms skipped because they look destructive). The same list is shown in the HTML report and the generated suite's README, so a green run is never mistaken for full coverage.
- Typing boxes: only plain text boxes outside forms are used, and a box with nothing to recognise it by (no id, placeholder, aria-label or name) is skipped.
- Widgets are found by standard markup (`role=tab`, `aria-expanded`, `<details>`, class names like `carousel` / `pagination`). Custom-built widgets with none of those are missed. Menus that open only on hover are not tested.
- Logged-in forms come from the pages the scan could reach by links; only the first few per area are tested.
- A link that sends guests to a login page can fail the "nav link navigates" test.
- `--include-write-tests` only checks that the server doesn't crash (no 5xx); it does not prove create/update/delete works.

---

## Testing the tool itself

```bash
pip install -e .                 # once, from this folder
python -m pytest                 # everything: about 10 minutes, needs Chromium
python -m pytest -m "not integration"   # the fast tests only: a few seconds, no browser needed
```

- **tests/unit** and **tests/generator** check the logic with no browser: URL handling, plain-language errors, which side (guest / user / admin) a test belongs to, the safety rules (destructive forms are never submitted, nothing is sent unless asked), and the code the generator writes.
- **tests/integration** starts a small local test website (`tests/integration/site.py`), scans it, writes a suite, runs it, and checks it passes. It then breaks the site on purpose (dead tabs and carousel, a dead next-page link, a server error on a form) and checks that the right tests fail. It also checks that an unreachable site stops the run with one clear message.
- `.github/workflows/ci.yml` runs all of this on Windows and Linux for every push (fast tests on Python 3.10 and 3.14, browser tests on Python 3.12), and checks that the package builds and installs. It has not run yet: it starts working once the project is on GitHub, and the first Linux run may show things that only ever ran on Windows.

---

## Re-running Tests Later

```bash
cd my-client-tests
pytest            # all
pytest -m e2e     # browser only
pytest -m api     # HTTP only
pytest -m auth    # tests that log in (needs .env)
pytest --headed   # watch the browser
```
