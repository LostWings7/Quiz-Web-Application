"""
Bloom's Taxonomy Classification and Analytics Module.

Exports core classifier, services, and taxonomy constants.
"""

from .classifier import BloomClassifier
from .constants import (
    BLOOM_ANALYZE,
    BLOOM_APPLY,
    BLOOM_CHOICES,
    BLOOM_REMEMBER,
    BLOOM_SOURCE_CHOICES,
    BLOOM_UNDERSTAND,
    CANONICAL_BLOOM_LEVELS,
    DEFAULT_MODEL_NAME,
    DEFAULT_REVIEW_THRESHOLD,
    SOURCE_MANUAL,
    SOURCE_ZERO_SHOT,
)
from .service import BloomAnalyticsService, BloomClassificationService

__all__ = [
    'BloomClassifier',
    'BloomClassificationService',
    'BloomAnalyticsService',
    'CANONICAL_BLOOM_LEVELS',
    'BLOOM_CHOICES',
    'BLOOM_SOURCE_CHOICES',
    'BLOOM_REMEMBER',
    'BLOOM_UNDERSTAND',
    'BLOOM_APPLY',
    'BLOOM_ANALYZE',
    'SOURCE_MANUAL',
    'SOURCE_ZERO_SHOT',
    'DEFAULT_MODEL_NAME',
    'DEFAULT_REVIEW_THRESHOLD',
]
