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

- Greenhouse public board ingestion.
- Extract career/job URLs from a PDF.
- Deterministic ranking using target roles + verified skills.
- Tailored DOCX generated only from `resume_content` and verified skills.
- Deduplicate jobs by canonical URL/external ID.

### v2.1 — application memory / training mode

- Record user-confirmed non-sensitive form answers.
- Normalize question wording.
- Reuse an answer automatically only after enough confirmations.
- Company/ATS-specific mappings take priority over global mappings.
- Never remember passwords, OTPs, SSNs, financial identifiers or sensitive demographic answers.

### v2.2 — account manager

- Detect sign-in vs create-account pages.
- Fill candidate email automatically.
- Create a random site-specific password when necessary.
- Store password in Windows Credential Manager/keyring, never YAML/logs.
- Pause for CAPTCHA/MFA/OTP verification.
- Resume automatically after the user confirms verification is complete.

### v2.3 — ATS adapters

Adapters share a common contract but keep site-specific selectors isolated:

- Workday
- Greenhouse
- Lever
- company-specific career pages

LinkedIn is treated primarily as a discovery source. Authenticated scraping or anti-bot bypass is not part of the design; where direct automation is unreliable, the pipeline follows the employer's application URL and completes the destination ATS.

### v2.4 — safe submit

Modes:

- `manual`: always stop at Review.
- `auto_if_safe`: click Submit only when all required fields are filled, no validation errors remain, and no legal/sensitive/review-required answer is unresolved.

CAPTCHA, MFA/OTP and legal attestations remain manual.

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

## Current v2 branch

`v2/job-pipeline`

Implemented foundation:

- `pipeline/job_sources.py`
- `pipeline/job_matcher.py`
- `pipeline/models.py`
- `pipeline_cli.py`
- `resume_builder/docx_resume.py`
- `learning/application_memory.py`
- `credentials/store.py`
- `agent/submission_policy.py`

Next engineering work is to connect these components to the browser orchestrator and add Greenhouse/Lever adapters after the Workday flow is stable.
