from __future__ import annotations

from pipeline.ats import (
    ATS_AVATURE,
    ATS_BRASSRING,
    ATS_CAREER_SITE,
    ATS_GREENHOUSE,
    ATS_LEVER,
    ATS_WORKDAY,
    detect_ats,
)

from .avature import AvatureAdapter
from .brassring import BrassRingAdapter
from .generic_career import GenericCareerSiteAdapter
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter
from .workday_autonomous import AutonomousWorkdayAdapter


ADAPTERS = {
    ATS_GREENHOUSE: GreenhouseAdapter,
    ATS_LEVER: LeverAdapter,
    ATS_WORKDAY: AutonomousWorkdayAdapter,
    ATS_BRASSRING: BrassRingAdapter,
    ATS_AVATURE: AvatureAdapter,
    ATS_CAREER_SITE: GenericCareerSiteAdapter,
}


def get_adapter(job):
    ats = detect_ats(job.url)
    adapter_class = ADAPTERS.get(ats)
    return adapter_class() if adapter_class else None
