"""Client-side utilities: pre-network validation, credential config, opt-in telemetry."""

from . import config
from .telemetry import Telemetry
from .validation import (
    validate_api_key,
    validate_base_url,
    validate_deployment,
    validate_model_id,
)

__all__ = [
    "config",
    "Telemetry",
    "validate_api_key",
    "validate_base_url",
    "validate_deployment",
    "validate_model_id",
]
