"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { AdobeExpressButton } from "@/components/AdobeExpressButton";
import CampaignEditor from "@/components/editor/CampaignEditor";
import { ProgressRail } from "@/components/ProgressRail";
import { ScorePanel } from "@/components/ScorePanel";
import {
  approve,
  createCampaign,
  designPreviewUrl,
  exportUrl,
  getDesign,
  getEvents,
  saveDesign,
  selectVariant,
  variantImageUrl
} from "@/lib/api";
import {
  EDITOR_CHANNELS,
  type Campaign,
  type DesignResponse,
  type EditorChannel,
  type EventRecord,
  type SaveDesignPayload,
  type Variant
} from "@/lib/types";

const SAMPLE_GUIDE = [
  "Aster Run — Brand Guide",
  "Primary colors: #182A4D, #F4B942, #FFFFFF",
  "Typography: Montserrat for headlines; Inter for body copy.",
  "Voice: energetic, confident, premium, inclusive.",
  "Logo clear space: 32px. Use the logo on white or navy backgrounds.",
  "Do not use: cheap, guaranteed results, no pain.",
  "Required legal disclaimer: Product performance varies by user."
].join("\n");

const STATUS_LABELS: Record<string, string> = {
  brand_rules_pending_approval: "Brand rules need your approval",
  plan_pending_approval: "Campaign strategy needs your approval",
  generating: "Specialists are generating concepts",
  evaluating: "Critics are evaluating candidates",
  variants_pending_approval: "Choose the strongest direction",
  final_approval: "Final publication gate",
  completed: "Campaign package is ready"
};

const CHANNEL_PREVIEW_SIZES: Record<EditorChannel, { width: number; height: number }> = {
  email: { width: 1200, height: 600 },
  instagram: { width: 1080, height: 1350 },
  presentation: { width: 1920, height: 1080 },
  web: { width: 1440, height: 560 }
};

export default function Home() {
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reviewNote, setReviewNote] = useState("");

  useEffect(() => {
    if (!campaign) return;
    getEvents(campaign.id).then(setEvents).catch(() => undefined);
  }, [campaign]);

  async function act(operation: () => Promise<Campaign>) {
    setBusy(true);
    setError("");
    try {
      setCampaign(await operation());
      setReviewNote("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The workflow could not continue");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <header className="topbar">
        <div className="brand-mark">
          <i>BF</i>
          <span><strong>BrandForge</strong><small>Creative intelligence</small></span>
        </div>
        <div className="environment"><span /> <strong>Local</strong><b>Control room</b></div>
        <div className="topbar-actions">
          <span className="governed-badge"><i /> Human governed</span>
          <div className="avatar" aria-label="Creative director">CD</div>
        </div>
      </header>
      {!campaign ? (
        <LaunchPanel
          busy={busy}
          error={error}
          onCreate={(payload) => act(() => createCampaign(payload))}
        />
      ) : (
        <div className="workspace">
          <section className="main-column">
            <div className="campaign-heading">
              <div>
                <p className="eyebrow">Campaign / {campaign.id}</p>
                <h1>{campaign.name}</h1>
                <p>{campaign.brief.objective}</p>
                <div className="campaign-tags">
                  <span>{campaign.brief.product_name}</span>
                  <span>{campaign.brief.audience}</span>
                  <span>{campaign.brief.channels.length} channels</span>
                </div>
              </div>
              <span className={"status-pill " + campaign.status}>
                <i />
                {STATUS_LABELS[campaign.status] ?? campaign.status}
              </span>
            </div>
            <ProgressRail status={campaign.status} />
            {error && <div className="alert error">{error}</div>}
            <WorkflowGate
              campaign={campaign}
              busy={busy}
              reviewNote={reviewNote}
              setReviewNote={setReviewNote}
              onApprove={(gate, decision, note) =>
                act(() => approve(campaign.id, gate, decision, note))
              }
              onSelect={(variant, reason, note) =>
                act(() => selectVariant(campaign.id, variant.id, reason, note))
              }
              onCampaignUpdate={setCampaign}
            />
          </section>
          <aside className="side-column">
            <RunSummary campaign={campaign} events={events} />
          </aside>
        </div>
      )}
    </main>
  );
}

