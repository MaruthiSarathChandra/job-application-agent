from __future__ import annotations

import argparse
import copy
import os
import tempfile
from pathlib import Path

import yaml

from agent.profile import CandidateProfile
from browser.queue_runner import run_queue
from pipeline.job_sources import (
    expand_career_urls,
    expand_pdf_sources,
    fetch_greenhouse_jobs,
    fetch_lever_jobs,
)
from pipeline.job_store import JobStore
from pipeline.orchestrator import PipelineOrchestrator


def _workday_terms(profile):
    roles = profile.get("preferences.target_roles", []) or []
    if isinstance(roles, str):
        roles = [roles]

    terms = []
    seen = set()
    for role in roles:
        value = " ".join(str(role or "").strip().split())
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        terms.append(value)
        if len(terms) >= 3:
            break

    if not terms:
        terms = ["Software Engineer", "Backend Engineer", "Java"]
    return terms


def _discover(args, profile):
    jobs = []
    warnings = []
    workday_terms = _workday_terms(profile)

    for pdf in args.pdf or []:
        try:
            found, errors = expand_pdf_sources(
                pdf,
                company=args.company or "",
                timeout=args.timeout,
                workday_search_terms=workday_terms,
                workday_max_jobs_per_term=args.workday_max_jobs,
            )
            jobs.extend(found)
            warnings.extend(errors)
        except Exception as exc:
            warnings.append({"source": "pdf", "url": pdf, "error": str(exc)})

    for board in args.greenhouse or []:
        try:
            jobs.extend(
                fetch_greenhouse_jobs(
                    board,
                    company=args.company or "",
                    timeout=args.timeout,
                )
            )
        except Exception as exc:
            warnings.append({"source": "greenhouse", "url": board, "error": str(exc)})

    for site in args.lever or []:
        try:
            jobs.extend(
                fetch_lever_jobs(
                    site,
                    company=args.company or "",
                    timeout=args.timeout,
                )
            )
        except Exception as exc:
            warnings.append({"source": "lever", "url": site, "error": str(exc)})

    urls = list(args.workday or []) + list(args.source_url or [])
    if urls:
        found, errors = expand_career_urls(
            urls,
            company=args.company or "",
            timeout=args.timeout,
            workday_search_terms=workday_terms,
            workday_max_jobs_per_term=args.workday_max_jobs,
        )
        jobs.extend(found)
        warnings.extend(errors)

    return jobs, warnings


def _prepare(profile, jobs, args):
    store = JobStore(args.db)
    try:
        orchestrator = PipelineOrchestrator(profile, store)
        ingested_ids = []
        if jobs:
            ingested_ids = orchestrator.ingest(jobs)

        # Rediscovery is also our crash-recovery boundary. An older code version
        # may have left a job in adapter_missing, while an interrupted browser
        # run can leave application_status=in_progress forever. Both states must
        # be made resumable without asking the user to edit SQLite by hand.
        for job_id in ingested_ids:
            row = store.get(str(job_id))
            if row is None:
                continue
            status = str(row["application_status"] or "").strip().lower()
            if status == "adapter_missing":
                store.set_application_status(str(job_id), "not_started")
            elif status == "in_progress":
                # Preserve the fact that this may be a partially completed
                # application. The browser profile/session can resume it, and
                # review is already part of the default resumable queue.
                store.set_application_status(str(job_id), "review")

        ranked = orchestrator.rank_all(limit=args.scan_limit)
        prepared = orchestrator.prepare_resumes(
            minimum_score=args.minimum_score,
            output_dir=args.output_dir,
            limit=args.prepare_limit,
        )
    finally:
        store.close()

    strong = [item for item in ranked if item.score >= args.minimum_score]
    return ranked, strong, prepared


