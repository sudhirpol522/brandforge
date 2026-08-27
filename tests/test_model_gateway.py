import unittest

from brandforge.exceptions import BudgetExceededError
from brandforge.model_gateway import DeterministicModelProvider, ModelGateway


class ModelGatewayTests(unittest.TestCase):
    def test_enforces_call_budget(self) -> None:
        gateway = ModelGateway(
            DeterministicModelProvider(), max_calls_per_campaign=1, max_cost_per_campaign_usd=5
        )
        gateway.generate_text("one", "headline", "hello", 1)
        with self.assertRaises(BudgetExceededError):
            gateway.generate_text("one", "headline", "again", 2)

    def test_enforces_cost_budget(self) -> None:
        gateway = ModelGateway(
            DeterministicModelProvider(),
            max_calls_per_campaign=50,
            max_cost_per_campaign_usd=0.00005,
        )
        with self.assertRaises(BudgetExceededError):
            gateway.generate_text("one", "headline", "hello", 1)

    def test_usage_is_isolated_by_campaign(self) -> None:
        gateway = ModelGateway(DeterministicModelProvider())
        gateway.generate_text("one", "headline", "hello", 1)
        self.assertEqual(gateway.usage("one").calls, 1)
        self.assertEqual(gateway.usage("two").calls, 0)

    def test_deterministic_provider_repeats_output(self) -> None:
        provider = DeterministicModelProvider()
        left = provider.generate_text(purpose="copy", prompt="sample", seed=7)
        right = provider.generate_text(purpose="copy", prompt="sample", seed=7)
        self.assertEqual(left, right)
