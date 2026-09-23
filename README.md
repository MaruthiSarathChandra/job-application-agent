# Job Application Agent V2

A local-first job discovery, resume-tailoring, application-memory, and ATS automation system.

V2 can:
- discover jobs from public Greenhouse, Lever, and Workday career boards,
- extract career/job links from a PDF,
- persist and deduplicate jobs in SQLite,
- rank jobs against verified candidate skills and target roles,
- generate job-specific DOCX resumes from verified facts only,
- run Workday, Greenhouse, and Lever application adapters,
- reuse user-confirmed non-sensitive answers after repeated confirmation,
- store ATS passwords in the OS keyring instead of YAML/Git/logs,
- keep a local audit trail of application runs,
- pause for CAPTCHA/MFA/email verification and resume on the same browser page,
- stop at review by default, or submit only when `submission.mode: auto_if_safe` passes all safety gates.

It does **not** bypass CAPTCHA/MFA, invent experience, guess immigration/legal/compliance answers, or store plaintext passwords.

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

`candidate_profile.yaml`, `.env`, browser profiles, generated resumes, local DBs, and personal resumes are ignored by Git.

## 2. Fill candidate_profile.yaml

Use only truthful, defensible values.

Important sections:
- `candidate`
- `education`
- `application_defaults`
- `preferences.target_roles`
- `work_authorization`
- `verified_facts.skills`
- `resume_content`
- `application_questions`
- `submission.mode`

Keep unknown legal/compliance/immigration answers as `REVIEW`.

Example:

```yaml
submission:
  mode: manual
```

After live validation, you may explicitly change it to:

```yaml
submission:
  mode: auto_if_safe
```

Even in auto mode, unresolved legal/sensitive answers, validation errors, CAPTCHA/MFA/email verification, and protected review categories block automatic submission.

## 3. One-command V2 runner

### Company-career PDF

```powershell
python agent_v2.py `
  --pdf "companies.pdf" `
  --minimum-score 40 `
  --prepare-limit 50 `
  --apply-limit 10
```

The runner will:
1. extract career links,
2. expand public Greenhouse/Lever/Workday boards,
3. search Workday boards using up to three target roles from your profile,
4. deduplicate jobs,
5. rank them,
6. generate verified-fact DOCX resumes,
7. open the supported ATS queue,
8. pause only when manual review or verification is required.

### Greenhouse

```powershell
python agent_v2.py --greenhouse "company-token-or-board-url" --apply-limit 10
```

### Lever

```powershell
python agent_v2.py --lever "company-token-or-board-url" --apply-limit 10
```

### Workday

```powershell
python agent_v2.py `
  --workday "https://company.wd1.myworkdayjobs.com/CareerSite" `
  --apply-limit 10
```

### Prepare resumes only

```powershell
python agent_v2.py --pdf "companies.pdf" --prepare-only
```

### Use existing queued jobs only

```powershell
python agent_v2.py --apply-limit 10
```

## 4. Training / learned answers

When an application pauses for manual review, V2 snapshots the form before and after your edit.

Eligible non-sensitive changed answers can be stored locally. Reuse requires repeated confirmation. Passwords, OTPs, SSNs, financial identifiers, demographic data, immigration/sponsorship, salary, legal attestations, public-official conflicts, and similar high-risk answers are excluded from learned memory.

You can inspect memory behavior manually:

```powershell
python pipeline_cli.py recall `
  --question "Are you willing to relocate?" `
  --company "Example Company" `
  --ats workday
```

## 5. Pipeline-only commands

```powershell
python pipeline_cli.py pdf-pipeline --pdf "companies.pdf" --profile candidate_profile.yaml
python pipeline_cli.py greenhouse-pipeline --board company-token
python pipeline_cli.py lever-pipeline --site company-token
python pipeline_cli.py rank-db
python pipeline_cli.py prepare --rank-first
python pipeline_cli.py ready
python pipeline_cli.py list-jobs
```

## 6. Resume generation rules

The DOCX builder uses only:
- `resume_content.experience`
- `resume_content.projects`
- `verified_facts.skills`
- candidate contact information
- education

It can reorder/rank verified bullets and skills for a job, but it does not invent employers, dates, metrics, technologies, or accomplishments.

Generated resumes are stored under:

```text
data/generated_resumes/
```

and are ignored by Git.

## 7. Credentials and verification

ATS passwords are stored through Python `keyring`, which uses the operating-system credential store where supported.

The agent never logs the password itself.

If the site requests CAPTCHA, MFA, OTP, or email verification, the browser remains open and the agent waits for you. After you complete the verification and press Enter in the terminal, V2 resumes the same application page instead of starting the job over.

## 8. Application queue and audit trail

Runtime databases:

```text
data/jobs.db
data/application_memory.db
data/application_audit.db
```

These remain local and are ignored by Git.

Application statuses include:
- `not_started`
- `in_progress`
- `review`
- `verification_required`
- `account_review`
- `ready_for_review`
- `submitted`
- `error`

Previously interrupted review/verification jobs can be resumed from the queue.

## 9. Tests

```powershell
python -m compileall agent browser credentials learning pipeline resume_builder pipeline_cli.py agent_v2.py main.py
python -m unittest discover -s tests -v
```

GitHub Actions runs the same compile and unit-test checks on V2/main changes.

## Current supported ATS scope

- Greenhouse: discovery + application adapter
- Lever: discovery + application adapter
- Workday: public board discovery + multi-step application adapter
- LinkedIn: not used for authenticated scraping or anti-bot bypass; use employer/ATS destination links when available
- Other career sites: stored as discovery leads until a supported ATS or future site adapter is available

The system is designed to scale the discovery and preparation pipeline while keeping identity, legal, compliance, and authentication decisions under explicit user control.
