"""FEWS validation passes (semantic, XSD).

Semantic validation answers: do the cross-file IDs referenced in the
generated config actually exist at their declaration sites? XSD checks
the shape; semantic checks the content.
"""
from .semantic import (
    IdRef,
    SemanticReport,
    validate_semantic,
)
from .xsd import validate_xsd

__all__ = ["IdRef", "SemanticReport", "validate_semantic", "validate_xsd"]
