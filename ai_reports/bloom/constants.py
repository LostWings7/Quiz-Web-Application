"""
Bloom's Taxonomy Constants and Configurations.

Defines canonical Bloom's levels (first four levels: Remember, Understand, Apply, Analyze),
zero-shot NLI candidate label mappings, default model configuration, and initial review threshold.
"""

# Canonical 4 Bloom's Levels (DB value -> Display Label)
BLOOM_REMEMBER = 'remember'
BLOOM_UNDERSTAND = 'understand'
BLOOM_APPLY = 'apply'
BLOOM_ANALYZE = 'analyze'

BLOOM_CHOICES = [
    (BLOOM_REMEMBER, 'Remember'),
    (BLOOM_UNDERSTAND, 'Understand'),
    (BLOOM_APPLY, 'Apply'),
    (BLOOM_ANALYZE, 'Analyze'),
]

# Display names (Title-cased canonical names)
CANONICAL_BLOOM_LEVELS = ['Remember', 'Understand', 'Apply', 'Analyze']

# Map from lowercase DB value to Title-case display name
DB_TO_DISPLAY_MAP = {
    BLOOM_REMEMBER: 'Remember',
    BLOOM_UNDERSTAND: 'Understand',
    BLOOM_APPLY: 'Apply',
    BLOOM_ANALYZE: 'Analyze',
}

# Map from Title-case display name to lowercase DB value
DISPLAY_TO_DB_MAP = {
    'Remember': BLOOM_REMEMBER,
    'Understand': BLOOM_UNDERSTAND,
    'Apply': BLOOM_APPLY,
    'Analyze': BLOOM_ANALYZE,
}

# Classification Sources
SOURCE_MANUAL = 'manual'
SOURCE_ZERO_SHOT = 'zero_shot'

BLOOM_SOURCE_CHOICES = [
    (SOURCE_MANUAL, 'Manual'),
    (SOURCE_ZERO_SHOT, 'Zero-shot'),
]

# Zero-Shot NLI Configuration
DEFAULT_MODEL_NAME = "valhalla/distilbart-mnli-12-3"
DEFAULT_HYPOTHESIS_TEMPLATE = "This exam question tests the student's ability to {}."

# Educational Candidate Labels with pedagogical descriptions for NLI entailment
CANDIDATE_LABELS = [
    "recall facts, terms, definitions, formulas, or basic concepts (Remember)",
    "understand, explain ideas, interpret principles, or summarize meaning (Understand)",
    "apply knowledge, formulas, algorithms, or procedures to solve a problem (Apply)",
    "analyze, compare alternatives, deconstruct patterns, or diagnose evidence (Analyze)",
]

# Mapping from NLI candidate label strings back to canonical display names
CANDIDATE_LABEL_TO_CANONICAL = {
    CANDIDATE_LABELS[0]: 'Remember',
    CANDIDATE_LABELS[1]: 'Understand',
    CANDIDATE_LABELS[2]: 'Apply',
    CANDIDATE_LABELS[3]: 'Analyze',
}

# Configurable Initial Review Threshold (Heuristic - 0.45)
# If the top confidence is below this threshold, the classification is flagged for teacher review.
DEFAULT_REVIEW_THRESHOLD = 0.45
