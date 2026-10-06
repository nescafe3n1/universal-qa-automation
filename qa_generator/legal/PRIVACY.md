<!--
TEMPLATE FOR THE PUBLISHER: not legal advice; have it reviewed by a lawyer before distributing the tool.
If you later add telemetry, ZAP, cloud features or any network call to your own servers, update this notice first.
-->
# Nes-Dev QA - Privacy Notice

Publisher: nescafe-dev - Contact: leueilshem@gmail.com

**Short version: the tool runs entirely on your computer. It has no analytics or telemetry, needs no account,
and sends nothing to the publisher.**

## What the tool connects to
- **The website you choose to test.** The tool loads its pages in a real browser, like a visitor would. Because of that, the
  site's own third-party scripts (analytics, ads, chat widgets, fonts) may also load and contact their own servers. That is
  the target site's behavior, not something this tool adds.
- Nothing else. Generated HTML reports and the web interface load no external resources.
- **The local web agent** (`run-playwright-ui`), if you use the web interface, listens only on your own computer (`127.0.0.1`). It is not reachable from other computers, and it refuses requests from other websites.
- Setup steps you run yourself (for example `pip install` and `playwright install`) download software from their own providers under their own terms.

## What the tool stores, and where
| Data | Where | Notes |
| :--- | :--- | :--- |
| Your acceptance of these terms (version, date/time) | `~/.3am-automation/accepted_terms.json` | Local only |
| Test accounts you enter (username and password) | `.env` in the generated test folder | **Plain text.** Keep private, never commit |
| Run history (date/time, target address, mode, suite name, result counts; never passwords) | `~/.3am-automation/runs.json` | Local only; written by the web agent |
| Scan results: URLs, page titles, link texts, form field names | Inside generated test files, `suite_config.json` and `scan.json` | Taken from the tested site |
| Test results and reports | `reports/` in the generated test folder | Include page content and the usernames you used |

Passwords typed at the prompt are hidden on screen and are not written to reports. Passwords you pass on the command line (`--password`, `--admin-password`) can be saved by your shell's history; prefer the prompt on shared computers. Passwords entered in the web interface go only to the local agent, which hands them to the test tool through environment variables (not the command line) and hides them in the output it shows you; the tool then saves them in the suite's `.env` file as described above.

## Sharing
Generated folders can contain credentials (`.env`) and details about the tested site. Review a folder before sharing it
or uploading it anywhere. If a tested site contains personal data of other people, handle the reports accordingly.

## Your control
Delete a generated folder to remove its data. Delete `~/.3am-automation/` to remove the acceptance record and the run history.
(You will be asked to accept the terms again.) Set the environment variable `QA_GENERATOR_HOME` to store them elsewhere.
