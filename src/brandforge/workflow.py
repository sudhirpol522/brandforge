from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from .agents.brand_compiler import BrandCompilerAgent
from .agents.creative import CreativeAgent
from .agents.planner import CampaignPlannerAgent
from .agents.reranker import MultimodalReranker
from .domain import (
    ApprovalDecision,
    ApprovalGate,
    ApprovalRecord,
    AssetRecord,
    Campaign,
    CampaignBrief,
    CampaignStatus,
    OutboxEvent,
    PreferenceFeedback,
    utc_now,
)
from .editor import DesignEditor, DesignSnapshot
from .exceptions import InvalidTransitionError, ValidationError
from .exporter import CampaignExporter
from .ports import CampaignRepository
from .retrieval import IndexingSummary, RetrievalStatusSummary, SearchResult
from .retrieval_service import MultimodalRetrievalService
from .state_machine import assert_transition
from .telemetry import Timer, metrics, trace_id_var


class BrandForgeWorkflow:
    """Application service implementing the four human review gates."""

    def __init__(
        self,
        repository: CampaignRepository,
        brand_compiler: BrandCompilerAgent,
        planner: CampaignPlannerAgent,
        creative: CreativeAgent,
        reranker: MultimodalReranker,
        exporter: CampaignExporter,
        editor: DesignEditor | None = None,
        retrieval: MultimodalRetrievalService | None = None,
    ) -> None:
        self.repository = repository
        self.brand_compiler = brand_compiler
        self.planner = planner
        self.creative = creative
        self.reranker = reranker
        self.exporter = exporter
        self.editor = editor or DesignEditor(exporter.object_store)
        self.retrieval = retrieval

    def create_campaign(self, tenant_id: str, name: str, brief: CampaignBrief) -> Campaign:
        if not tenant_id.strip() or not name.strip():
            raise ValidationError("tenant and campaign name are required")
        if not brief.objective.strip() or not brief.audience.strip():
            raise ValidationError("campaign objective and audience are required")
        campaign = Campaign.create(tenant_id.strip(), name.strip(), brief)
        saved = self._save_with_event(
            campaign,
            0,
            "campaign.created",
            {"name": campaign.name, "status": campaign.status},
        )
        metrics.increment("brandforge_campaigns_total", status="created")
        return saved

    def compile_brand_guide(self, tenant_id: str, campaign_id: str, guide_text: str) -> Campaign:
        campaign = self.repository.get(tenant_id, campaign_id)
        if campaign.status not in {CampaignStatus.CREATED, CampaignStatus.ASSETS_PROCESSING}:
            raise InvalidTransitionError("brand guide can only be compiled during setup")
        token = trace_id_var.set(campaign.trace_id)
        try:
            with Timer(metrics, "brandforge_agent_duration_seconds", agent="brand_compiler"):
                rules, trace = self.brand_compiler.run(guide_text)
            campaign.brand_rules = rules
            campaign.agent_traces.append(asdict(trace))
            return self._transition(
                campaign,
                CampaignStatus.BRAND_RULES_PENDING_APPROVAL,
                "brand_rules.extracted",
                {"confidence": rules.confidence, "warnings": rules.warnings},
            )
        finally:
            trace_id_var.reset(token)

    def attach_asset(self, tenant_id: str, campaign_id: str, asset: AssetRecord) -> Campaign:
        campaign = self.repository.get(tenant_id, campaign_id)
        if campaign.status not in {
            CampaignStatus.CREATED,
            CampaignStatus.ASSETS_PROCESSING,
            CampaignStatus.BRAND_RULES_PENDING_APPROVAL,
        }:
            raise InvalidTransitionError("assets cannot be changed after planning begins")
        expected = campaign.version
        campaign.assets.append(asset)
        campaign.updated_at = utc_now()
        return self._save_with_event(
            campaign,
            expected,
            "asset.normalized",
            {"asset_id": asset.id, "kind": asset.kind},
        )

    def review_brand_rules(
        self,
        tenant_id: str,
        campaign_id: str,
        reviewer_id: str,
        reviewer_role: str,
        decision: ApprovalDecision,
        comments: str = "",
        corrections: dict[str, Any] | None = None,
        reason_codes: list[str] | None = None,
    ) -> Campaign:
        campaign = self.repository.get(tenant_id, campaign_id)
        if campaign.status != CampaignStatus.BRAND_RULES_PENDING_APPROVAL:
            raise InvalidTransitionError("brand rules are not awaiting review")
        assert campaign.brand_rules is not None
        expected = campaign.version
        if corrections:
            self._apply_rule_corrections(campaign, corrections)
        campaign.approvals.append(
            self._approval(
                campaign,
                ApprovalGate.BRAND_RULES,
                decision,
                reviewer_id,
                reviewer_role,
                comments,
                reason_codes,
            )
        )
        if decision != ApprovalDecision.APPROVED:
            campaign.updated_at = utc_now()
            return self._save_with_event(
                campaign,
                expected,
                "brand_rules.changes_requested",
                {"comments": comments},
            )
        plan, trace = self.planner.run(campaign.brief, campaign.brand_rules)
        campaign.plan = plan
        campaign.agent_traces.append(asdict(trace))
        return self._transition_from_version(
            campaign,
            expected,
            CampaignStatus.PLAN_PENDING_APPROVAL,
            "brand_rules.approved",
            {"reviewer_id": reviewer_id, "plan_revision": plan.revision},
        )

    def review_plan(
        self,
        tenant_id: str,
        campaign_id: str,
        reviewer_id: str,
        reviewer_role: str,
        decision: ApprovalDecision,
        comments: str = "",
        reason_codes: list[str] | None = None,
    ) -> Campaign:
        campaign = self.repository.get(tenant_id, campaign_id)
        if campaign.status != CampaignStatus.PLAN_PENDING_APPROVAL:
            raise InvalidTransitionError("campaign plan is not awaiting review")
        expected = campaign.version
        campaign.approvals.append(
            self._approval(
                campaign,
                ApprovalGate.PLAN,
                decision,
                reviewer_id,
                reviewer_role,
                comments,
                reason_codes,
            )
        )
        if decision != ApprovalDecision.APPROVED:
            assert campaign.brand_rules is not None
            plan, trace = self.planner.run(campaign.brief, campaign.brand_rules, comments)
            campaign.plan = plan
            campaign.agent_traces.append(asdict(trace))
            campaign.updated_at = utc_now()
            return self._save_with_event(
                campaign,
                expected,
                "plan.changes_requested",
                {"comments": comments},
            )
        campaign = self._transition_from_version(
            campaign,
            expected,
            CampaignStatus.GENERATING,
            "plan.approved",
            {"reviewer_id": reviewer_id},
        )
        return self._generate_and_rank(campaign)

    def select_variant(
        self,
        tenant_id: str,
        campaign_id: str,
        reviewer_id: str,
        reviewer_role: str,
        variant_id: str,
        reason_code: str,
        explanation: str,
    ) -> Campaign:
        campaign = self.repository.get(tenant_id, campaign_id)
        if campaign.status != CampaignStatus.VARIANTS_PENDING_APPROVAL:
            raise InvalidTransitionError("campaign variants are not awaiting selection")
        if variant_id not in {variant.id for variant in campaign.variants}:
            raise ValidationError("selected variant does not belong to this campaign")
        expected = campaign.version
        rejected = [variant.id for variant in campaign.variants if variant.id != variant_id]
        variants_by_id = {variant.id: variant for variant in campaign.variants}
        preferred = variants_by_id[variant_id]
        campaign.selected_variant_id = variant_id
        campaign.feedback.append(
            PreferenceFeedback(
                id=f"fb_{uuid4().hex[:16]}",
                reviewer_id=reviewer_id,
                preferred_variant_id=variant_id,
                rejected_variant_ids=rejected,
                reason_code=reason_code,
                explanation=explanation,
                preferred_features=_critic_features(preferred),
                rejected_features={
                    rejected_id: _critic_features(variants_by_id[rejected_id])
                    for rejected_id in rejected
                },
                display_ranks={
                    variant.id: variant.rank or index + 1
                    for index, variant in enumerate(campaign.variants)
                },
                presentation_order=[variant.id for variant in campaign.variants],
                brand=campaign.brief.product_name,
                campaign_category=_campaign_category(campaign),
                brief_fingerprint=_brief_fingerprint(campaign.brief),
            )
        )
        campaign.approvals.append(
            self._approval(
                campaign,
                ApprovalGate.VARIANT,
                ApprovalDecision.APPROVED,
                reviewer_id,
                reviewer_role,
                explanation,
                [reason_code],
            )
        )
        return self._transition_from_version(
            campaign,
            expected,
            CampaignStatus.FINAL_APPROVAL,
            "variant.selected",
            {"variant_id": variant_id, "reason_code": reason_code},
        )

    def review_final(
        self,
        tenant_id: str,
        campaign_id: str,
        reviewer_id: str,
        reviewer_role: str,
        decision: ApprovalDecision,
        comments: str = "",
        reason_codes: list[str] | None = None,
    ) -> Campaign:
        campaign = self.repository.get(tenant_id, campaign_id)
        if campaign.status != CampaignStatus.FINAL_APPROVAL:
            raise InvalidTransitionError("campaign is not awaiting final approval")
        expected = campaign.version
        campaign.approvals.append(
            self._approval(
                campaign,
                ApprovalGate.FINAL,
                decision,
                reviewer_id,
                reviewer_role,
                comments,
                reason_codes,
            )
        )
        if decision != ApprovalDecision.APPROVED:
            assert campaign.plan is not None
            campaign.plan.revision += 1
            campaign = self._transition_from_version(
                campaign,
                expected,
                CampaignStatus.REVISING,
                "final.changes_requested",
                {"comments": comments},
            )
            return self._generate_and_rank(campaign, comments)
        campaign = self._transition_from_version(
            campaign,
            expected,
            CampaignStatus.EXPORTING,
            "final.approved",
            {"reviewer_id": reviewer_id},
        )
        expected = campaign.version
        campaign.export = self.exporter.export(campaign)
        return self._transition_from_version(
            campaign,
            expected,
            CampaignStatus.COMPLETED,
            "campaign.exported",
            {"manifest_key": campaign.export.object_key},
        )

    def get_campaign(self, tenant_id: str, campaign_id: str) -> Campaign:
        return self.repository.get(tenant_id, campaign_id)

    def list_campaigns(self, tenant_id: str) -> list[Campaign]:
        return self.repository.list(tenant_id)

    def search_retrieval_text(
        self,
        tenant_id: str,
        campaign_id: str,
        query: str,
        *,
        limit: int = 10,
    ) -> list[SearchResult]:
        return self._retrieval().search_text(
            tenant_id, campaign_id, query, limit=limit
        )

    def search_retrieval_image(
        self,
        tenant_id: str,
        campaign_id: str,
        image_bytes: bytes,
        *,
        limit: int = 10,
    ) -> list[SearchResult]:
        return self._retrieval().search_image(
            tenant_id, campaign_id, image_bytes, limit=limit
        )

    def retrieval_status(
        self, tenant_id: str, campaign_id: str
    ) -> RetrievalStatusSummary:
        return self._retrieval().status(tenant_id, campaign_id)

    def backfill_retrieval(
        self, tenant_id: str, campaign_id: str | None = None
    ) -> list[IndexingSummary]:
        return self._retrieval().backfill(tenant_id, campaign_id)

    def curate_preference_feedback(
        self,
        tenant_id: str,
        campaign_id: str,
        feedback_id: str,
        *,
        curator_id: str,
        curation_status: str,
        dataset_version: str,
    ) -> Campaign:
        if curation_status not in {"curated", "rejected"}:
            raise ValidationError("curation status must be curated or rejected")
        if not curator_id.strip() or not dataset_version.strip():
            raise ValidationError("curator identity and dataset version are required")
        campaign = self.repository.get(tenant_id, campaign_id)
        feedback = next((item for item in campaign.feedback if item.id == feedback_id), None)
        if feedback is None:
            raise ValidationError("preference feedback does not belong to this campaign")
        expected = campaign.version
        feedback.curation_status = curation_status
        feedback.curated = curation_status == "curated"
        feedback.curated_by = curator_id
        feedback.curated_at = utc_now()
        feedback.dataset_version = dataset_version[:100]
        campaign.updated_at = utc_now()
        return self._save_with_event(
            campaign,
            expected,
            "preference.curated",
            {
                "feedback_id": feedback.id,
                "curation_status": curation_status,
                "curated_by": curator_id,
                "dataset_version": feedback.dataset_version,
            },
        )

    def load_design(
        self, tenant_id: str, campaign_id: str, channel: str
    ) -> DesignSnapshot:
        campaign = self.repository.get(tenant_id, campaign_id)
        if campaign.status not in {CampaignStatus.FINAL_APPROVAL, CampaignStatus.COMPLETED}:
            raise InvalidTransitionError(
                "designs are available only during or after final approval"
            )
        bootstrap_svg = self.exporter.render_channel(campaign, channel)
        if campaign.export is not None and channel in campaign.export.formats:
            bootstrap_svg = self.exporter.object_store.get(
                campaign.export.formats[channel]
            ).decode("utf-8")
        return self.editor.load(campaign, channel, bootstrap_svg)

    def save_design(
        self,
        tenant_id: str,
        campaign_id: str,
        channel: str,
        *,
        layer_document: Any,
        fabric_json: dict[str, Any],
        svg: str,
        preview_png: bytes | None,
        expected_revision: int,
        created_by: str,
        editor: str = "fabric",
        editor_version: str = "unknown",
    ) -> Campaign:
        campaign = self.repository.get(tenant_id, campaign_id)
        if campaign.status not in {CampaignStatus.FINAL_APPROVAL, CampaignStatus.COMPLETED}:
            raise InvalidTransitionError("designs can be saved only during or after final approval")
        expected_campaign_version = campaign.version
        revision = self.editor.save(
            campaign,
            channel,
            layer_document=layer_document,
            fabric_json=fabric_json,
            svg=svg,
            preview_png=preview_png,
            expected_revision=expected_revision,
            created_by=created_by,
            editor=editor,
            editor_version=editor_version,
        )
        campaign.designs.setdefault(revision.channel.value, []).append(revision)
        campaign.export = None
        payload = {
            "channel": revision.channel.value,
            "design_revision_id": revision.id,
            "revision": revision.revision,
            "created_by": revision.created_by,
        }
        if campaign.status == CampaignStatus.COMPLETED:
            return self._transition_from_version(
                campaign,
                expected_campaign_version,
                CampaignStatus.FINAL_APPROVAL,
                "design.edited",
                payload,
            )
        campaign.updated_at = utc_now()
        return self._save_with_event(
            campaign,
            expected_campaign_version,
            "design.edited",
            payload,
        )

    def events(self, tenant_id: str, campaign_id: str) -> list[OutboxEvent]:
        self.repository.get(tenant_id, campaign_id)
        return self.repository.events(tenant_id, campaign_id)

    def cancel(self, tenant_id: str, campaign_id: str, reviewer_id: str) -> Campaign:
        campaign = self.repository.get(tenant_id, campaign_id)
        return self._transition(
            campaign,
            CampaignStatus.CANCELLED,
            "campaign.cancelled",
            {"reviewer_id": reviewer_id},
        )

    def _generate_and_rank(self, campaign: Campaign, revision_note: str = "") -> Campaign:
        assert campaign.brand_rules is not None and campaign.plan is not None
        brand_rules = campaign.brand_rules
        plan = campaign.plan
        if campaign.status == CampaignStatus.REVISING:
            campaign = self._transition(
                campaign,
                CampaignStatus.GENERATING,
                "revision.started",
                {"note": revision_note},
            )
        try:
            reference_context: list[dict[str, object]] = []
            if self.retrieval is not None:
                query = (
                    f"{campaign.brief.product_name}. {campaign.brief.objective}. "
                    f"Audience: {campaign.brief.audience}. "
                    f"Visual direction: {plan.visual_direction}."
                )
                reference_context, retrieval_trace = self.retrieval.trace_context(
                    campaign.tenant_id, campaign.id, query, limit=5
                )
                campaign.agent_traces.append(retrieval_trace)
            campaign.model_manifest = self.creative.provider_manifest()
            with Timer(metrics, "brandforge_agent_duration_seconds", agent="creative_studio"):
                variants, creative_trace = self.creative.run(
                    campaign.id,
                    campaign.brief,
                    brand_rules,
                    plan,
                    revision_note=revision_note,
                    reference_context=reference_context,
                )
            campaign.agent_traces.append(asdict(creative_trace))
            campaign.total_cost_usd = round(campaign.total_cost_usd + creative_trace.cost_usd, 6)
            metrics.increment(
                "brandforge_model_cost_usd_total",
                amount=creative_trace.cost_usd,
                provider=self.creative.gateway.provider.name,
            )
            campaign = self._transition(
                campaign,
                CampaignStatus.EVALUATING,
                "variants.generated",
                {"candidate_count": len(variants)},
            )
            with Timer(metrics, "brandforge_agent_duration_seconds", agent="multimodal_reranker"):
                ranked, ranking_trace = self.reranker.run(
                    campaign.brief, brand_rules, variants, top_k=3
                )
            campaign.agent_traces.append(asdict(ranking_trace))
            visual_scores: dict[str, dict[str, float]] = {}
            for variant in ranked:
                image, scores, visual_trace = self.creative.render_and_score(
                    campaign.id, campaign.brief, brand_rules, variant
                )
                variant.provider_asset_id = (
                    str(image["asset_id"]) if image.get("asset_id") is not None else None
                )
                variant.provider_asset_url = (
                    str(image["asset_url"]) if image.get("asset_url") else None
                )
                variant.asset_object_key = self.exporter.store_generated_image(
                    campaign, variant.id, image
                )
                if scores:
                    visual_scores[variant.id] = scores
                campaign.agent_traces.append(asdict(visual_trace))
                campaign.total_cost_usd = round(campaign.total_cost_usd + visual_trace.cost_usd, 6)
                metrics.increment(
                    "brandforge_model_cost_usd_total",
                    amount=visual_trace.cost_usd,
                    provider=self.creative.gateway.provider.name,
                )
            if visual_scores:
                ranked, vision_ranking_trace = self.reranker.run(
                    campaign.brief,
                    brand_rules,
                    ranked,
                    top_k=3,
                    external_visual_scores=visual_scores,
                )
                campaign.agent_traces.append(asdict(vision_ranking_trace))
            campaign.variants = ranked
            campaign.selected_variant_id = None
            return self._transition(
                campaign,
                CampaignStatus.VARIANTS_PENDING_APPROVAL,
                "variants.ranked",
                {"recommended": ranked[0].id if ranked else None},
            )
        except Exception as error:
            if campaign.status in {CampaignStatus.GENERATING, CampaignStatus.EVALUATING}:
                self._transition(
                    campaign,
                    CampaignStatus.FAILED_RETRYABLE,
                    "workflow.failed_retryable",
                    {"error_type": type(error).__name__},
                )
            raise

    def _retrieval(self) -> MultimodalRetrievalService:
        if self.retrieval is None:
            raise ValidationError("multimodal retrieval is disabled")
        return self.retrieval

    def _transition(
        self,
        campaign: Campaign,
        target: CampaignStatus,
        event_type: str,
        payload: dict[str, Any],
    ) -> Campaign:
        return self._transition_from_version(
            campaign, campaign.version, target, event_type, payload
        )

    def _transition_from_version(
        self,
        campaign: Campaign,
        expected_version: int,
        target: CampaignStatus,
        event_type: str,
        payload: dict[str, Any],
    ) -> Campaign:
        assert_transition(campaign.status, target)
        previous = campaign.status
        campaign.status = target
        campaign.updated_at = utc_now()
        saved = self._save_with_event(
            campaign,
            expected_version,
            event_type,
            {**payload, "from": previous, "to": target},
        )
        metrics.increment("brandforge_workflow_transitions_total", state=target.value)
        return saved

    def _save_with_event(
        self,
        campaign: Campaign,
        expected_version: int,
        event_type: str,
        payload: dict[str, Any],
    ) -> Campaign:
        event = OutboxEvent.create(campaign.tenant_id, campaign.id, event_type, payload)
        return self.repository.save_with_event(
            campaign,
            event,
            expected_version,
        )

    @staticmethod
    def _approval(
        campaign: Campaign,
        gate: ApprovalGate,
        decision: ApprovalDecision,
        reviewer_id: str,
        reviewer_role: str,
        comments: str,
        reason_codes: list[str] | None,
    ) -> ApprovalRecord:
        if not reviewer_id.strip():
            raise ValidationError("reviewer identity is required")
        return ApprovalRecord(
            id=f"apr_{uuid4().hex[:16]}",
            gate=gate,
            decision=decision,
            reviewer_id=reviewer_id,
            reviewer_role=reviewer_role,
            artifact_version=campaign.version,
            comments=comments[:1000],
            reason_codes=(reason_codes or [])[:10],
        )
    @staticmethod
    def _apply_rule_corrections(campaign: Campaign, corrections: dict[str, Any]) -> None:
        assert campaign.brand_rules is not None
        allowed = {
            "colors",
            "fonts",
            "tone",
            "prohibited_terms",
            "required_disclaimers",
            "logo_clear_space_px",
            "allowed_logo_backgrounds",
        }
        unexpected = set(corrections) - allowed
        if unexpected:
            raise ValidationError(f"unsupported brand-rule fields: {sorted(unexpected)}")
        for field_name, value in corrections.items():
            if field_name == "logo_clear_space_px":
                value = max(0, min(512, int(value)))
            elif not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValidationError(f"{field_name} must be a list of strings")
            elif len(value) > 50 or any(len(item) > 200 for item in value):
                raise ValidationError(f"{field_name} exceeds the correction limits")
            elif field_name == "colors":
                if len(value) > 12 or not all(
                    re.fullmatch(r"#[0-9A-Fa-f]{6}", item) for item in value
                ):
                    raise ValidationError("colors must contain at most 12 six-digit hex values")
                value = list(dict.fromkeys(item.upper() for item in value))
            else:
                value = list(dict.fromkeys(item.strip() for item in value if item.strip()))
            setattr(campaign.brand_rules, field_name, value)
        campaign.brand_rules.version += 1


def _critic_features(variant: Any) -> dict[str, float]:
    fields = (
        "brief_alignment",
        "visual_alignment",
        "copy_image_consistency",
        "visual_quality",
        "brand_compliance",
        "accessibility",
        "claims_safety",
    )
    return {field: float(getattr(variant.scores, field)) for field in fields}


def _brief_fingerprint(brief: CampaignBrief) -> str:
    payload = json.dumps(asdict(brief), separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _campaign_category(campaign: Campaign) -> str:
    objective = campaign.brief.objective.lower()
    for category in ("launch", "awareness", "conversion", "retention", "event"):
        if category in objective:
            return category
    return "general"
