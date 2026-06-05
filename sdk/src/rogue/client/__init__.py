"""Client layer: the Rogue facade + auth/deployments/scans/reports sub-clients."""

from .auth import AuthManager
from .deployments import DeploymentsClient
from .reports import ReportsClient
from .rogue import DEFAULT_BASE_URL, Rogue
from .scans import ScansClient

__all__ = [
    "Rogue",
    "DEFAULT_BASE_URL",
    "AuthManager",
    "DeploymentsClient",
    "ScansClient",
    "ReportsClient",
]
