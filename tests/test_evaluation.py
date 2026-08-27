import unittest
from pathlib import Path

from brandforge.evaluation import load_scenarios, run_benchmark


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = Path(__file__).parents[1] / "evals" / "benchmark.json"

    def test_benchmark_expands_to_120_scenarios(self) -> None:
        scenarios = load_scenarios(self.path)
        self.assertEqual(len(scenarios), 120)
        self.assertEqual(len({item.id for item in scenarios}), 120)

    def test_benchmark_includes_adversarial_and_sparse_groups(self) -> None:
        groups = {item.brief_id for item in load_scenarios(self.path)}
        self.assertIn("adversarial", groups)
        self.assertIn("sparse", groups)

    def test_small_benchmark_has_all_four_systems(self) -> None:
        result = run_benchmark(load_scenarios(self.path)[:2])
        self.assertEqual(len(result["systems"]), 4)
        self.assertEqual(result["scenario_count"], 2)
