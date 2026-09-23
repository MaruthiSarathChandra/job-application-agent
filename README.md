# Job Application Agent V2

A local-first job discovery, resume-tailoring, application-memory, and ATS automation system.

V2 can:
- discover jobs from public Greenhouse, Lever, and Workday career boards,
- accept direct Workday, Greenhouse, Lever, BrassRing, Avature, and ordinary career-site URLs,
- extract career/job links from a PDF,
- persist and deduplicate jobs in SQLite,
- rank jobs against verified candidate skills and target roles,
- generate job-specific DOCX resumes from verified facts only,
- run dedicated Workday, Greenhouse, Lever, BrassRing, and Avature application adapters,
- use a conservative generic career-site adapter when no dedicated ATS adapter exists,
- follow Apply controls, new tabs/windows, sign-in/create-account flows, resume upload, multi-step forms, review, and submission confirmation,
- reuse user-confirmed non-sensitive answers after repeated confirmation,
- store ATS passwords in the OS keyring instead of YAML/Git/logs,
- keep a local audit trail of application runs,
- optionally read Gmail through local OAuth for email OTP/verification links while never logging or learning the verification secret,
- stop at review by default, or submit only when `submission.mode: auto_if_safe` passes all safety gates.

It does **not** bypass CAPTCHA/non-email MFA, invent experience, guess immigration/legal/compliance answers, or store plaintext passwords/OTPs.

## 1. Windows setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
Copy-Item .env.example .env
Copy-Item candidate_profile.example.yaml candidate_profile.yaml
```

Put your OpenAI key only in `.env`:

```text
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-5.6-luna
```

`candidate_profile.yaml`, `.env`, browser profiles, generated resumes, local DBs, Gmail OAuth tokens, OAuth client secrets, and personal resumes are ignored by Git.

## 2. Fill candidate_profile.yaml

Use only truthful, defensible values. Important sections include `candidate`, `education`, `application_defaults`, `preferences.target_roles`, `work_authorization`, `eligibility`, `verified_facts.skills`, `resume_content`, `application_questions`, `email_verification`, and `submission.mode`.

Keep unknown legal/compliance/immigration answers as `REVIEW`.

```yaml
submission:
  mode: manual
```

After live validation, you may explicitly change it to:

```yaml
submission:
  mode: auto_if_safe
```

Even in auto mode, unresolved legal/sensitive answers, validation errors, CAPTCHA/non-email MFA, and protected review categories block automatic submission.

## 3. One-command runner

Direct job URL:

```powershell
python agent_v2.py `
  --source-url "PASTE_JOB_URL" `
  --minimum-score 0 `
  --prepare-limit 1 `
  --apply-limit 1
```

The runner discovers/persists the job, ranks it, reuses or generates a verified-fact resume, recovers jobs previously marked `adapter_missing` after an adapter upgrade, opens Chromium, and drives the application state machine.

Company-career PDF:

```powershell
python agent_v2.py `
  --pdf "companies.pdf" `
  --minimum-score 40 `
  --prepare-limit 50 `
  --apply-limit 10
```

Greenhouse:

```powershell
python agent_v2.py --greenhouse "company-token-or-board-url" --apply-limit 10
```

Lever:

```powershell
python agent_v2.py --lever "company-token-or-board-url" --apply-limit 10
```

Workday:

```powershell
python agent_v2.py `
  --workday "https://company.wd1.myworkdayjobs.com/CareerSite" `
  --apply-limit 10
```

Prepare only:

```powershell
python agent_v2.py --pdf "companies.pdf" --prepare-only
```

Use existing queued jobs only:

```powershell
python agent_v2.py --apply-limit 10
```

## 4. Real-world application state machine

Dedicated and generic adapters follow the same conservative flow:

```text
job page
  -> eligibility/preflight where supported
  -> Apply / Start Application
  -> follow popup/new tab if created
  -> sign in OR create candidate account
  -> email/verification step
  -> resume/profile
  -> multi-step questions
  -> final review
  -> submit only when policy allows
  -> detect submission confirmation
