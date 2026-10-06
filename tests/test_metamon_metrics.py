import json
import math
import unittest

from scripts.run_metamon_challenge import json_safe_metrics


class TestMetamonMetrics(unittest.TestCase):
    def test_json_safe_metrics_converts_non_finite_values_to_null(self):
        metrics = json_safe_metrics(
            {"finite": 0.75, "nan": math.nan, "positive_infinity": math.inf}
        )

        self.assertEqual(
            metrics, {"finite": 0.75, "nan": None, "positive_infinity": None}
        )
        self.assertEqual(json.loads(json.dumps(metrics, allow_nan=False)), metrics)
