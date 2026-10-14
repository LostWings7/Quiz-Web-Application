"""
Bloom's Taxonomy Zero-Shot Classifier.

Encapsulates Hugging Face Transformers zero-shot/NLI classification pipeline.
Executes 100% locally on CPU by default with cached in-memory singleton pipeline.
"""

import logging
import re
from typing import Any, Dict, List, Optional

try:
    import transformers
except ImportError:
    transformers = None

from .constants import (
    CANDIDATE_LABEL_TO_CANONICAL,
    CANDIDATE_LABELS,
    CANONICAL_BLOOM_LEVELS,
    DEFAULT_HYPOTHESIS_TEMPLATE,
    DEFAULT_MODEL_NAME,
    DEFAULT_REVIEW_THRESHOLD,
)

logger = logging.getLogger(__name__)


def clean_text_for_classification(text: str) -> str:
    """
    Strips HTML tags and normalizes whitespace in input question text.
    """
    if not text:
        return ""
    # Strip HTML tags
    clean = re.sub(r'<[^>]+>', ' ', text)
    # Normalize whitespace
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


class BloomClassifier:
    """
    Local Zero-Shot Classifier for Bloom's Taxonomy (Remember, Understand, Apply, Analyze).
    
    Loads Hugging Face zero-shot pipeline once into memory and reuses it across all requests.
    Supports CPU execution by default without network calls after initial download.
    """

    _pipeline = None
    _loaded_model_name: Optional[str] = None
    _loaded_device: Optional[str] = None

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        hypothesis_template: str = DEFAULT_HYPOTHESIS_TEMPLATE,
        review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
        device: str = "cpu",
    ):
        self.model_name = model_name
        self.hypothesis_template = hypothesis_template
        self.review_threshold = review_threshold
        self.device = device

    @classmethod
    def get_pipeline(cls, model_name: str = DEFAULT_MODEL_NAME, device: str = "cpu"):
        """
        Singleton pipeline accessor.
        Initializes and caches the Hugging Face zero-shot-classification pipeline on demand.
        """
        if cls._pipeline is None or cls._loaded_model_name != model_name or cls._loaded_device != device:
            logger.info("Initializing Hugging Face zero-shot pipeline with model '%s' on %s...", model_name, device)
            if transformers is None:
                raise ImportError(
                    "The 'transformers' package is required for Bloom classification. "
                    "Please install it using 'pip install torch transformers'."
                )

            # device=-1 specifies CPU execution in Hugging Face pipeline
            pipeline_device = -1 if device.lower() == "cpu" else 0

            cls._pipeline = transformers.pipeline(
                "zero-shot-classification",
                model=model_name,
                device=pipeline_device,
            )
            cls._loaded_model_name = model_name
            cls._loaded_device = device
            logger.info("Bloom zero-shot pipeline loaded successfully.")

        return cls._pipeline

    @classmethod
    def reset_pipeline(cls):
        """
        Reset cached pipeline instance (useful for testing and memory cleanup).
        """
        cls._pipeline = None
        cls._loaded_model_name = None
        cls._loaded_device = None

    def classify(self, text: str, review_threshold: Optional[float] = None) -> Dict[str, Any]:
        """
        Classify a single question text into one of the four Bloom's levels.

        :param text: Question text or prompt.
        :param review_threshold: Optional override for review threshold (defaults to self.review_threshold).
        :return: Dictionary containing level, confidence, complete scores dict, and needs_review flag.
        """
        threshold = self.review_threshold if review_threshold is None else review_threshold
        cleaned_text = clean_text_for_classification(text)

        if not cleaned_text:
            # Fallback for empty or whitespace-only inputs
            uniform_score = 0.25
            scores = {level: uniform_score for level in CANONICAL_BLOOM_LEVELS}
            return {
                "level": "Remember",
                "confidence": 0.0,
                "scores": scores,
                "needs_review": True,
            }

        pipe = self.get_pipeline(self.model_name, self.device)
        result = pipe(
            cleaned_text,
            candidate_labels=CANDIDATE_LABELS,
            hypothesis_template=self.hypothesis_template,
            multi_label=False,
        )

        return self._format_result(result, threshold)

    def classify_batch(
        self,
        texts: List[str],
        review_threshold: Optional[float] = None,
        batch_size: int = 16,
    ) -> List[Dict[str, Any]]:
        """
        Batch classify a list of question texts.

        :param texts: List of question texts.
        :param review_threshold: Optional override for review threshold.
        :param batch_size: Batch size for pipeline processing.
        :return: List of classification output dictionaries.
        """
        threshold = self.review_threshold if review_threshold is None else review_threshold
        if not texts:
            return []

        cleaned_texts = [clean_text_for_classification(t) for t in texts]
        non_empty_indices = [i for i, t in enumerate(cleaned_texts) if t]

        # Prepare outputs list initialized with default fallback for empty strings
        outputs: List[Optional[Dict[str, Any]]] = [None] * len(texts)
        for i, t in enumerate(cleaned_texts):
            if not t:
                outputs[i] = {
                    "level": "Remember",
                    "confidence": 0.0,
                    "scores": {level: 0.25 for level in CANONICAL_BLOOM_LEVELS},
                    "needs_review": True,
                }

        if non_empty_indices:
            valid_texts = [cleaned_texts[i] for i in non_empty_indices]
            pipe = self.get_pipeline(self.model_name, self.device)
            raw_results = pipe(
                valid_texts,
                candidate_labels=CANDIDATE_LABELS,
                hypothesis_template=self.hypothesis_template,
                multi_label=False,
                batch_size=batch_size,
            )

            if isinstance(raw_results, dict):
                raw_results = [raw_results]

            for original_idx, result in zip(non_empty_indices, raw_results):
                outputs[original_idx] = self._format_result(result, threshold)

        return [out for out in outputs if out is not None]

    def _format_result(self, raw_result: Dict[str, Any], threshold: float) -> Dict[str, Any]:
        """
        Format raw Hugging Face zero-shot output dictionary into structured Bloom format.
        """
        labels = raw_result.get("labels", [])
        raw_scores = raw_result.get("scores", [])

        # Build scores mapping for each canonical level
        scores: Dict[str, float] = {level: 0.0 for level in CANONICAL_BLOOM_LEVELS}
        for label_str, score_val in zip(labels, raw_scores):
            canonical = CANDIDATE_LABEL_TO_CANONICAL.get(label_str)
            if canonical in scores:
                scores[canonical] = round(float(score_val), 4)

        # The first label in raw_result['labels'] is the top-ranked label
        top_label_str = labels[0] if labels else CANDIDATE_LABELS[0]
        top_level = CANDIDATE_LABEL_TO_CANONICAL.get(top_label_str, "Remember")
        confidence = round(float(raw_scores[0]), 4) if raw_scores else 0.0
        needs_review = bool(confidence < threshold)

        return {
            "level": top_level,
            "confidence": confidence,
            "scores": scores,
            "needs_review": needs_review,
        }
