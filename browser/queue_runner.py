from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from agent.profile import CandidateProfile
from browser.adapters import ApplicationContext, get_adapter
from pipeline.job_store import JobStore


DEFAULT_BROWSER_PROFILE = "data/browser_profile_v2"


def _submission_mode(profile) -> str:
    return str(profile.get("submission.mode", "manual") or "manual").strip().lower()


def run_queue(
    profile_path: str,
    db_path: str,
    browser_profile: str,
    minimum_score: float,
    limit: int,
    stop_on_review: bool = True,
):
    profile = CandidateProfile(profile_path)
    store = JobStore(db_path)
    mode = _submission_mode(profile)

    rows = store.list_rows(
        minimum_score=minimum_score,
        pipeline_status="resume_ready",
        application_status="not_started",
        limit=limit,
    )

    if not rows:
        print("No resume-ready, unapplied jobs are currently queued.")
        store.close()
        return

    print(f"Queued jobs: {len(rows)}")
    print(f"Submission mode: {mode}")

    results = []

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
                    results.append({
                        "job_id": job_id,
                        "status": "adapter_missing",
                        "ats": row["ats"],
                        "url": job.url,
                    })
                    continue

                application = ApplicationContext(
                    job_id=job_id,
                    job=job,
                    resume_path=row["resume_path"],
                    company=job.company,
                    role=job.title,
                    submission_mode=mode,
                    metadata={"match_score": row["match_score"]},
                )

                print("\n" + "=" * 78)
                print(f"JOB {job_id} | {adapter.name} | {job.company} | {job.title}")
                print(job.url)
                print("=" * 78)

                store.set_application_status(job_id, "in_progress")

                try:
                    result = adapter.run(page, profile, application)
                except Exception as exc:
                    store.set_application_status(job_id, "error")
                    store.set_error(job_id, str(exc), status="application_error")
                    results.append({
                        "job_id": job_id,
                        "status": "error",
                        "error": str(exc),
                    })
                    continue

                if result.submitted:
                    status = "submitted"
                elif result.status == "ready_for_review":
                    status = "ready_for_review"
                elif result.status == "workday_runner_required":
                    status = "workday_runner_required"
                elif result.review_required:
                    status = "review"
                else:
                    status = result.status or "unknown"

                store.set_application_status(job_id, status)
                payload = {
                    "job_id": job_id,
                    "ats": adapter.name,
                    "status": status,
                    "submitted": result.submitted,
                    "message": result.message,
                    "blockers": result.blockers,
                }
                results.append(payload)
                print(json.dumps(payload, indent=2))

                if status in {"ready_for_review", "review"} and stop_on_review:
                    print(
                        "\nBrowser is intentionally staying open for review. "
                        "Complete any manual fields/verification yourself."
                    )
                    input("Press ENTER here when you are finished reviewing this page...")
                    break

            context.close()
    finally:
        store.close()

    print("\nQUEUE RESULT")
    print(json.dumps(results, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(description="Run v2 ATS adapters over the prepared job queue")
    parser.add_argument("--profile", default="candidate_profile.yaml")
    parser.add_argument("--db", default="data/jobs.db")
    parser.add_argument("--browser-profile", default=DEFAULT_BROWSER_PROFILE)
    parser.add_argument("--minimum-score", type=float, default=40.0)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--continue-on-review",
        action="store_true",
        help="Continue to later jobs instead of stopping when a page requires review.",
    )
    return parser


def main():
    args = build_parser().parse_args()
    run_queue(
        profile_path=args.profile,
        db_path=args.db,
        browser_profile=args.browser_profile,
        minimum_score=args.minimum_score,
        limit=args.limit,
        stop_on_review=not args.continue_on_review,
    )


if __name__ == "__main__":
    main()
