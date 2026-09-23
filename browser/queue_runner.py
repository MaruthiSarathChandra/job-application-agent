from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from agent.profile import CandidateProfile
from browser.adapters import ApplicationContext, get_adapter
from browser.submission_detector import detect_submission_confirmation
from learning.application_memory import ApplicationMemory
from learning.review_capture import ReviewCapture
from pipeline.application_audit import ApplicationAudit
from pipeline.job_store import JobStore


DEFAULT_BROWSER_PROFILE = "data/browser_profile_v2"
DEFAULT_AUDIT_DB = "data/application_audit.db"
DEFAULT_RESUME_STATUSES = (
    "not_started",
    "review",
    "verification_required",
    "account_review",
    "error",
    "ready_for_review",
)

MANUAL_STATES = {
    "review",
    "verification_required",
    "account_review",
    "ready_for_review",
}


def _submission_mode(profile) -> str:
    return str(profile.get("submission.mode", "manual") or "manual").strip().lower()


def _result_status(result) -> str:
    if result.submitted:
        return "submitted"
    if result.status in {
        "ready_for_review",
        "verification_required",
        "account_review",
        "review",
        "error",
    }:
        return result.status
    if result.review_required:
        return "review"
    return result.status or "unknown"


def _manual_prompt(status: str):
    if status == "verification_required":
        print(
            "\nVerification is intentionally manual. Complete CAPTCHA/MFA/email "
            "verification in the browser, then return here."
        )
    elif status == "account_review":
        print(
            "\nThe ATS account page requires your review. Complete any terms, "
            "existing-account recovery, or other account-only step in the browser."
        )
    elif status == "ready_for_review":
        print(
            "\nThe application is ready for final review. Check the complete form. "
            "In manual submission mode, click Submit yourself if it is correct."
        )
    else:
        print(
            "\nComplete only the review-required fields in the browser. The trainer "
            "will learn eligible non-sensitive answers changed by you."
        )


def _result_payload(job_id, run_id, adapter_name, status, result):
    return {
        "job_id": job_id,
        "run_id": run_id,
        "ats": adapter_name,
        "status": status,
        "submitted": bool(result.submitted),
        "message": result.message,
        "blockers": result.blockers,
    }


def _blocker_fingerprint(result) -> str:
    blockers = result.blockers or []
    normalized = []
    for item in blockers:
        if not isinstance(item, dict):
            normalized.append(str(item))
            continue
        normalized.append(
            "|".join(
                str(item.get(key) or "").strip().lower()
                for key in ("category", "reason", "question", "label")
            )
        )
    return json.dumps(
        {
            "status": str(result.status or "").lower(),
            "message": str(result.message or "").strip().lower(),
            "blockers": sorted(normalized),
        },
        sort_keys=True,
    )


