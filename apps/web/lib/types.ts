export type CampaignStatus =
  | "created"
  | "assets_processing"
  | "brand_rules_pending_approval"
  | "plan_pending_approval"
  | "generating"
  | "evaluating"
  | "variants_pending_approval"
  | "revising"
  | "final_approval"
  | "exporting"
  | "completed"
  | "failed_retryable"
  | "failed_permanent"
  | "cancelled";

export type Scores = {
  brief_alignment: number;
  visual_alignment: number;
  copy_image_consistency: number;
  visual_quality: number;
  brand_compliance: number;
  accessibility: number;
  claims_safety: number;
  preference: number;
  diversity: number;
  final: number;
  scorer_mode: string;
};

export type Variant = {
  id: string;
  concept: string;
  rationale: string;
  visual_prompt: string;
  alt_text: string;
  palette: string[];
  copy_by_channel: Record<string, Record<string, string>>;
  scores: Scores;
  violations: string[];
  rank: number;
  asset_object_key?: string;
};

export type EditorChannel = "instagram" | "email" | "web" | "presentation";

export const EDITOR_CHANNELS: readonly EditorChannel[] = [
  "instagram",
  "email",
  "web",
  "presentation"
];

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type LayerType = "text" | "image" | "rect" | "ellipse" | "path" | "group";
export type ImageFitMode = "fit" | "fill" | "crop";

export type LayerTransform = {
  left: number;
  top: number;
  width: number;
  height: number;
  scaleX: number;
  scaleY: number;
  angle: number;
  skewX: number;
  skewY: number;
  flipX: boolean;
  flipY: boolean;
  originX: string;
  originY: string;
};

export type LayerAppearance = {
  opacity: number;
  visible: boolean;
  fill: JsonValue;
  stroke: JsonValue;
  strokeWidth: number;
  strokeDashArray: number[] | null;
  shadow: JsonValue;
};

export type CanonicalLayer = {
  id: string;
  name: string;
  type: LayerType;
  role?: string;
  imageFitMode?: ImageFitMode;
  assetKey?: string;
  brandLocked?: boolean;
  locked: boolean;
  transform: LayerTransform;
  appearance: LayerAppearance;
  text?: {
    value: string;
    fontFamily: string;
    fontSize: number;
    fontWeight: string | number;
    fontStyle: string;
    textAlign: string;
    lineHeight: number;
    charSpacing: number;
    underline: boolean;
    overline: boolean;
    linethrough: boolean;
    editable: boolean;
    direction: string;
    textBackgroundColor: string;
    styles: JsonValue;
  };
  image?: {
    src: string;
    crossOrigin: string | null;
    cropX: number;
    cropY: number;
    filters: JsonValue;
  };
  path?: {
    commands: JsonValue;
    fillRule: string;
  };
  radius?: { rx: number; ry: number };
  children?: CanonicalLayer[];
};

export type LayerDocument = {
  schema_version: 1;
  channel: EditorChannel;
  width: number;
  height: number;
  layers: CanonicalLayer[];
};

export type DesignRevisionMetadata = {
  id: string;
  channel: EditorChannel;
  revision: number;
  layer_document_key: string;
  fabric_json_key: string;
  svg_key: string;
  preview_png_key: string | null;
  editor: string;
  editor_version: string;
  created_by: string;
  created_at: string;
  hashes: Record<string, string>;
};

export type SaveDesignPayload = {
  channel?: EditorChannel;
  layer_document: LayerDocument;
  fabric_json: Record<string, JsonValue>;
  svg: string;
  preview_png_base64: string | null;
  expected_revision: number;
  editor_version: string;
};

export type Campaign = {
  id: string;
  name: string;
  status: CampaignStatus;
  brief: {
    product_name: string;
    objective: string;
    audience: string;
    channels: string[];
    call_to_action: string;
  };
  brand_rules?: {
    colors: string[];
    fonts: string[];
    tone: string[];
    prohibited_terms: string[];
    confidence: number;
    warnings: string[];
    version: number;
  };
  plan?: {
    key_messages: string[];
    visual_direction: string;
    channel_deliverables: Record<string, string>;
    claims_requiring_review: string[];
    success_criteria: string[];
    revision: number;
  };
  variants: Variant[];
  selected_variant_id?: string;
  approvals: Array<{
    id: string;
    gate: string;
    decision: string;
    reviewer_id: string;
    created_at: string;
  }>;
  agent_traces: Array<{
    agent: string;
    version: string;
    decision_summary: string;
    tool_calls: Array<Record<string, unknown>>;
    warnings: string[];
    cost_usd: number;
  }>;
  export?: {
    object_key: string;
    formats: Record<string, string>;
  };
  designs: Partial<Record<EditorChannel, DesignRevisionMetadata[]>>;
  total_cost_usd: number;
  trace_id: string;
  version: number;
};

export type DesignResponse = {
  campaign_id: string;
  campaign_version: number;
  revision: number;
  revision_metadata: DesignRevisionMetadata | null;
  layer_document: LayerDocument;
  fabric_json: Record<string, JsonValue>;
  svg: string;
  campaign: Campaign;
};

export type EventRecord = {
  id: string;
  event_type: string;
  payload: Record<string, unknown>;
  occurred_at: string;
};
