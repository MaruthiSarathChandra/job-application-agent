from __future__ import annotations

from pipeline.ats import ATS_GREENHOUSE, ATS_LEVER, ATS_WORKDAY, detect_ats

from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter
from .workday import WorkdayAdapter


ADAPTERS = {
    ATS_GREENHOUSE: GreenhouseAdapter,
    ATS_LEVER: LeverAdapter,
    ATS_WORKDAY: WorkdayAdapter,
}


def get_adapter(job):
    ats = detect_ats(job.url)
    adapter_class = ADAPTERS.get(ats)
    return adapter_class() if adapter_class else None
