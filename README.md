# Job Application Agent v0.1

This is the first safe/deterministic layer of the job-application agent.

It DOES:
- keep fixed candidate facts in `candidate_profile.yaml`
- distinguish current work authorization from future-sponsorship questions
- route between explicitly approved resume variants
- use an LLM only when deterministic policy cannot answer
- stop on sensitive/high-risk questions
- log job hash, resume hash, question, answer, source, confidence, and review status
- support dry runs before browser automation

It DOES NOT:
- submit applications
- bypass CAPTCHA/MFA
- evade anti-bot systems
- invent experience or immigration facts

## 1. Windows setup

Open PowerShell inside this folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Open `.env` and put your API key:

```text
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-5.6-luna
```

Do not commit `.env`.

## 2. Put your two resumes in `resumes/`

Use exactly these names initially:

```text
resumes/resume_7_months.pdf
resumes/resume_4_plus_years.pdf
```

The 4+ year resume is disabled by default. Only set:

```yaml
eligible_for_auto_use: true
```

after every claim in that version is factually yours and defensible.

## 3. Edit candidate_profile.yaml

At minimum fill:

- legal_name
- preferred_name
- email
- phone
- LinkedIn
- GitHub
- work-authorization facts

Do not put passwords or API keys into this YAML.

## 4. Smoke test without spending API money

```powershell
python main.py init-db
python main.py route-resume --job-file samples/job.txt

python main.py answer `
  --question "Are you legally authorized to work in the United States?" `
  --no-llm
```

You should get a deterministic answer from `LOCKED_PROFILE`.

## 5. Test an LLM question

```powershell
python main.py answer `
  --question "Why are you interested in this backend software engineering role?" `
  --job-file samples/job.txt
```

## 6. Run the full sample

```powershell
python main.py dry-run `
  --job-file samples/job.txt `
  --questions-file samples/questions.json `
  --company "Sample Company" `
  --role "Backend Software Engineer" `
  --job-url "https://example.com/job/123"
```

Expected behavior:
- current US authorization -> deterministic
- sponsorship NOW -> deterministic
- sponsorship IN THE FUTURE -> manual review unless you explicitly lock a truthful value
- relocation -> deterministic
- "why interested" -> LLM
- salary -> manual review

## 7. Inspect exactly what was logged

```powershell
python inspect_log.py
```

The DB is:

```text
data/applications.db
```

## What to do in your first hour

### 0-15 minutes
- create the venv
- install requirements
- add API key
- run `python main.py init-db`

### 15-30 minutes
- copy both resumes into `resumes/`
- fill `candidate_profile.yaml`
- keep the experienced resume disabled unless fully verified

### 30-45 minutes
- paste one real job description into `samples/job.txt`
- replace `samples/questions.json` with 10-20 real questions from that application
- run `dry-run`

### 45-60 minutes
- inspect every answer
- fix incorrect rules in `candidate_profile.yaml`
- run again
- do NOT automate submission until the same set repeatedly produces correct answers

## Phase 0.2

Next add:
- verified experience/project fact database
- job eligibility filter
- question-memory/rule-learning
- resume tailoring from approved bullets only
- Playwright form reader/filler in `headless=False`
- screenshot before submission
- explicit submission gate
- company/application deduplication
- retry/idempotency rules
