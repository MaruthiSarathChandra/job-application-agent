import argparse
import json
from pathlib import Path

from agent.profile import CandidateProfile
from learning.application_memory import ApplicationMemory
from pipeline.ats import detect_ats
from pipeline.job_matcher import rank_jobs
from pipeline.job_sources import (
    extract_urls_from_pdf,
    fetch_greenhouse_jobs,
    leads_from_pdf,
)
from pipeline.job_store import JobStore
from pipeline.models import JobLead
from pipeline.orchestrator import PipelineOrchestrator
from resume_builder.docx_resume import build_tailored_resume


DEFAULT_DB = "data/jobs.db"
DEFAULT_MEMORY_DB = "data/application_memory.db"


def _print_ranked(items, limit=25):
    for index, item in enumerate(items[:limit], start=1):
        job = item.job
        print(f"{index:02d}. {item.score:5.1f}  {job.title or '[title unknown]'}")
        if job.company:
            print(f"    {job.company}")
        if job.location:
            print(f"    {job.location}")
        print(f"    ATS={detect_ats(job.url)}  {job.url}")
        for reason in item.reasons:
            print(f"    - {reason}")


def _print_db_rows(rows):
    for index, row in enumerate(rows, start=1):
        score = row["match_score"]
        score_text = "  n/a" if score is None else f"{float(score):5.1f}"
        print(
            f"{index:03d}. {score_text}  {row['pipeline_status']:13} "
            f"{row['application_status']:12} {row['title'] or '[title unknown]'}"
        )
        print(f"     {row['company']} | {row['ats']} | {row['location']}")
        print(f"     id={row['job_id']}  {row['url']}")
        if row["resume_path"]:
            print(f"     resume={row['resume_path']}")
        if row["last_error"]:
            print(f"     error={row['last_error']}")


def _job_from_json(path: str) -> JobLead:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "job" in data and isinstance(data["job"], dict):
        data = data["job"]
    return JobLead(
        source=str(data.get("source", "manual")),
        company=str(data.get("company", "")),
        title=str(data.get("title", "")),
        url=str(data.get("url", "")),
        location=str(data.get("location", "")),
        description=str(data.get("description", "")),
        external_id=str(data.get("external_id", "")),
    )


def cmd_pdf_links(args):
    urls = extract_urls_from_pdf(args.pdf)
    for url in urls:
        print(f"{detect_ats(url):12} {url}")
    print(f"\n{len(urls)} unique URL(s)")


def cmd_greenhouse_rank(args):
    profile = CandidateProfile(args.profile)
    jobs = fetch_greenhouse_jobs(args.board, company=args.company or "")
    ranked = rank_jobs(jobs, profile, minimum_score=args.minimum_score)
    _print_ranked(ranked, args.limit)

    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([item.to_dict() for item in ranked], indent=2),
            encoding="utf-8",
        )
        print(f"\nSaved: {path}")


def cmd_ingest_greenhouse(args):
    jobs = fetch_greenhouse_jobs(args.board, company=args.company or "")
    store = JobStore(args.db)
    try:
        ids = store.upsert_many(jobs)
    finally:
        store.close()
    print(f"Ingested {len(jobs)} Greenhouse job(s); {len(set(ids))} unique ID(s).")


def cmd_ingest_pdf(args):
    jobs = leads_from_pdf(args.pdf, company=args.company or "")
    store = JobStore(args.db)
    try:
        ids = store.upsert_many(jobs)
    finally:
        store.close()
    print(f"Ingested {len(jobs)} PDF career/job link(s); {len(set(ids))} unique ID(s).")


def cmd_rank_db(args):
    profile = CandidateProfile(args.profile)
    store = JobStore(args.db)
    try:
        orchestrator = PipelineOrchestrator(profile, store)
        ranked = orchestrator.rank_all(limit=args.scan_limit)
    finally:
        store.close()

    filtered = [item for item in ranked if item.score >= args.minimum_score]
    _print_ranked(filtered, args.limit)
    print(f"\nRanked {len(ranked)} job(s); {len(filtered)} at/above {args.minimum_score}.")


