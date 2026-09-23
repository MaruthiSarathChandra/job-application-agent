import argparse
import json
from pathlib import Path

from agent.profile import CandidateProfile
from pipeline.job_matcher import rank_jobs
from pipeline.job_sources import extract_urls_from_pdf, fetch_greenhouse_jobs
from pipeline.models import JobLead
from resume_builder.docx_resume import build_tailored_resume


def _print_ranked(items, limit=25):
    for index, item in enumerate(items[:limit], start=1):
        job = item.job
        print(f"{index:02d}. {item.score:5.1f}  {job.title or '[title unknown]'}")
        if job.company:
            print(f"    {job.company}")
        if job.location:
            print(f"    {job.location}")
        print(f"    {job.url}")
        for reason in item.reasons:
            print(f"    - {reason}")


def cmd_pdf_links(args):
    urls = extract_urls_from_pdf(args.pdf)
    for url in urls:
        print(url)
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


def cmd_tailor(args):
    profile = CandidateProfile(args.profile)
    job = _job_from_json(args.job)
    output = build_tailored_resume(profile, job, args.output)
    print(output)


def build_parser():
    parser = argparse.ArgumentParser(description="Job Application Agent v2 pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    pdf = sub.add_parser("pdf-links", help="Extract career/job links from a PDF")
    pdf.add_argument("--pdf", required=True)
    pdf.set_defaults(func=cmd_pdf_links)

    greenhouse = sub.add_parser(
        "greenhouse-rank",
        help="Fetch a Greenhouse board and rank jobs against verified profile facts",
    )
    greenhouse.add_argument("--board", required=True, help="Board token or Greenhouse URL")
    greenhouse.add_argument("--company", default="")
    greenhouse.add_argument("--profile", default="candidate_profile.yaml")
    greenhouse.add_argument("--minimum-score", type=float, default=20.0)
    greenhouse.add_argument("--limit", type=int, default=25)
    greenhouse.add_argument("--output", default="data/ranked_jobs.json")
    greenhouse.set_defaults(func=cmd_greenhouse_rank)

    tailor = sub.add_parser("tailor", help="Build a DOCX from verified local resume content")
    tailor.add_argument("--job", required=True, help="JSON file containing one job")
    tailor.add_argument("--profile", default="candidate_profile.yaml")
    tailor.add_argument("--output", required=True)
    tailor.set_defaults(func=cmd_tailor)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
