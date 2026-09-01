import asyncio
import json
from pathlib import Path
from unittest import TestCase

import httpx

from regimpact.calibration import (
    CALIBRATION_CANDIDATE_COUNT,
    CURRENT_POLICY,
    DATASET_SIZE,
    calibration_metrics,
    select_precision_threshold,
)
from regimpact.domain import Section
from regimpact.main import create_app
from regimpact.obligation_extraction import extract_obligations


class CalibrationPolicyTests(TestCase):
    def test_policy_is_monotonic_bounded_and_versioned(self):
        calibrated = [item.calibrated_confidence for item in CURRENT_POLICY.bins]
        self.assertEqual(calibrated, sorted(calibrated))
        self.assertTrue(all(0 <= value <= 1 for value in calibrated))
        self.assertEqual(
            sum(item.training_count for item in CURRENT_POLICY.bins),
            CALIBRATION_CANDIDATE_COUNT,
        )
        self.assertGreaterEqual(CURRENT_POLICY.review_threshold, 0.80)

    def test_annotated_corpus_meets_candidate_and_auto_route_safety_gates(self):
        path = Path(__file__).parent / "fixtures" / "obligation_calibration.json"
        cases = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), DATASET_SIZE)
        candidate_tp = candidate_fp = candidate_fn = 0
        auto_tp = auto_fp = 0
        calibration_observations = []
        for case in cases:
            candidates = extract_obligations(Section(case["id"], case["id"], case["text"]))
            predicted = bool(candidates)
            auto_routed = any(not item.requires_review for item in candidates)
            if predicted and case["label"]:
                candidate_tp += 1
            elif predicted:
                candidate_fp += 1
            elif case["label"]:
                candidate_fn += 1
            if auto_routed and case["label"]:
                auto_tp += 1
            elif auto_routed:
                auto_fp += 1
            calibration_observations.extend(
                (item.confidence, bool(case["label"])) for item in candidates
            )
        precision = candidate_tp / (candidate_tp + candidate_fp)
        recall = candidate_tp / (candidate_tp + candidate_fn)
        auto_precision = auto_tp / (auto_tp + auto_fp)
        self.assertGreaterEqual(precision, 0.85)
        self.assertGreaterEqual(recall, 0.90)
        self.assertGreaterEqual(auto_precision, CURRENT_POLICY.minimum_precision)
        observations = tuple(calibration_observations)
        self.assertEqual(
            select_precision_threshold(
                observations, minimum_precision=CURRENT_POLICY.minimum_precision
            ),
            CURRENT_POLICY.review_threshold,
        )
        brier, ece = calibration_metrics(observations)
        self.assertLessEqual(brier, 0.11)
        self.assertLessEqual(ece, 0.11)

    def test_policy_endpoint_exposes_lineage_and_threshold(self):
        async def request():
            transport = httpx.ASGITransport(app=create_app())
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get("/api/v1/system/calibration-policy")

        response = asyncio.run(request())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["policy_id"], CURRENT_POLICY.policy_id)
        self.assertEqual(response.json()["dataset_size"], DATASET_SIZE)
        self.assertEqual(
            response.json()["calibration_candidate_count"], CALIBRATION_CANDIDATE_COUNT
        )