def cmd_prepare(args):
    profile = CandidateProfile(args.profile)
    store = JobStore(args.db)
    try:
        orchestrator = PipelineOrchestrator(profile, store)
        if args.rank_first:
            orchestrator.rank_all(limit=args.scan_limit)
        prepared = orchestrator.prepare_resumes(
            minimum_score=args.minimum_score,
            output_dir=args.output_dir,
            limit=args.limit,
        )
    finally:
        store.close()

    print(json.dumps(prepared, indent=2))
    ok = sum(1 for item in prepared if item.get("resume_path"))
    print(f"\nPrepared {ok}/{len(prepared)} resume(s).")


def cmd_ready(args):
    store = JobStore(args.db)
    try:
        rows = store.list_rows(
            minimum_score=args.minimum_score,
            pipeline_status="resume_ready",
            application_status="not_started",
            limit=args.limit,
        )
        _print_db_rows(rows)
    finally:
        store.close()


def cmd_list_jobs(args):
    store = JobStore(args.db)
    try:
        rows = store.list_rows(
            minimum_score=args.minimum_score,
            pipeline_status=args.pipeline_status or None,
            application_status=args.application_status or None,
            limit=args.limit,
        )
        _print_db_rows(rows)
    finally:
        store.close()


def cmd_greenhouse_pipeline(args):
    profile = CandidateProfile(args.profile)
    jobs = fetch_greenhouse_jobs(args.board, company=args.company or "")
    store = JobStore(args.db)
    try:
        orchestrator = PipelineOrchestrator(profile, store)
        orchestrator.ingest(jobs)
        ranked = orchestrator.rank_all(limit=max(args.limit * 10, 500))
        prepared = orchestrator.prepare_resumes(
            minimum_score=args.minimum_score,
            output_dir=args.output_dir,
            limit=args.limit,
        )
    finally:
        store.close()

    strong = [item for item in ranked if item.score >= args.minimum_score]
    print(f"Discovered: {len(jobs)}")
    print(f"Qualified:  {len(strong)}")
    print(f"Prepared:   {sum(1 for x in prepared if x.get('resume_path'))}")
    _print_ranked(strong, min(args.limit, 20))


def cmd_tailor(args):
    profile = CandidateProfile(args.profile)
    job = _job_from_json(args.job)
    output = build_tailored_resume(profile, job, args.output)
    print(output)


def cmd_remember(args):
    memory = ApplicationMemory(args.memory_db)
    try:
        stored = memory.remember_confirmed(
            question=args.question,
            answer=args.answer,
            company=args.company or "",
            ats=args.ats or "",
            category=args.category or "general",
        )
        stats = memory.stats()
    finally:
        memory.close()

    if stored:
        print("Confirmed answer stored.")
    else:
        print("Answer was NOT stored (empty or sensitive/high-risk question).")
    print(json.dumps(stats, indent=2))


