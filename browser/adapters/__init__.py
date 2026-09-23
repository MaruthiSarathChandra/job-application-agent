from browser.account_recovery_resilience import install_account_recovery_resilience

# Install live-ATS account recovery fallbacks before adapter modules import
# handle_account_page directly. This keeps the shared account manager behavior
# consistent across Avature and the generic fallback without duplicating logic.
install_account_recovery_resilience()

from .base import AdapterResult, ApplicationContext, ATSAdapter
from .registry import get_adapter

__all__ = [
    "AdapterResult",
    "ApplicationContext",
    "ATSAdapter",
    "get_adapter",
]