function LaunchPanel({
  busy,
  error,
  onCreate
}: {
  busy: boolean;
  error: string;
  onCreate: (payload: Record<string, unknown>) => void;
}) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    onCreate({
      name: data.get("name"),
      brief: {
        product_name: data.get("product"),
        objective: data.get("objective"),
        audience: data.get("audience"),
        channels: ["instagram", "email", "web", "presentation"],
        call_to_action: data.get("cta")
      },
      brand_guide_text: data.get("guide")
    });
  }
  return (
    <div className="launch-shell">
      <section className="launch-copy">
        <div className="launch-system"><i>BF</i><span>01</span><strong>Campaign intelligence system</strong></div>
        <h1>One brief.<br /><em>Three defensible directions.</em></h1>
        <p>
          Specialist agents create, critique and rank a coordinated campaign.
          You approve every consequential decision.
        </p>
        <div className="workflow-proof" aria-label="Workflow preview">
          <div><span><i>01</i><strong>Brand compiler</strong></span><b>93%</b></div>
          <div><span><i>02</i><strong>Creative studio</strong></span><b>3x</b></div>
          <div><span><i>03</i><strong>Vision reranker</strong></span><b>Top 1</b></div>
        </div>
      </section>
      <form className="launch-form" onSubmit={submit}>
        <GateTitle
          number="01"
          title="Start a campaign"
          subtitle="Use the sample or replace it with your own brand."
        />
        <label>
          Campaign name
          <input name="name" defaultValue="Aster Run — Campus Launch" required />
        </label>
        <div className="two-up">
          <label>
            Product
            <input name="product" defaultValue="Aster Run One" required />
          </label>
          <label>
            Audience
            <input
              name="audience"
              defaultValue="university students and first-time runners"
              required
            />
          </label>
        </div>
        <label>
          Objective
          <textarea
            name="objective"
            defaultValue="Launch a lightweight running shoe that makes everyday movement feel premium and achievable."
            required
          />
        </label>
        <label>
          Call to action
          <input name="cta" defaultValue="Find your pace" required />
        </label>
        <label>
          Brand guide
          <textarea className="guide" name="guide" defaultValue={SAMPLE_GUIDE} required />
        </label>
        {error && <div className="alert error">{error}</div>}
        <button className="button primary" disabled={busy}>
          {busy ? "Compiling brand rules…" : "Create campaign →"}
        </button>
        <p className="microcopy">
          No publishing occurs. Uploaded guidance is treated as untrusted data.
        </p>
      </form>
    </div>
  );
}

type GateName = "brand-rules" | "plan" | "final";
type GateDecision = "approved" | "changes_requested";

