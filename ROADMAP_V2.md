# Job Application Agent v2 Roadmap

## Goal

Turn the current single-application Workday runner into a pipeline that can:

1. discover jobs from approved/public sources and user-supplied company career PDFs,
2. rank jobs against verified candidate facts,
3. generate a tailored DOCX without inventing experience,
4. create or reuse ATS accounts with passwords stored in the OS keyring,
5. complete supported ATS applications,
6. learn reusable question/answer mappings from user-confirmed applications,
7. keep CAPTCHA, MFA/OTP, sensitive disclosures and legal attestations behind a manual gate,
8. submit automatically only when `submission.mode=auto_if_safe` and the submission policy has no blockers.

## Version plan

### v2.0 — discovery + ranking + resume generation

Implemented:

- Greenhouse public board ingestion.
- Lever public postings ingestion.
- Extract career/job URLs from a PDF.
- Expand Greenhouse/Lever board links found in a PDF into individual jobs.
- Persistent SQLite job queue with canonical URL/external-ID deduplication.
- ATS detection/routing.
- Deterministic ranking using target roles + verified skills.
- Tailored DOCX generated only from `resume_content` and verified skills.
- Persistent match score, pipeline status, resume path and application status.

### v2.1 — application memory / training mode

Implemented foundation:

- Record user-confirmed non-sensitive form answers.
- Exact normalized question reuse.
- Conservative fuzzy reuse after repeated confirmation.
- Company/ATS-specific mappings take priority.
- Conflicting memories fail closed.
- Passwords, OTPs, SSNs, financial identifiers, immigration, salary,
  legal/conflict and sensitive demographic answers are excluded from memory.
- `ApplicationEngine` consults locked profile facts first, confirmed memory second,
  and the LLM only after those layers.

Still to add:

- automatic capture of answers after the user manually completes a review page,
- canonical question categories shared across ATS adapters,
- memory review/edit CLI.

### v2.2 — account manager

Foundation implemented:

- random site-specific password generation,
- OS keyring/Windows Credential Manager storage,
- no plaintext password storage in YAML/logs/Git.

Still to add:

- Workday sign-in/create-account state machine,
- email verification handoff,
- resume after the user completes CAPTCHA/MFA/OTP,
- account reuse across applications for the same ATS tenant.

### v2.3 — ATS adapters

Implemented:

- common `ATSAdapter` contract,
- Greenhouse form adapter,
- Lever form adapter,
- generic non-Workday custom-question filler,
- multi-ATS queue runner,
- Workday routing wrapper while the existing deterministic Workday runner is
  refactored behind the common adapter contract.

Next:

- refactor Workday runner into `WorkdayAdapter`,
- add account creation/login manager,
- add validation/evidence capture shared by every adapter,
- add company-specific fallback adapter only after generic ATS adapters are stable.

LinkedIn remains primarily a discovery source. Authenticated scraping or anti-bot
bypass is not part of the design; where direct automation is unreliable, the
pipeline follows the employer's application URL and completes the destination ATS.

### v2.4 — safe submit

Modes:

- `manual`: always stop for final review.
- `auto_if_safe`: click Submit only when all required fields are filled, no
  validation errors remain, and no legal/sensitive/review-required answer is unresolved.

The submission policy and adapter-level gate now exist. `manual` remains the
recommended/default mode while adapters are being validated.

CAPTCHA, MFA/OTP and legal attestations remain manual.

## Persistent V2 flow

```text
Career PDF / Greenhouse / Lever / discovery links
                     |
                     v
                JobStore SQLite
                     |
             dedupe + ATS detect
                     |
                     v
                 rank jobs
                     |
                     v
          verified DOCX resume builder
                     |
                     v
              resume_ready queue
                     |
        +------------+------------+
        |            |            |
   Greenhouse      Lever       Workday
     adapter        adapter    deterministic runner
        |            |            |
        +------------+------------+
                     |
               safe submit gate
```

## Candidate profile additions

Local `candidate_profile.yaml` can add:

```yaml
preferences:
  target_roles:
    - Backend Software Engineer
    - Software Engineer
    - Java Developer

submission:
  mode: manual   # later: auto_if_safe

resume_content:
  headline: Software Engineer
  summary: "Only verified summary text"
  experience:
    - employer: Example
      title: Software Engineer
      location: Kansas City, Missouri
      dates: Feb 2026 - Present
      bullets:
        - text: "Verified bullet text"
          tags: [Java, Spring Boot, REST APIs]
  projects:
    - name: PencilDrive
      tech: Java, Spring Boot, MySQL
      bullets:
        - text: "Verified project bullet"
          tags: [Spring Security, JWT, JPA]
```

`candidate_profile.yaml` stays local and ignored by Git.

## Useful commands

```powershell
# Pull jobs from Greenhouse, rank them, and generate resumes for strong matches
python pipeline_cli.py greenhouse-pipeline `
  --board COMPANY_BOARD_TOKEN `
  --company "Company Name" `
  --minimum-score 40

# Same for Lever
python pipeline_cli.py lever-pipeline `
  --site COMPANY_SITE_TOKEN `
  --company "Company Name" `
  --minimum-score 40

# Expand a company-career PDF, rank what can be discovered publicly,
# and generate resumes
python pipeline_cli.py pdf-pipeline `
  --pdf companies.pdf `
  --minimum-score 40

# Inspect prepared jobs
python pipeline_cli.py ready

# Run the current multi-ATS browser queue
python browser/queue_runner.py --minimum-score 40
```

## Current branch

`v2/job-pipeline`

Primary next milestone: **V2 account/login manager + WorkdayAdapter refactor**, then
real-world testing across Greenhouse, Lever and Workday applications.
