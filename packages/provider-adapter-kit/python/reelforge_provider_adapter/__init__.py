"""Menivor provider-adapter-kit — execution contract + shared metadata.

License, deprecation, and envelope metadata remain byte-identical to the
TypeScript port.  The Python side additionally owns the persistence-neutral v1
provider execution DTO and protocol used by API and Prism adapters.
"""

from .deprecation import (
    DEPRECATION_REGISTRY,
    lifecycle,
    migrate,
    replacement_for,
)
from .envelope import STATES, is_terminal, normalize_state, normalized_usage
from .execution import (
    ACCEPTANCE_CERTAINTIES,
    COST_SOURCES,
    ERROR_CATEGORIES,
    ERROR_PHASES,
    EXECUTION_SCHEMA_V1,
    HANDLE_SCHEMA_V1,
    INLINE_IMAGE_MEDIA_TYPES,
    MAX_INLINE_IMAGE_BYTES,
    OUTPUT_KINDS,
    RESULT_SCHEMA_V1,
    ProviderCostV1,
    ProviderExecutionErrorV1,
    ProviderExecutionException,
    ProviderExecutor,
    ProviderExecutorRegistry,
    ProviderHandleV1,
    ProviderOutputV1,
    ProviderRequestV1,
    ProviderResultV1,
    decode_legacy_execution,
    should_fail_over,
    validate_output_reference,
)
from .license import (
    LICENSE_CLASSES,
    LICENSE_REGISTRY,
    can_use_for_paid,
    license_class,
)

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "LICENSE_CLASSES",
    "LICENSE_REGISTRY",
    "license_class",
    "can_use_for_paid",
    "DEPRECATION_REGISTRY",
    "lifecycle",
    "replacement_for",
    "migrate",
    "STATES",
    "normalize_state",
    "is_terminal",
    "normalized_usage",
    "EXECUTION_SCHEMA_V1",
    "HANDLE_SCHEMA_V1",
    "RESULT_SCHEMA_V1",
    "ERROR_PHASES",
    "ERROR_CATEGORIES",
    "ACCEPTANCE_CERTAINTIES",
    "COST_SOURCES",
    "OUTPUT_KINDS",
    "INLINE_IMAGE_MEDIA_TYPES",
    "MAX_INLINE_IMAGE_BYTES",
    "ProviderRequestV1",
    "ProviderHandleV1",
    "ProviderOutputV1",
    "ProviderCostV1",
    "ProviderExecutionErrorV1",
    "ProviderExecutionException",
    "ProviderResultV1",
    "ProviderExecutor",
    "ProviderExecutorRegistry",
    "validate_output_reference",
    "should_fail_over",
    "decode_legacy_execution",
]
