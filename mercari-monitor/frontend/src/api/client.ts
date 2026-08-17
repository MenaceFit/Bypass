import type {
  DiscordTestResponse,
  HealthStatus,
  Listing,
  ListingFilters,
  MessageResponse,
  PaginatedListings,
  Search,
  SearchWriteRequest,
  Settings,
  SettingsUpdateRequest,
  Stats,
  SystemStatus,
  LogEntry,
} from "../types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // response had no JSON body — fall back to statusText
    }
    throw new ApiError(response.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function toQueryString<T extends object>(params: T): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export const api = {
  health: () => request<HealthStatus>("/api/health"),
  monitoringStatus: () => request<SystemStatus>("/api/monitoring/status"),
  pauseAll: () => request<MessageResponse>("/api/monitoring/pause-all", { method: "POST" }),
  resumeAll: () => request<MessageResponse>("/api/monitoring/resume-all", { method: "POST" }),

  listSearches: () => request<Search[]>("/api/searches"),
  getSearch: (id: number) => request<Search>(`/api/searches/${id}`),
  createSearch: (body: SearchWriteRequest) =>
    request<Search>("/api/searches", { method: "POST", body: JSON.stringify(body) }),
  updateSearch: (id: number, body: SearchWriteRequest) =>
    request<Search>(`/api/searches/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteSearch: (id: number) => request<MessageResponse>(`/api/searches/${id}`, { method: "DELETE" }),
  pauseSearch: (id: number) => request<Search>(`/api/searches/${id}/pause`, { method: "POST" }),
  resumeSearch: (id: number) => request<Search>(`/api/searches/${id}/resume`, { method: "POST" }),
  exportSearches: () => request<unknown[]>("/api/searches/export"),
  importSearches: (searches: SearchWriteRequest[]) =>
    request<Search[]>("/api/searches/import", { method: "POST", body: JSON.stringify({ searches }) }),

  listListings: (filters: ListingFilters) =>
    request<PaginatedListings>(`/api/listings${toQueryString(filters)}`),
  getListing: (id: number) => request<Listing>(`/api/listings/${id}`),
  exportListingsCsvUrl: (filters: ListingFilters) => `/api/listings/export${toQueryString(filters)}`,
  archiveListings: (olderThanDays: number) =>
    request<MessageResponse>("/api/listings/archive", {
      method: "POST",
      body: JSON.stringify({ older_than_days: olderThanDays }),
    }),

  stats: () => request<Stats>("/api/stats"),
  logs: (limit = 200, level?: string) => request<LogEntry[]>(`/api/logs${toQueryString({ limit, level })}`),

  testDiscord: () => request<DiscordTestResponse>("/api/discord/test", { method: "POST" }),

  getSettings: () => request<Settings>("/api/settings"),
  updateSettings: (body: SettingsUpdateRequest) =>
    request<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(body) }),

  resetDatabase: (confirm: string) =>
    request<MessageResponse>("/api/database/reset", { method: "POST", body: JSON.stringify({ confirm }) }),
};
