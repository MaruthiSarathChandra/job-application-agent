import html
import re
from typing import Iterable, List

from .models import JobLead, JobMatch


TAG_RE = re.compile(r"<[^>]+>")
WORD_RE = re.compile(r"[a-z0-9+#.]+")


def _tokens(text: str):
    text = html.unescape(TAG_RE.sub(" ", text or "")).lower()
    return set(WORD_RE.findall(text))


def _contains_phrase(text: str, phrase: str) -> bool:
    return phrase.lower() in (text or "").lower()


def rank_job(job: JobLead, profile) -> JobMatch:
    verified_skills = profile.get("verified_facts.skills", []) or []
    target_roles = profile.get("preferences.target_roles", []) or []

    if not target_roles:
        target_roles = [
            "software engineer",
            "backend software engineer",
            "backend engineer",
            "java developer",
            "java software engineer",
        ]

    title = job.title or ""
    body = f"{job.title}\n{job.description}\n{job.location}"

    title_hits = [role for role in target_roles if _contains_phrase(title, role)]
    title_score = min(60.0, 30.0 * len(title_hits))

    body_tokens = _tokens(body)
    matched_skills: List[str] = []
    for skill in verified_skills:
        skill_norm = str(skill).strip()
        if not skill_norm:
            continue
        skill_tokens = _tokens(skill_norm)
        if skill_tokens and skill_tokens.issubset(body_tokens):
            matched_skills.append(skill_norm)
        elif _contains_phrase(body, skill_norm):
            matched_skills.append(skill_norm)

    denominator = max(1, min(len(verified_skills), 10))
    skills_score = min(40.0, 40.0 * len(matched_skills) / denominator)

    score = round(title_score + skills_score, 2)
    reasons = []
    if title_hits:
        reasons.append("title matched: " + ", ".join(title_hits[:3]))
    if matched_skills:
        reasons.append("skills matched: " + ", ".join(matched_skills[:8]))
    if not reasons:
        reasons.append("no strong verified-profile match")

    return JobMatch(
        job=job,
        score=score,
        title_score=round(title_score, 2),
        skills_score=round(skills_score, 2),
        matched_skills=matched_skills,
        reasons=reasons,
    )


def rank_jobs(jobs: Iterable[JobLead], profile, minimum_score: float = 0.0):
    ranked = [rank_job(job, profile) for job in jobs]
    ranked = [item for item in ranked if item.score >= minimum_score]
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked
