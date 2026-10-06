<!--
TEMPLATE FOR THE PUBLISHER: this text is a plain-language starting point written by an AI assistant.
It is NOT legal advice and has not been reviewed by a lawyer. Before you share this tool with others,
(1) replace the [PLACEHOLDERS] below and (2) have a lawyer in your country review these Terms,
the Privacy Notice, and choose a software licence. This comment is hidden when the terms are shown to users.
-->
# Nes-Dev QA - Terms of Use

Publisher: nescafe-dev - Contact: leueilshem@gmail.com

By using this tool you agree to these terms. If you do not agree, do not use it.

## 1. What this tool does
Nes-Dev QA opens websites in an automated browser, records what it finds (pages, links, forms, network calls),
generates automated tests for them, and runs those tests.

## 2. You need permission
- Only test websites, applications and APIs that **you own**, or that you have **clear, written permission** to test.
- Testing systems without authorization can be illegal (for example under computer-misuse and anti-hacking laws),
  can breach the site's own terms, and can get your IP address blocked.
- Respect the target's rules: rate limits, robots/automation policies, maintenance windows, and any hosting-provider rules.

## 3. Be careful with live systems
- Prefer a **staging or test environment**. Tests drive a real browser and send real requests.
- `--include-write-tests` sends POST/PUT/PATCH/DELETE requests, which can create, change or delete data. Use it only on systems where that is acceptable.
- `--submit-forms` fills in and submits the forms it finds (contact, sign-up, newsletter, checkout...), which can send
  emails, create accounts or place orders. Use it only on systems where that is acceptable.
- The tool does not intentionally perform denial-of-service, password guessing, injection or exploitation, but any
  automated tool can have unexpected effects. You run it at your own risk.

## 4. Accounts and passwords
- Use dedicated **test accounts**, never personal accounts or real customers' accounts.
- Credentials you enter are saved **in plain text** in a `.env` file inside the generated test folder (on your computer).
  Keep that file private and do not commit or share it.

## 5. No professional advice, no guarantee
- The tool is provided **"as is" and "as available"**, without warranties of any kind, to the maximum extent allowed by law.
- Results can be wrong: tests can pass when something is broken (false negatives) or fail when nothing is wrong (false positives).
- The tool is a functional test generator. It is **not a security audit or certification**, and a clean result does not mean
  a site is secure. Do not rely on this tool alone for security, compliance or safety decisions.

## 6. Responsibility
- You are responsible for how you use the tool, for the targets you choose, and for following the laws and agreements that apply to you.
- To the maximum extent allowed by law, the publisher is not liable for any loss or damage arising from your use of the tool
  (including damage to a tested system, lost data, downtime, blocked access, or legal claims by third parties).
  Nothing in these terms limits liability that cannot be limited by law.
- You agree to compensate the publisher for claims brought by third parties that result from your unauthorized or unlawful use of the tool.

## 7. Changes
These terms may change. When they do, the tool asks you to accept the new version before it runs again.