def run_queue(
    profile_path: str,
    db_path: str,
    audit_db: str,
    browser_profile: str,
    minimum_score: float,
    limit: int,
    stop_on_review: bool = True,
    statuses=DEFAULT_RESUME_STATUSES,
    max_manual_cycles: int = 4,
):
    profile = CandidateProfile(profile_path)
    store = JobStore(db_path)
    audit = ApplicationAudit(audit_db)
    mode = _submission_mode(profile)

    rows = store.list_application_queue(
        minimum_score=minimum_score,
        statuses=statuses,
        limit=limit,
    )

    if not rows:
        print("No resume-ready jobs are currently queued for the requested statuses.")
        audit.close()
        store.close()
        return

    print(f"Queued jobs: {len(rows)}")
    print(f"Submission mode: {mode}")
    print(f"Queue statuses: {', '.join(statuses)}")

    results = []
    memory = ApplicationMemory()
    trainer = ReviewCapture()

    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(Path(browser_profile).resolve()),
                headless=False,
                viewport={"width": 1400, "height": 900},
            )

            page = context.pages[-1] if context.pages else context.new_page()

            for row in rows:
                job_id = str(row["job_id"])
                job = store.row_to_job(row)
                adapter = get_adapter(job)

                if adapter is None:
                    store.set_application_status(job_id, "adapter_missing")
                    payload = {
                        "job_id": job_id,
                        "status": "adapter_missing",
                        "ats": row["ats"],
                        "url": job.url,
                    }
                    results.append(payload)
                    print(json.dumps(payload, indent=2))
                    continue

                application = ApplicationContext(
                    job_id=job_id,
                    job=job,
                    resume_path=row["resume_path"],
                    company=job.company,
                    role=job.title,
                    submission_mode=mode,
                    metadata={
                        "match_score": row["match_score"],
                        "previous_application_status": row["application_status"],
                        "resume_current_page": False,
                    },
                )

                print("\n" + "=" * 78)
                print(
                    f"JOB {job_id} | {adapter.name} | {job.company} | {job.title} "
                    f"| previous={row['application_status']}"
                )
                print(job.url)
                print("=" * 78)

                run_id = audit.begin_run(
                    job_id=job_id,
                    ats=adapter.name,
                    company=job.company,
                    role=job.title,
                    job_url=job.url,
                    resume_path=row["resume_path"],
                    submission_mode=mode,
                )
                audit.event(
                    run_id,
                    "start",
                    {
                        "match_score": row["match_score"],
                        "previous_application_status": row["application_status"],
                    },
                )

                store.set_application_status(job_id, "in_progress")
                final_result = None
                final_status = "error"
                previous_manual_fingerprint = None
                previous_manual_learned = None

                for manual_cycle in range(max_manual_cycles + 1):
                    try:
                        result = adapter.run(page, profile, application)
                    except Exception as exc:
                        final_status = "error"
                        store.set_error(job_id, str(exc), status="application_error")
                        audit.event(
                            run_id,
                            "adapter_exception",
                            {"cycle": manual_cycle, "error": str(exc)},
                        )
                        final_result = None
                        break

                    status = _result_status(result)
                    final_result = result
                    final_status = status

                    audit.event(
                        run_id,
                        "adapter_result",
                        {
                            "cycle": manual_cycle,
                            "status": status,
                            "submitted": result.submitted,
                            "message": result.message,
                            "blocker_count": len(result.blockers or []),
                        },
                    )

                    if result.submitted or status == "submitted":
                        final_status = "submitted"
                        break

                    if status not in MANUAL_STATES:
                        break

                    if not stop_on_review:
                        break

                    current_fingerprint = _blocker_fingerprint(result)
                    if (
                        previous_manual_fingerprint is not None
                        and current_fingerprint == previous_manual_fingerprint
                        and previous_manual_learned == 0
                    ):
                        print(
                            "\nNo progress detected: the same blocker returned after the "
                            "previous manual step, so the agent will stop instead of asking "
                            "you to repeat the same action."
                        )
                        audit.event(
                            run_id,
                            "manual_review_no_progress",
                            {"cycle": manual_cycle, "status": status},
                        )
                        break

                    before = trainer.capture(page)
                    _manual_prompt(status)
                    input("Press ENTER here after you are finished with this manual step...")
                    after = trainer.capture(page)

                    learned = trainer.remember_changes(
                        before,
                        after,
                        memory=memory,
                        company=job.company,
                        ats=adapter.name,
                    )

                    audit.event(
                        run_id,
                        "manual_review_completed",
                        {
                            "cycle": manual_cycle,
                            "status": status,
                            "learned_answer_count": len(learned),
                            "learned_questions": [item["question"] for item in learned],
                        },
                    )

                    if learned:
                        print(f"Learned {len(learned)} confirmed non-sensitive answer(s):")
                        for item in learned:
                            print(f" - {item['question'][:100]} -> {item['answer']}")
                    else:
                        print("No eligible answer changes were stored from this manual step.")

                    if detect_submission_confirmation(page):
                        result.submitted = True
                        result.status = "submitted"
                        result.review_required = False
                        result.message = "Submission confirmation detected after manual review."
                        final_result = result
                        final_status = "submitted"
                        break

                    if status == "ready_for_review":
                        final_status = "ready_for_review"
                        break

                    if manual_cycle >= max_manual_cycles:
                        final_status = status
                        break

                    previous_manual_fingerprint = current_fingerprint
                    previous_manual_learned = len(learned)
                    application.metadata["resume_current_page"] = True
                    print("\nResuming the same application automatically...")

                if final_result is None:
                    store.set_application_status(job_id, "error")
                    audit.finish(
                        run_id,
                        status="error",
                        submitted=False,
                        message="Adapter raised an exception.",
                        blockers=[{"category": "exception", "reason": "See adapter_exception audit event."}],
                    )
                    payload = {
                        "job_id": job_id,
                        "run_id": run_id,
                        "ats": adapter.name,
                        "status": "error",
                        "submitted": False,
                        "message": "Adapter raised an exception.",
                    }
                else:
                    store.set_application_status(job_id, final_status)
                    audit.finish(
                        run_id,
                        status=final_status,
                        submitted=bool(final_result.submitted),
                        message=final_result.message,
                        blockers=final_result.blockers,
                        decisions=final_result.decisions,
                        metadata=final_result.metadata,
                    )
                    payload = _result_payload(
                        job_id,
                        run_id,
                        adapter.name,
                        final_status,
                        final_result,
                    )

                results.append(payload)
                print(json.dumps(payload, indent=2))

            context.close()
    finally:
        memory.close()
        audit.close()
        store.close()

    print("\nQUEUE RESULT")
    print(json.dumps(results, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(description="Run v2 ATS adapters over the prepared job queue")
    parser.add_argument("--profile", default="candidate_profile.yaml")
    parser.add_argument("--db", default="data/jobs.db")
    parser.add_argument("--audit-db", default=DEFAULT_AUDIT_DB)
    parser.add_argument("--browser-profile", default=DEFAULT_BROWSER_PROFILE)
    parser.add_argument("--minimum-score", type=float, default=40.0)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-manual-cycles", type=int, default=4)
    parser.add_argument(
        "--statuses",
        default=",".join(DEFAULT_RESUME_STATUSES),
        help=(
            "Comma-separated application statuses to resume. Default: "
            + ",".join(DEFAULT_RESUME_STATUSES)
        ),
    )
    parser.add_argument(
        "--continue-on-review",
        action="store_true",
        help="Do not pause for manual review; record the status and continue to later jobs.",
    )
    return parser


def main():
    args = build_parser().parse_args()
    statuses = tuple(
        item.strip()
        for item in str(args.statuses).split(",")
        if item.strip()
    )
    run_queue(
        profile_path=args.profile,
        db_path=args.db,
        audit_db=args.audit_db,
        browser_profile=args.browser_profile,
        minimum_score=args.minimum_score,
        limit=args.limit,
        stop_on_review=not args.continue_on_review,
        statuses=statuses,
        max_manual_cycles=max(0, int(args.max_manual_cycles)),
    )


if __name__ == "__main__":
    main()
