import tempfile
import unittest
from pathlib import Path

from brandforge.preference_dataset import grouped_split, import_jsonl
from brandforge.preference_evaluation import (
    evaluate,
    expected_calibration_error,
    train_model,
)


class PreferenceEvaluationTests(unittest.TestCase):
    def test_calibration_error(self) -> None:
        self.assertAlmostEqual(
            expected_calibration_error([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0], bins=2),
            0.15,
        )

    def test_synthetic_training_report_is_explicitly_labeled(self) -> None:
        rows = import_jsonl(
            Path("evals/preference_comparisons.synthetic.jsonl"),
            tenant_id="synthetic-tenant",
            dataset_version="preference-synthetic-v1",
        )
        splits = grouped_split(rows)
        model = train_model(
            splits.train,
            dataset_fingerprint_value=splits.fingerprint,
            split_fingerprint=splits.fingerprint,
            epochs=10,
        )
        report = evaluate(model, splits)
        self.assertTrue(report["dataset"]["synthetic"])
        self.assertIn("not evidence", report["disclaimer"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            model.save(path)
            loaded = type(model).load(path)
            self.assertEqual(loaded.model_version, model.model_version)


if __name__ == "__main__":
    unittest.main()