function WorkflowGate({
  campaign,
  busy,
  reviewNote,
  setReviewNote,
  onApprove,
  onSelect,
  onCampaignUpdate
}: {
  campaign: Campaign;
  busy: boolean;
  reviewNote: string;
  setReviewNote: (value: string) => void;
  onApprove: (gate: GateName, decision: GateDecision, note: string) => void;
  onSelect: (variant: Variant, reason: string, note: string) => void;
  onCampaignUpdate: (campaign: Campaign) => void;
}) {
  if (campaign.status === "brand_rules_pending_approval" && campaign.brand_rules) {
    const rules = campaign.brand_rules;
    return (
      <section className="gate-card">
        <GateTitle
          number="02"
          title="Confirm the brand compiler"
          subtitle={
            "Extraction confidence " + Math.round(rules.confidence * 100) + "% · version " + rules.version
          }
        />
        {rules.warnings.map((warning) => (
          <div className="alert warning" key={warning}>⚑ {warning}</div>
        ))}
        <div className="rule-grid">
          <RuleBlock title="Palette">
            <div className="swatches">
              {rules.colors.map((color) => (
                <span key={color} style={{ background: color }} title={color} />
              ))}
            </div>
            <small>{rules.colors.join(" · ")}</small>
          </RuleBlock>
          <RuleBlock title="Typography">
            <div className="tag-row">
              {rules.fonts.map((font) => <span key={font}>{font}</span>)}
            </div>
          </RuleBlock>
          <RuleBlock title="Voice">
            <div className="tag-row">
              {rules.tone.map((tone) => <span key={tone}>{tone}</span>)}
            </div>
          </RuleBlock>
          <RuleBlock title="Blocked language">
            <p>{rules.prohibited_terms.join(", ") || "No explicit terms extracted"}</p>
          </RuleBlock>
        </div>
        <ReviewActions
          busy={busy}
          note={reviewNote}
          setNote={setReviewNote}
          onApprove={() => onApprove("brand-rules", "approved", reviewNote)}
          onChanges={() => onApprove("brand-rules", "changes_requested", reviewNote)}
        />
      </section>
    );
  }

  if (campaign.status === "plan_pending_approval" && campaign.plan) {
    return (
      <section className="gate-card">
        <GateTitle
          number="03"
          title="Approve the campaign strategy"
          subtitle={"Plan revision " + campaign.plan.revision + " · generation has not started"}
        />
        <div className="strategy-grid">
          <RuleBlock title="Message architecture">
            {campaign.plan.key_messages.map((item) => <p key={item}>→ {item}</p>)}
          </RuleBlock>
          <RuleBlock title="Visual direction"><p>{campaign.plan.visual_direction}</p></RuleBlock>
        </div>
        <div className="deliverables">
          {Object.entries(campaign.plan.channel_deliverables).map(([channel, spec]) => (
            <div key={channel}><strong>{channel}</strong><span>{spec}</span></div>
          ))}
        </div>
        <ReviewActions
          busy={busy}
          note={reviewNote}
          setNote={setReviewNote}
          onApprove={() => onApprove("plan", "approved", reviewNote)}
          onChanges={() => onApprove("plan", "changes_requested", reviewNote)}
        />
      </section>
    );
  }

  if (["generating", "evaluating", "revising", "exporting"].includes(campaign.status)) {
    return (
      <section className="gate-card loading-card">
        <div className="loader" />
        <h2>Durable workflow in progress</h2>
        <p>Completed steps are preserved. Provider timeouts are retried within the campaign budget.</p>
      </section>
    );
  }

  if (campaign.status === "variants_pending_approval") {
    return <VariantGallery campaign={campaign} busy={busy} onSelect={onSelect} />;
  }

  if (campaign.status === "final_approval") {
    const selected = campaign.variants.find((item) => item.id === campaign.selected_variant_id);
    const hasEditedDesign = Object.values(campaign.designs ?? {}).some(
      (revisions) => (revisions?.length ?? 0) > 0
    );
    if (!selected) return <div className="alert error">The selected variant is unavailable.</div>;
    return (
      <section className="gate-card">
        <GateTitle
          number="05"
          title="Final approval"
          subtitle="Any edit after approval invalidates this gate"
        />
        {hasEditedDesign && (
          <div className="alert warning">
            A completed layout was edited in BrandForge. Review the revised design and renew final
            approval before publishing.
          </div>
        )}
        <div className="final-preview">
          <img
            src={variantImageUrl(campaign.id, selected.id)}
            alt={selected.alt_text}
            crossOrigin="anonymous"
          />
          <div>
            <p className="eyebrow">Selected direction</p>
            <h2>{selected.concept}</h2>
            <p>{selected.rationale}</p>
            <ScorePanel scores={selected.scores} />
          </div>
        </div>
        <ReviewActions
          busy={busy}
          note={reviewNote}
          setNote={setReviewNote}
          onApprove={() => onApprove("final", "approved", reviewNote)}
          onChanges={() => onApprove("final", "changes_requested", reviewNote)}
        />
      </section>
    );
  }

  if (campaign.status === "completed") {
    return <CompletedCampaign campaign={campaign} onCampaignUpdate={onCampaignUpdate} />;
  }

  return <section className="gate-card"><h2>{STATUS_LABELS[campaign.status] ?? campaign.status}</h2></section>;
}

function isEditorChannel(value: string): value is EditorChannel {
  return EDITOR_CHANNELS.includes(value as EditorChannel);
}

