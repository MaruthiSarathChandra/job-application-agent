from __future__ import annotations

from pipeline.ats import ATS_GREENHOUSE, ATS_LEVER, ATS_WORKDAY, detect_ats

from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter


class WorkdayLegacyAdapter:
    """
    Routing placeholder until the existing deterministic Workday runner is
    refactored behind the common ATSAdapter contract.
    """

    name = ATS_WORKDAY

    def supports(self, job):
        return detect_ats(job.url) == ATS_WORKDAY

    def run(self, page, profile, context):
        from .base import AdapterResult

        return AdapterResult(
            status="workday_runner_required",
            review_required=True,
            message=(
                "This Workday job is routed correctly, but v2 still uses "
                "browser/workday_runner.py for execution."
            ),
            metadata={
                "job_url": context.job.url,
                "company": context.company or context.job.company,
                "role": context.role or context.job.title,
            },
        )


ADAPTERS = {
    ATS_GREENHOUSE: GreenhouseAdapter,
    ATS_LEVER: LeverAdapter,
    ATS_WORKDAY: WorkdayLegacyAdapter,
}


def get_adapter(job):
    ats = detect_ats(job.url)
    adapter_class = ADAPTERS.get(ats)
    return adapter_class() if adapter_class else None
