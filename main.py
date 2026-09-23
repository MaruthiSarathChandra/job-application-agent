import argparse
import json
from pathlib import Path

from agent.audit_log import AuditLog
from agent.engine import ApplicationEngine
from agent.profile import CandidateProfile
from agent.resume_router import ResumeRouter


def read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def cmd_init_db(args):
    db = AuditLog(args.db)
    db.close()
    print(f"Database ready: {args.db}")


def cmd_route_resume(args):
    profile = CandidateProfile(args.profile)
    router = ResumeRouter(profile)
    job_text = read_text(args.job_file)
    decision = router.choose(job_text)
    print(json.dumps(decision.to_dict(), indent=2))


def cmd_answer(args):
    profile = CandidateProfile(args.profile)
    engine = ApplicationEngine(profile, use_llm=not args.no_llm)
    job_text = read_text(args.job_file) if args.job_file else ""
    decision = engine.answer_question(args.question, job_text)
    print(json.dumps(decision.to_dict(), indent=2))


def cmd_dry_run(args):
    profile = CandidateProfile(args.profile)
    router = ResumeRouter(profile)
    engine = ApplicationEngine(profile, use_llm=not args.no_llm)
    audit = AuditLog(args.db)

    job_text = read_text(args.job_file)
    questions = json.loads(read_text(args.questions_file))

    if not isinstance(questions, list):
        raise ValueError("questions file must contain a JSON array of strings")

    resume = router.choose(job_text)

    application_id = audit.begin_application(
        job_text=job_text,
        resume=resume,
        company=args.company,
        role=args.role,
        job_url=args.job_url,
    )

    print(f"\nApplication ID: {application_id}")
    print("\nRESUME:")
    print(json.dumps(resume.to_dict(), indent=2))

    review_count = 0

    print("\nANSWERS:")
    for question in questions:
        decision = engine.answer_question(str(question), job_text)
        audit.log_decision(application_id, decision)

        if decision.review_required:
            review_count += 1

        print("-" * 70)
        print(f"Q: {decision.question}")
        print(f"A: {decision.answer}")
        print(
            f"source={decision.source} | "
            f"confidence={decision.confidence:.3f} | "
            f"review={decision.review_required} | "
            f"category={decision.category}"
        )
        print(f"reason={decision.rationale}")

    total = len(questions)
    review_rate = (review_count / total * 100.0) if total else 0.0

    final_status = "REVIEW_REQUIRED" if review_count else "DRY_RUN_READY"
    audit.set_status(application_id, final_status)
    audit.log_event(
        application_id,
        "DRY_RUN_SUMMARY",
        {
            "total_questions": total,
            "review_count": review_count,
            "review_rate_percent": round(review_rate, 2),
            "status": final_status,
        },
    )
    audit.close()

    print("\n" + "=" * 70)
    print(f"Questions: {total}")
    print(f"Needs review: {review_count}")
    print(f"Review rate: {review_rate:.2f}%")
    print(f"Final status: {final_status}")
    print(f"Audit DB: {args.db}")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Job Application Agent v0.1 — dry-run decision engine"
    )
    parser.add_argument(
        "--profile",
        default="candidate_profile.yaml",
        help="Path to candidate profile YAML",
    )
    parser.add_argument(
        "--db",
        default="data/applications.db",
        help="Path to SQLite audit database",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    init_db = sub.add_parser("init-db")
    init_db.set_defaults(func=cmd_init_db)

    route = sub.add_parser("route-resume")
    route.add_argument("--job-file", required=True)
    route.set_defaults(func=cmd_route_resume)

    answer = sub.add_parser("answer")
    answer.add_argument("--question", required=True)
    answer.add_argument("--job-file")
    answer.add_argument("--no-llm", action="store_true")
    answer.set_defaults(func=cmd_answer)

    dry = sub.add_parser("dry-run")
    dry.add_argument("--job-file", required=True)
    dry.add_argument("--questions-file", required=True)
    dry.add_argument("--company", default="")
    dry.add_argument("--role", default="")
    dry.add_argument("--job-url", default="")
    dry.add_argument("--no-llm", action="store_true")
    dry.set_defaults(func=cmd_dry_run)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
