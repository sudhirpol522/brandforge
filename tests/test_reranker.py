import copy
import unittest

from brandforge.agents import BrandCompilerAgent, CampaignPlannerAgent, CreativeAgent
from brandforge.agents.preferences import PairwiseExample, PairwisePreferenceModel
from brandforge.agents.reranker import MultimodalReranker, RankingWeights
from brandforge.domain import ScoreBreakdown
from brandforge.model_gateway import DeterministicModelProvider, ModelGateway
from tests.helpers import GUIDE, brief


class RerankerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules, _ = BrandCompilerAgent().run(GUIDE)
        self.plan, _ = CampaignPlannerAgent().run(brief(), self.rules)
        gateway = ModelGateway(DeterministicModelProvider())
        self.variants, _ = CreativeAgent(gateway).run(
            "campaign-test", brief(), self.rules, self.plan
        )

    def test_returns_three_ranked_candidates(self) -> None:
        ranked, _ = MultimodalReranker().run(
            brief(), self.rules, copy.deepcopy(self.variants), top_k=3
        )
        self.assertEqual([item.rank for item in ranked], [1, 2, 3])

    def test_off_brand_candidate_does_not_rank_first(self) -> None:
        ranked, _ = MultimodalReranker().run(
            brief(), self.rules, copy.deepcopy(self.variants), top_k=8
        )
        self.assertNotEqual(ranked[0].palette, ["#FF00FF", "#00FFFF"])

    def test_external_vision_scores_change_scorer_mode(self) -> None:
        subset = copy.deepcopy(self.variants[:3])
        scores = {
            subset[0].id: {
                "brief_alignment": 0.9,
                "brand_alignment": 0.9,
                "composition_quality": 0.9,
            }
        }
        ranked, _ = MultimodalReranker().run(
            brief(), self.rules, subset, top_k=3, external_visual_scores=scores
        )
        scored = next(item for item in ranked if item.id in scores)
        self.assertIn("provider_vision", scored.scores.scorer_mode)

    def test_ranking_weights_sum_to_one(self) -> None:
        weights = RankingWeights()
        self.assertAlmostEqual(sum(getattr(weights, key) for key in weights.__slots__), 1.0)

    def test_preference_model_trains_on_pair(self) -> None:
        preferred = ScoreBreakdown(brand_compliance=1, brief_alignment=0.9)
        rejected = ScoreBreakdown(brand_compliance=0.2, brief_alignment=0.3)
        model = PairwisePreferenceModel().fit([PairwiseExample(preferred, rejected)])
        self.assertGreater(model.predict(preferred), model.predict(rejected))
        self.assertGreater(model.predict_pair(preferred, rejected), 0.5)
        self.assertEqual(model.training_examples, 1)
