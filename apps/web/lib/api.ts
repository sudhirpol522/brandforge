import type {
  Campaign,
  DesignResponse,
  EditorChannel,
  EventRecord,
  SaveDesignPayload
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const headers = {
  "Content-Type": "application/json",
  "X-Tenant-ID": "demo-studio",
  "X-User-ID": "creative-director",
  "X-User-Role": "campaign_owner"
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(API_URL + path, {
    ...init,
    headers: { ...headers, ...(init?.headers ?? {}) },
    cache: "no-store"
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    let body: Record<string, unknown> = {};
    try {
      body = text ? JSON.parse(text) as Record<string, unknown> : {};
    } catch {
      body = {};
    }
    const detail = body.detail;
    const validationMessage = Array.isArray(detail)
      ? detail
          .map((item) => {
            if (!item || typeof item !== "object") return String(item);
            const issue = item as { loc?: Array<string | number>; msg?: string };
            const location = issue.loc?.filter((part) => part !== "body").join(".");
            return [location, issue.msg].filter(Boolean).join(": ");
          })
          .filter(Boolean)
          .join("; ")
      : undefined;
    const nestedDetail =
      detail && typeof detail === "object" && !Array.isArray(detail)
        ? (detail as { message?: unknown }).message
        : undefined;
    const message =
      (typeof body.message === "string" && body.message) ||
      (typeof body.error === "string" && body.error) ||
      (typeof detail === "string" && detail) ||
      (typeof nestedDetail === "string" && nestedDetail) ||
      validationMessage ||
      text ||
      response.statusText ||
      `BrandForge request failed (${response.status})`;
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function createCampaign(payload: Record<string, unknown>): Promise<Campaign> {
  const data = await request<{ campaign: Campaign }>("/v1/campaigns", {
    method: "POST",
    headers: { "X-Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(payload)
  });
  return data.campaign;
}

export async function approve(
  campaignId: string,
  gate: "brand-rules" | "plan" | "final",
  decision: "approved" | "changes_requested",
  comments = ""
): Promise<Campaign> {
  const data = await request<{ campaign: Campaign }>(
    "/v1/campaigns/" + campaignId + "/approvals/" + gate,
    {
      method: "POST",
      body: JSON.stringify({
        decision,
        comments,
        reason_codes: comments ? ["reviewer_note"] : []
      })
    }
  );
  return data.campaign;
}

export async function selectVariant(
  campaignId: string,
  variantId: string,
  reasonCode: string,
  explanation: string
): Promise<Campaign> {
  const data = await request<{ campaign: Campaign }>("/v1/campaigns/" + campaignId + "/selection", {
    method: "POST",
    body: JSON.stringify({ variant_id: variantId, reason_code: reasonCode, explanation })
  });
  return data.campaign;
}

export async function getEvents(campaignId: string): Promise<EventRecord[]> {
  const data = await request<{ events: EventRecord[] }>("/v1/campaigns/" + campaignId + "/events");
  return data.events;
}

export function variantImageUrl(campaignId: string, variantId: string): string {
  return API_URL + "/v1/campaigns/" + campaignId + "/variants/" + variantId + "/image";
}

export function exportUrl(campaignId: string, artifact: string): string {
  return API_URL + "/v1/campaigns/" + campaignId + "/exports/" + artifact;
}

function designPath(campaignId: string, channel: EditorChannel): string {
  return `/v1/campaigns/${encodeURIComponent(campaignId)}/designs/${encodeURIComponent(channel)}`;
}

export function getDesign(
  campaignId: string,
  channel: EditorChannel
): Promise<DesignResponse> {
  return request<DesignResponse>(designPath(campaignId, channel));
}

export function saveDesign(
  campaignId: string,
  channel: EditorChannel,
  payload: SaveDesignPayload
): Promise<DesignResponse> {
  return request<DesignResponse>(designPath(campaignId, channel), {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export function designPreviewUrl(campaignId: string, channel: EditorChannel): string {
  return API_URL + designPath(campaignId, channel) + "/preview";
}
