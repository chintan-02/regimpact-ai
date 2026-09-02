import type { Change, ChangeDetail, Ingestion, Regulation, Source } from "./types";
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