```

Required terms/legal checkboxes remain review-gated. CAPTCHA and non-email MFA are never bypassed.

## 5. Gmail verification automation

Default behavior is manual:

```yaml
email_verification:
  mode: manual
```

Optional Gmail OAuth mode:

```yaml
email_verification:
  mode: gmail_api
  gmail:
    client_secret_file: "secrets/gmail_oauth_client.json"
    token_dir: "data/gmail_tokens"
    poll_seconds: 60
    trusted_link_domains: []
```

For `gmail_api`, create a Google OAuth Desktop client, download its JSON locally as `secrets/gmail_oauth_client.json`, and never commit it. The first run for each mailbox opens Google's consent flow. Tokens are kept under `data/gmail_tokens/` and are ignored by Git.

The verifier uses Gmail readonly access. OTP/code values are kept only in memory long enough to fill the page and are not written to logs, the application-memory database, YAML, or Git. Verification links auto-open only when the destination matches the current career/ATS domain, a known ATS family, or a domain you explicitly add to `trusted_link_domains`.

For multiple truthful resume/email identities, use separate local profile files and run with `--profile`. This keeps emails, resumes, and verified work history isolated instead of hardcoding personal addresses into the repository.

The ChatGPT Gmail connector and the local Python agent are separate authorization paths: connecting Gmail in ChatGPT does not automatically grant the local Playwright process mailbox access. The local agent uses the OAuth configuration above.

## 6. Training / learned answers

When an application pauses for manual review, V2 snapshots the form before and after your edit. Eligible non-sensitive changed answers can be stored locally. Reuse requires repeated confirmation.

Passwords, OTPs, SSNs, financial identifiers, demographic data, immigration/sponsorship, salary, legal attestations, public-official conflicts, and similar high-risk answers are excluded from learned memory.

```powershell
python pipeline_cli.py recall `
  --question "Are you willing to relocate?" `
  --company "Example Company" `
  --ats workday
```

## 7. Resume generation rules

The DOCX builder uses verified profile/resume content only. It can reorder/rank verified bullets and skills for a job, but it does not invent employers, dates, experience length, metrics, technologies, work authorization, or accomplishments.

Generated resumes are stored under `data/generated_resumes/` and ignored by Git.

## 8. Credentials and privacy

ATS passwords are stored through Python `keyring`, using the operating-system credential store where supported. Browser sessions live under the ignored browser-profile directory. Candidate profiles, Gmail OAuth secrets/tokens, generated resumes, and SQLite databases remain local.

## 9. Application queue and audit trail

Runtime databases:

```text
data/jobs.db
data/application_memory.db
data/application_audit.db
```

Application statuses include `not_started`, `in_progress`, `review`, `verification_required`, `account_review`, `ready_for_review`, `submitted`, `ineligible`, `closed`, `already_applied`, `adapter_missing`, and `error`.

Previously interrupted review/verification jobs can be resumed. Jobs previously marked `adapter_missing` are automatically recovered when the new code now recognizes the source.

## 10. Tests and production validation

```powershell
python -m compileall agent browser credentials learning pipeline resume_builder pipeline_cli.py agent_v2.py main.py
python -m unittest discover -s tests -v
```

GitHub Actions runs compile and unit-test checks on V2/main changes.

CI validates syntax, deterministic state logic, parsers, routing, queue recovery, and safety rules. A live ATS still has to be validated from the local Chromium session because the CI runner does not possess your browser session, candidate identity, mailbox authorization, or the employer site's interactive state. Live failures should be treated as adapter traces to patch, not as reasons to delete local application state.

## Current ATS scope

- Greenhouse: discovery + application adapter
- Lever: discovery + application adapter
- Workday: public board discovery + multi-step application adapter
- BrassRing: application adapter, popup/new-tab handling, eligibility preflight
- Avature: application adapter, including MetLife-style deep links
- Other public career sites: conservative generic application adapter
- LinkedIn: no authenticated scraping or anti-bot bypass; use the employer/ATS destination URL

The system is designed to automate repetitive application mechanics while keeping identity, factual resume content, legal/compliance answers, CAPTCHA, and non-email MFA under explicit truthful controls.
