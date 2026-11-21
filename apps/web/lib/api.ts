import type { Change, ChangeDetail, Ingestion, Obligation, Regulation, ReviewItem, ReviewQueue, Source } from "./types";
import { cookies } from "next/headers";

export type ApiResult<T> = { data: T; error: null } | { data: null; error: string };

const apiBase = process.env.REGIMPACT_API_BASE_URL ?? "http://localhost:8000";
export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  try {
    const token = (await cookies()).get("regimpact_access_token")?.value;
    const response = await fetch(`${apiBase}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      cache: "no-store",
    });
    if (!response.ok) {
      const requestId = response.headers.get("X-Request-ID");
      return {
        data: null,
        error: `API request failed (${response.status})${requestId ? ` · ${requestId}` : ""}`,
      };
    }
    return { data: (await response.json()) as T, error: null };
  } catch {
    return { data: null, error: "RegImpact API is unavailable. Check the API and database services." };
  }
}

const pageSize = 200;

export async function getObligations(versionId?: string): Promise<ApiResult<Obligation[]>> {
  const obligations: Obligation[] = [];
  const params = new URLSearchParams({ limit: String(pageSize) });
  if (versionId) params.set("version_id", versionId);
  for (let offset = 0; ; offset += pageSize) {
    params.set("offset", String(offset));
    const result = await apiGet<Obligation[]>(`/api/v1/obligations?${params}`);
    if (!result.data) return result;
    obligations.push(...result.data);
    if (result.data.length < pageSize) return { data: obligations, error: null };
  }
}

export async function getObligationReviews(): Promise<ApiResult<ReviewItem[]>> {
  const items: ReviewItem[] = [];
  for (let offset = 0; ; offset += pageSize) {
    const result = await apiGet<ReviewQueue>(`/api/v1/review-queue?limit=${pageSize}&offset=${offset}`);
    if (!result.data) return { data: null, error: result.error };
    items.push(...result.data.items);
    if (!result.data.items.length || items.length >= result.data.total) {
      return { data: items, error: null };
    }
  }
}

export async function getChangeRegister(selectedChangeId?: string) {
  const [regulations, changes, sources, ingestions] = await Promise.all([
    apiGet<Regulation[]>("/api/v1/regulations"),
    apiGet<Change[]>("/api/v1/changes?latest_only=true&limit=100"),
    apiGet<Source[]>("/api/v1/sources"),
    apiGet<Ingestion[]>("/api/v1/ingestions?limit=100"),
  ]);
  const selectedChange =
    changes.data?.find((change) => change.id === selectedChangeId) ?? changes.data?.[0];
  const selected = selectedChange
    ? await apiGet<ChangeDetail>(`/api/v1/changes/${selectedChange.id}`)
    : ({ data: null, error: null } satisfies ApiResult<ChangeDetail | null>);
  return { regulations, changes, sources, ingestions, selected };
}