def cmd_recall(args):
    memory = ApplicationMemory(args.memory_db)
    try:
        result = memory.lookup(
            args.question,
            company=args.company or "",
            ats=args.ats or "",
            min_confirmations=args.min_confirmations,
        )
    finally:
        memory.close()

    if result is None:
        print("NO_REUSABLE_MEMORY")
        return

    print(json.dumps({
        "answer": result.answer,
        "company": result.company,
        "ats": result.ats,
        "confirmations": result.confirmations,
        "category": result.category,
        "similarity": result.similarity,
    }, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(description="Job Application Agent v2 pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    pdf = sub.add_parser("pdf-links", help="Extract and classify career/job links from a PDF")
    pdf.add_argument("--pdf", required=True)
    pdf.set_defaults(func=cmd_pdf_links)

    greenhouse = sub.add_parser(
        "greenhouse-rank",
        help="Fetch a Greenhouse board and rank jobs without persisting them",
    )
    greenhouse.add_argument("--board", required=True, help="Board token or Greenhouse URL")
    greenhouse.add_argument("--company", default="")
    greenhouse.add_argument("--profile", default="candidate_profile.yaml")
    greenhouse.add_argument("--minimum-score", type=float, default=20.0)
    greenhouse.add_argument("--limit", type=int, default=25)
    greenhouse.add_argument("--output", default="data/ranked_jobs.json")
    greenhouse.set_defaults(func=cmd_greenhouse_rank)

    ingest_gh = sub.add_parser("ingest-greenhouse", help="Persist a Greenhouse board in the job database")
    ingest_gh.add_argument("--board", required=True)
    ingest_gh.add_argument("--company", default="")
    ingest_gh.add_argument("--db", default=DEFAULT_DB)
    ingest_gh.set_defaults(func=cmd_ingest_greenhouse)

    ingest_pdf = sub.add_parser("ingest-pdf", help="Persist career/job links from a PDF")
    ingest_pdf.add_argument("--pdf", required=True)
    ingest_pdf.add_argument("--company", default="")
    ingest_pdf.add_argument("--db", default=DEFAULT_DB)
    ingest_pdf.set_defaults(func=cmd_ingest_pdf)

    rank_db = sub.add_parser("rank-db", help="Rank persisted jobs against the verified candidate profile")
    rank_db.add_argument("--profile", default="candidate_profile.yaml")
    rank_db.add_argument("--db", default=DEFAULT_DB)
    rank_db.add_argument("--minimum-score", type=float, default=20.0)
    rank_db.add_argument("--limit", type=int, default=25)
    rank_db.add_argument("--scan-limit", type=int, default=5000)
    rank_db.set_defaults(func=cmd_rank_db)

    prepare = sub.add_parser("prepare", help="Generate DOCX resumes for strong, unapplied jobs")
    prepare.add_argument("--profile", default="candidate_profile.yaml")
    prepare.add_argument("--db", default=DEFAULT_DB)
    prepare.add_argument("--minimum-score", type=float, default=40.0)
    prepare.add_argument("--limit", type=int, default=25)
    prepare.add_argument("--scan-limit", type=int, default=5000)
    prepare.add_argument("--output-dir", default="data/generated_resumes")
    prepare.add_argument("--rank-first", action="store_true")
    prepare.set_defaults(func=cmd_prepare)

    ready = sub.add_parser("ready", help="Show jobs with generated resumes ready for an ATS adapter")
    ready.add_argument("--db", default=DEFAULT_DB)
    ready.add_argument("--minimum-score", type=float, default=40.0)
    ready.add_argument("--limit", type=int, default=100)
    ready.set_defaults(func=cmd_ready)

    listing = sub.add_parser("list-jobs", help="Inspect the persistent job queue")
    listing.add_argument("--db", default=DEFAULT_DB)
    listing.add_argument("--minimum-score", type=float, default=None)
    listing.add_argument("--pipeline-status", default="")
    listing.add_argument("--application-status", default="")
    listing.add_argument("--limit", type=int, default=100)
    listing.set_defaults(func=cmd_list_jobs)

    gp = sub.add_parser(
        "greenhouse-pipeline",
        help="Discover, persist, rank and prepare resumes from one Greenhouse board",
    )
    gp.add_argument("--board", required=True)
    gp.add_argument("--company", default="")
    gp.add_argument("--profile", default="candidate_profile.yaml")
    gp.add_argument("--db", default=DEFAULT_DB)
    gp.add_argument("--minimum-score", type=float, default=40.0)
    gp.add_argument("--limit", type=int, default=25)
    gp.add_argument("--output-dir", default="data/generated_resumes")
    gp.set_defaults(func=cmd_greenhouse_pipeline)

    tailor = sub.add_parser("tailor", help="Build one DOCX from verified local resume content")
    tailor.add_argument("--job", required=True, help="JSON file containing one job")
    tailor.add_argument("--profile", default="candidate_profile.yaml")
    tailor.add_argument("--output", required=True)
    tailor.set_defaults(func=cmd_tailor)

    remember = sub.add_parser("remember", help="Store a user-confirmed non-sensitive application answer")
    remember.add_argument("--question", required=True)
    remember.add_argument("--answer", required=True)
    remember.add_argument("--company", default="")
    remember.add_argument("--ats", default="")
    remember.add_argument("--category", default="general")
    remember.add_argument("--memory-db", default=DEFAULT_MEMORY_DB)
    remember.set_defaults(func=cmd_remember)

    recall = sub.add_parser("recall", help="Test whether an answer is reusable from confirmed memory")
    recall.add_argument("--question", required=True)
    recall.add_argument("--company", default="")
    recall.add_argument("--ats", default="")
    recall.add_argument("--min-confirmations", type=int, default=2)
    recall.add_argument("--memory-db", default=DEFAULT_MEMORY_DB)
    recall.set_defaults(func=cmd_recall)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