function CompletedCampaign({
  campaign,
  onCampaignUpdate
}: {
  campaign: Campaign;
  onCampaignUpdate: (campaign: Campaign) => void;
}) {
  const availableChannels = useMemo(() => {
    const exported = Object.keys(campaign.export?.formats ?? {}).filter(isEditorChannel);
    const brief = campaign.brief.channels.filter(isEditorChannel);
    const channels = exported.length > 0 ? exported : brief;
    return channels.length > 0 ? channels : [...EDITOR_CHANNELS];
  }, [campaign.brief.channels, campaign.export?.formats]);
  const [channel, setChannel] = useState<EditorChannel>(availableChannels[0]);
  const [editorOpen, setEditorOpen] = useState(false);
  const [bootstrap, setBootstrap] = useState<DesignResponse | null>(null);
  const [designLoading, setDesignLoading] = useState(false);
  const [designError, setDesignError] = useState("");
  const [currentPng, setCurrentPng] = useState<Blob | null>(null);

  const selected = campaign.variants.find((item) => item.id === campaign.selected_variant_id);
  const hasSavedPreview = (campaign.designs?.[channel]?.length ?? 0) > 0;
  const fallbackImage = selected ? variantImageUrl(campaign.id, selected.id) : "";
  const editorVisualImage = fallbackImage
    ? `${fallbackImage}?editor=${campaign.version}`
    : undefined;
  const previewDimensions = CHANNEL_PREVIEW_SIZES[channel];
  const previewAspectRatio = previewDimensions.width / previewDimensions.height;
  const savedPreviewImage = hasSavedPreview
    ? designPreviewUrl(campaign.id, channel)
    : "";
  const channelCopy = selected?.copy_by_channel[channel] ?? {};
  const previewHeadline = channelCopy.headline || selected?.concept || campaign.name;
  const previewBody = channelCopy.body || channelCopy.caption || "";
  const previewCta = channelCopy.cta || campaign.brief.call_to_action;
  const previewPrimary = /^#[0-9a-f]{6}$/i.test(selected?.palette[0] ?? "")
    ? selected!.palette[0]
    : "#182A4D";
  const previewSecondary = /^#[0-9a-f]{6}$/i.test(selected?.palette[1] ?? "")
    ? selected!.palette[1]
    : "#F4B942";

  useEffect(() => {
    if (!availableChannels.includes(channel)) setChannel(availableChannels[0]);
  }, [availableChannels, channel]);

  useEffect(() => {
    if (!editorOpen) return;
    let active = true;
    setDesignLoading(true);
    setDesignError("");
    setBootstrap(null);
    getDesign(campaign.id, channel)
      .then((response) => {
        if (active) setBootstrap(response);
      })
      .catch((caught) => {
        if (active) {
          setDesignError(caught instanceof Error ? caught.message : "The design could not be loaded.");
        }
      })
      .finally(() => {
        if (active) setDesignLoading(false);
      });
    return () => {
      active = false;
    };
  }, [campaign.id, channel, editorOpen]);

  function chooseChannel(nextChannel: EditorChannel) {
    if (editorOpen) return;
    setChannel(nextChannel);
    setCurrentPng(null);
    setDesignError("");
  }

  function openEditor() {
    setCurrentPng(null);
    setEditorOpen(true);
  }

  function save(payload: SaveDesignPayload) {
    return saveDesign(campaign.id, channel, payload);
  }

  if (editorOpen) {
    return (
      <section className="completed-editor-host" aria-label={`${channel} BrandForge editor`}>
        <div className="completed-editor-context">
          <div>
            <p className="eyebrow">Editing exported campaign</p>
            <strong>{channel}</strong>
            <span>Saving an edit reopens final approval.</span>
          </div>
          <div className="completed-channel-tabs" aria-label="Export channel">
            {availableChannels.map((item) => (
              <button
                type="button"
                key={item}
                className={item === channel ? "active" : ""}
                disabled
                title="Close the editor before switching channels"
              >
                {item}
              </button>
            ))}
          </div>
        </div>
        {designLoading && (
          <div className="completed-design-loading" role="status">
            <div className="loader" />
            <strong>Loading editable {channel} layers…</strong>
          </div>
        )}
        {designError && (
          <div className="completed-design-error" role="alert">
            <strong>Editor unavailable</strong>
            <p>{designError}</p>
            <button className="button ghost" type="button" onClick={() => setEditorOpen(false)}>
              Back to campaign package
            </button>
          </div>
        )}
        {bootstrap && !designLoading && (
          <CampaignEditor
            channel={channel}
            bootstrap={bootstrap}
            visualImageUrl={editorVisualImage}
            onSave={save}
            onSaved={(response) => onCampaignUpdate(response.campaign)}
            onClose={() => setEditorOpen(false)}
            onPngChange={setCurrentPng}
          />
        )}
      </section>
    );
  }

  return (
    <section className="gate-card complete-card completed-campaign">
      <div className="completed-hero">
        <div className="completed-copy">
          <span className="success-mark">✓</span>
          <p className="eyebrow">Export completed</p>
          <h2>Your campaign package is ready</h2>
          <p>
            Edit channel layouts in BrandForge, or download the original SVG package and
            provenance manifest.
          </p>
          <button className="button primary completed-edit-button" type="button" onClick={openEditor}>
            Edit in BrandForge →
          </button>
          {selected && (
            <div className="completed-secondary-action">
              <span>Optional external handoff</span>
              <AdobeExpressButton imageUrl={fallbackImage} assetBlob={currentPng} />
            </div>
          )}
        </div>
        {(savedPreviewImage || fallbackImage) && (
          <div className="completed-preview">
            <span>{channel} preview</span>
            <div
              className="completed-preview-frame"
              style={{
                aspectRatio: `${previewDimensions.width} / ${previewDimensions.height}`,
                maxWidth: `${Math.round(420 * previewAspectRatio)}px`
              }}
            >
              {savedPreviewImage ? (
                <img
                  src={savedPreviewImage}
                  alt={`${campaign.name} ${channel} design preview`}
                  crossOrigin="anonymous"
                />
              ) : (
                <>
                  <img
                    className="completed-preview-visual"
                    src={fallbackImage}
                    alt={selected?.alt_text ?? ""}
                    crossOrigin="anonymous"
                  />
                  <div
                    className="completed-preview-gradient"
                    style={{
                      background: `linear-gradient(135deg, ${previewPrimary}4D, ${previewSecondary}4D)`
                    }}
                    aria-hidden="true"
                  />
                  <div className="completed-preview-panel" aria-hidden="true" />
                  <div className="completed-preview-copy">
                    <span>{selected?.concept ?? campaign.name}</span>
                    <strong>{previewHeadline}</strong>
                    <p>{previewBody}</p>
                    <b style={{ color: previewPrimary }}>{previewCta}</b>
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="completed-channel-tabs" role="tablist" aria-label="Campaign channel">
        {availableChannels.map((item) => (
          <button
            type="button"
            role="tab"
            aria-selected={item === channel}
            className={item === channel ? "active" : ""}
            key={item}
            onClick={() => chooseChannel(item)}
          >
            {item}
          </button>
        ))}
      </div>

      <div className="export-list completed-exports">
        {Object.entries(campaign.export?.formats ?? {}).map(([exportChannel, key]) => (
          <a href={exportUrl(campaign.id, exportChannel)} key={key} download>
            <strong>{exportChannel}</strong><span>Download editable SVG ↗</span>
          </a>
        ))}
        <a href={exportUrl(campaign.id, "manifest")} download>
          <strong>manifest</strong><span>Download provenance JSON ↗</span>
        </a>
      </div>
    </section>
  );
}

function VariantGallery({
  campaign,
  busy,
  onSelect
}: {
  campaign: Campaign;
  busy: boolean;
  onSelect: (variant: Variant, reason: string, note: string) => void;
}) {
  const [selected, setSelected] = useState(campaign.variants[0]?.id);
  const [reason, setReason] = useState("brand_match");
  const [note, setNote] = useState(
    "Strongest balance of brand fit, visual quality and audience relevance."
  );
  const active = useMemo(
    () => campaign.variants.find((item) => item.id === selected),
    [campaign.variants, selected]
  );
  return (
    <section className="gate-card wide-gate">
      <GateTitle
        number="04"
        title="Ranked creative directions"
        subtitle="Vision scores and deterministic policy checks are shown separately"
      />
      <div className="variant-grid">
        {campaign.variants.map((variant) => (
          <button
            type="button"
            className={"variant-card " + (selected === variant.id ? "selected" : "")}
            key={variant.id}
            onClick={() => setSelected(variant.id)}
            aria-pressed={selected === variant.id}
          >
            <div className="rank-badge">#{variant.rank}</div>
            <img
              src={variantImageUrl(campaign.id, variant.id)}
              alt={variant.alt_text}
              crossOrigin="anonymous"
            />
            <div className="variant-body">
              <div className="variant-title">
                <h3>{variant.concept}</h3>
                <strong>{Math.round(variant.scores.final * 100)}</strong>
              </div>
              <p>{variant.rationale}</p>
              <ScorePanel scores={variant.scores} />
              {variant.violations.length > 0 && (
                <small className="violation">
                  {variant.violations.length} reviewer note
                  {variant.violations.length > 1 ? "s" : ""}
                </small>
              )}
            </div>
          </button>
        ))}
      </div>
      <div className="selection-bar">
        <label>
          Selection reason
          <select value={reason} onChange={(event) => setReason(event.target.value)}>
            <option value="brand_match">Brand match</option>
            <option value="visual_quality">Visual quality</option>
            <option value="brief_match">Brief match</option>
            <option value="audience_fit">Audience fit</option>
            <option value="accessibility">Accessibility</option>
            <option value="other">Other</option>
          </select>
        </label>
        <label>
          Reviewer note
          <input value={note} onChange={(event) => setNote(event.target.value)} />
        </label>
        <button
          className="button primary"
          disabled={busy || !active}
          onClick={() => active && onSelect(active, reason, note)}
        >
          {busy ? "Saving…" : "Select direction →"}
        </button>
      </div>
    </section>
  );
}

function ReviewActions({
  busy,
  note,
  setNote,
  onApprove,
  onChanges
}: {
  busy: boolean;
  note: string;
  setNote: (value: string) => void;
  onApprove: () => void;
  onChanges: () => void;
}) {
  return (
    <div className="review-actions">
      <label>
        Reviewer note
        <input
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Optional for approval; required for changes"
        />
      </label>
      <button className="button ghost" disabled={busy || note.trim().length < 2} onClick={onChanges}>
        Request changes
      </button>
      <button className="button primary" disabled={busy} onClick={onApprove}>
        {busy ? "Working…" : "Approve →"}
      </button>
    </div>
  );
}

function GateTitle({
  number,
  title,
  subtitle
}: {
  number: string;
  title: string;
  subtitle: string;
}) {
  return (
    <div className="form-heading">
      <span>{number}</span>
      <div><small>Human review gate</small><h2>{title}</h2><p>{subtitle}</p></div>
    </div>
  );
}

function RuleBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="rule-block"><small>{title}</small>{children}</div>;
}

function RunSummary({ campaign, events }: { campaign: Campaign; events: EventRecord[] }) {
  return (
    <>
      <section className="summary-card manifest-card">
        <div className="summary-heading"><div><p className="eyebrow">Run inspector</p><h2>Manifest</h2></div><span>Live</span></div>
        <div className="manifest-metrics">
          <div><small>Cost</small><strong>{"$"}{campaign.total_cost_usd.toFixed(3)}</strong></div>
          <div><small>Approvals</small><strong>{campaign.approvals.length}</strong></div>
          <div><small>Traces</small><strong>{campaign.agent_traces.length}</strong></div>
        </div>
        <dl className="manifest-meta">
          <div><dt>Trace</dt><dd>{campaign.trace_id.slice(0, 10)}…</dd></div>
          <div><dt>Version</dt><dd>v{campaign.version}</dd></div>
        </dl>
      </section>
      <section className="summary-card timeline">
        <div className="summary-heading"><h3>Decisions</h3><span>{events.length}</span></div>
        {events.slice().reverse().slice(0, 8).map((event) => (
          <div key={event.id}>
            <i />
            <span>
              <strong>{event.event_type.replaceAll(".", " ")}</strong>
              <small>{new Date(event.occurred_at).toLocaleTimeString()}</small>
            </span>
          </div>
        ))}
      </section>
      <section className="summary-card agents">
        <div className="summary-heading"><h3>Specialists</h3><span>{campaign.agent_traces.length}</span></div>
        {campaign.agent_traces.slice().reverse().slice(0, 6).map((trace, index) => (
          <details key={trace.agent + "-" + index}>
            <summary>
              <span>{trace.agent.replaceAll("_", " ")}</span>
              <small>{"$"}{trace.cost_usd.toFixed(3)}</small>
            </summary>
            <p>{trace.decision_summary}</p>
          </details>
        ))}
      </section>
    </>
  );
}
