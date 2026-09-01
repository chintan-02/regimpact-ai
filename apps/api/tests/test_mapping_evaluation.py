import json
from pathlib import Path
from typing import cast
from unittest import TestCase

from regimpact.mapping_evaluation import MappingEvaluationRow, evaluate


class MappingEvaluationTests(TestCase):
    def test_curated_regression_gates(self) -> None:
        fixture = json.loads((Path(__file__).parent / "fixtures/mapping_eval.json").read_text())
        self.assertIn("not production-grade", fixture["limitations"])
        metrics = evaluate(cast(list[MappingEvaluationRow], fixture["rows"]), top_k=2)
        self.assertGreaterEqual(metrics.candidate_recall_at_k, 0.95)
        self.assertGreaterEqual(metrics.precision_at_k, 0.45)
        self.assertGreaterEqual(metrics.mean_reciprocal_rank, 0.90)
        self.assertGreaterEqual(metrics.unmapped_accuracy, 1.0)
        self.assertLessEqual(metrics.ambiguity_rate, 0.30)
        self.assertLessEqual(metrics.review_workload, 0.65)
