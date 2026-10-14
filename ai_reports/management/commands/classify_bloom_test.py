"""
Django Development Command: classify_bloom_test

Runs sample questions across the 5 representative categories through the local
Hugging Face Bloom classifier to demonstrate inference output and benchmark CPU timing.
"""

import time
from django.core.management.base import BaseCommand

from ai_reports.bloom.classifier import BloomClassifier
from ai_reports.bloom.constants import DEFAULT_MODEL_NAME, DEFAULT_REVIEW_THRESHOLD


class Command(BaseCommand):
    help = "Run test classification on representative sample questions using local Hugging Face model."

    def handle(self, *args, **options):
        sample_questions = [
            {
                "category": "1. Direct Definition / Recall",
                "text": "What is the primary definition of polymorphism in object-oriented programming?",
            },
            {
                "category": "2. Concept Explanation",
                "text": "Explain why a binary search algorithm requires the input array to be sorted before searching.",
            },
            {
                "category": "3. Applying a Known Method",
                "text": "Calculate the final velocity of a vehicle accelerating at 4 m/s² from rest for 6 seconds.",
            },
            {
                "category": "4. Comparing / Analyzing Alternatives",
                "text": "Which algorithm would be most appropriate for finding the shortest path in a weighted graph with negative edge weights: Dijkstra or Bellman-Ford?",
            },
            {
                "category": "5. Ambiguous / Subjective Question",
                "text": "Which programming language is better for software development: Python or C++?",
            },
        ]

        self.stdout.write(self.style.NOTICE(f"\nLoading local model '{DEFAULT_MODEL_NAME}' on CPU..."))
        start_load = time.time()
        classifier = BloomClassifier(review_threshold=DEFAULT_REVIEW_THRESHOLD)
        load_time = time.time() - start_load
        self.stdout.write(self.style.SUCCESS(f"Model initialized in {load_time:.2f}s.\n"))

        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS("LOCAL BLOOM'S TAXONOMY ZERO-SHOT CLASSIFICATION REPORT"))
        self.stdout.write("=" * 80 + "\n")

        total_infer_time = 0.0

        for idx, sample in enumerate(sample_questions, 1):
            t0 = time.time()
            result = classifier.classify(sample["text"])
            infer_time = time.time() - t0
            total_infer_time += infer_time

            self.stdout.write(f"Sample #{idx}: {sample['category']}")
            self.stdout.write(f"Prompt        : \"{sample['text']}\"")
            self.stdout.write(f"Predicted     : {self.style.SUCCESS(result['level'])}")
            self.stdout.write(f"Confidence    : {result['confidence']:.2%}")
            
            review_status = self.style.WARNING("YES (Low Confidence)") if result['needs_review'] else self.style.SUCCESS("NO (High Confidence)")
            self.stdout.write(f"Needs Review  : {review_status}")
            
            self.stdout.write("Score Matrix  :")
            for level, score in result["scores"].items():
                bar = "#" * int(score * 30)
                self.stdout.write(f"   - {level:<11}: {score:>6.2%}  [{bar}]")
            self.stdout.write(f"Latency       : {infer_time*1000:.1f} ms")
            self.stdout.write("-" * 80 + "\n")

        avg_time = (total_infer_time / len(sample_questions)) * 1000
        self.stdout.write(self.style.SUCCESS(f"Summary: 5 samples evaluated. Average CPU latency: {avg_time:.1f} ms/question.\n"))
