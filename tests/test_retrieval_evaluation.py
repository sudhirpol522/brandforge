import unittest
from pathlib import Path

from brandforge.retrieval_evaluation import (
    evaluate,
    load_jsonl,
    ndcg_at,
    pairwise_ranking_accuracy,
    policy_violation_rate,
    recall_at,
    reciprocal_rank,
)


class RetrievalEvaluationTests(unittest.TestCase):
    def test_metric_formulas(self) -> None:
        judgments = {"a": 3, "b": 2, "c": 0, "d": 1}
        ranking = ["a", "b", "d", "c"]
        self.assertEqual(recall_at(ranking, judgments, 2), 2 / 3)
        self.assertAlmostEqual(ndcg_at(ranking, judgments, 10), 1.0)
        self.assertEqual(reciprocal_rank(ranking, judgments), 1.0)
        self.assertEqual(pairwise_ranking_accuracy(ranking, judgments), 1.0)
        self.assertEqual(policy_violation_rate(ranking, {"c"}, 3), 0.0)
        report = evaluate(
            load_jsonl(Path("evals/retrieval_judgments.synthetic.jsonl"))
        )
        self.assertEqual(report["schema_version"], 1)
        self.assertTrue(report["dataset"]["synthetic"])
        self.assertIn("not human-study", report["disclaimer"])


if __name__ == "__main__":
    unittest.main()
