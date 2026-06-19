"""ROGUE — continuous LLM red-team SDK.

    from rogue import Rogue
    rogue = Rogue(api_key="...")
    deployment = rogue.register(name="Support Agent", model="gpt-5", system_prompt="...")
    report = rogue.scan(deployment)
    print(report.summary())

See DESIGN.md for architecture and CONTRACT.md for the wire protocol.
"""

from ._version import API_VERSION, __version__
from .client.rogue import Rogue
from .exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    RogueConfigError,
    RogueError,
    ScanError,
    ScanFailedError,
    ScanTimeoutError,
    ValidationError,
)
from .models import (
    Deployment,
    Finding,
    Provider,
    Report,
    ReportSummary,
    Scan,
    ScanStatus,
    Severity,
)
from .transport import HTTPTransport, MockTransport, Transport

__all__ = [
    "Rogue",
    "__version__",
    "API_VERSION",
    # models
    "Deployment",
    "Scan",
    "Report",
    "ReportSummary",
    "Finding",
    "Severity",
    "ScanStatus",
    "Provider",
    # transport
    "Transport",
    "HTTPTransport",
    "MockTransport",
    # exceptions
    "RogueError",
    "RogueConfigError",
    "ValidationError",
    "APIError",
    "AuthenticationError",
    "AuthorizationError",
    "NotFoundError",
    "ConflictError",
    "RateLimitError",
    "APIConnectionError",
    "ScanError",
    "ScanFailedError",
    "ScanTimeoutError",
]