def _runtime_profile(original_path: Path, unattended: bool = False, job_source: str = ""):
    """
    Build an ephemeral profile for one run when command-line execution policy
    differs from the persistent candidate profile.

    The temporary file is deleted after the run. This lets unattended mode force
    auto_if_safe submission without rewriting the user's real YAML and lets a
    one-off truthful source (LinkedIn, Indeed, etc.) be supplied per application.
    """
    profile = CandidateProfile(str(original_path))
    data = copy.deepcopy(profile.data)
    changed = False

    if unattended:
        submission = data.setdefault("submission", {})
        submission["mode"] = "auto_if_safe"
        changed = True

    source = str(job_source or "").strip()
    if source:
        defaults = data.setdefault("application_defaults", {})
        defaults["job_source"] = source
        changed = True

    if not changed:
        return original_path, profile, None

    fd, temp_name = tempfile.mkstemp(prefix="job_agent_runtime_", suffix=".yaml")
    os.close(fd)
    temp_path = Path(temp_name)
    temp_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return temp_path, CandidateProfile(str(temp_path)), temp_path


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Job Application Agent V2: discover jobs, rank them, build verified-fact "
            "DOCX resumes, and run supported ATS applications."
        )
    )
    parser.add_argument("--profile", default="candidate_profile.yaml")
    parser.add_argument("--db", default="data/jobs.db")
    parser.add_argument("--audit-db", default="data/application_audit.db")
    parser.add_argument("--browser-profile", default="data/browser_profile_v2")
    parser.add_argument("--output-dir", default="data/generated_resumes")

    parser.add_argument(
        "--pdf",
        action="append",
        default=[],
        help="Company-career PDF. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--greenhouse",
        action="append",
        default=[],
        help="Greenhouse board token/URL. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--lever",
        action="append",
        default=[],
        help="Lever site token/URL. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--workday",
        action="append",
        default=[],
        help=(
            "Public Workday career-site/job URL. Board URLs are searched using "
            "up to three target roles from the candidate profile. Can be repeated."
        ),
    )
    parser.add_argument(
        "--source-url",
        action="append",
        default=[],
        help=(
            "Direct public career/job URL. Greenhouse/Lever/Workday board URLs are "
            "expanded where supported. Can be repeated."
        ),
    )
    parser.add_argument("--company", default="")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument(
        "--job-source",
        default="",
        help=(
            "Truthful source for this run, e.g. 'LinkedIn Job Post' or 'Indeed'. "
            "Overrides application_defaults.job_source only in an ephemeral runtime profile."
        ),
    )
    parser.add_argument(
        "--workday-max-jobs",
        type=int,
        default=75,
        help="Maximum Workday jobs fetched per target-role search term.",
    )

    parser.add_argument("--minimum-score", type=float, default=40.0)
    parser.add_argument("--scan-limit", type=int, default=10000)
    parser.add_argument("--prepare-limit", type=int, default=100)
    parser.add_argument("--apply-limit", type=int, default=10)
    parser.add_argument("--max-manual-cycles", type=int, default=4)
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Discover/rank/generate resumes but do not open the browser application queue.",
    )
    parser.add_argument(
        "--continue-on-review",
        action="store_true",
        help="Record review-required jobs and move on instead of pausing for user input.",
    )
    parser.add_argument(
        "--unattended",
        action="store_true",
        help=(
            "Run without interactive ENTER prompts. Forces submission.mode=auto_if_safe "
            "for this run, auto-submits only when all safe-submit checks pass, and records/"
            "skips applications that still require CAPTCHA, MFA, legal consent, or another "
            "unresolved review-required answer."
        ),
    )
    return parser


def main():
    args = build_parser().parse_args()
    original_profile_path = Path(args.profile)
    if not original_profile_path.exists():
        raise SystemExit(
            f"Profile not found: {original_profile_path}. Copy candidate_profile.example.yaml "
            "to candidate_profile.yaml and fill only truthful values."
        )

    runtime_temp = None
    try:
        profile_path, profile, runtime_temp = _runtime_profile(
            original_profile_path,
            unattended=bool(args.unattended),
            job_source=args.job_source,
        )

        jobs, warnings = _discover(args, profile)
        ranked, strong, prepared = _prepare(profile, jobs, args)

        prepared_ok = sum(1 for item in prepared if item.get("resume_path"))
        print("\nV2 PIPELINE")
        print(f"Discovered this run: {len(jobs)}")
        print(f"Ranked in DB:        {len(ranked)}")
        print(f"Qualified:           {len(strong)}")
        print(f"Resumes prepared:    {prepared_ok}")
        print(f"Run mode:            {'unattended' if args.unattended else 'interactive'}")

        if args.unattended:
            print(
                "Unattended policy: safe deterministic/profile-backed answers may be submitted; "
                "unresolved CAPTCHA/MFA/legal/review blockers are recorded and skipped without pausing."
            )

        if warnings:
            print(f"Warnings:            {len(warnings)}")
            for item in warnings[:25]:
                print(f" - {item.get('source')}: {item.get('url')} -> {item.get('error')}")

        if args.prepare_only:
            print("\nPrepare-only mode complete.")
            return

        run_queue(
            profile_path=str(profile_path),
            db_path=args.db,
            audit_db=args.audit_db,
            browser_profile=args.browser_profile,
            minimum_score=args.minimum_score,
            limit=args.apply_limit,
            stop_on_review=not (args.continue_on_review or args.unattended),
            max_manual_cycles=max(0, int(args.max_manual_cycles)),
        )
    finally:
        if runtime_temp is not None:
            try:
                runtime_temp.unlink(missing_ok=True)
            except Exception:
                pass


if __name__ == "__main__":
    main()
