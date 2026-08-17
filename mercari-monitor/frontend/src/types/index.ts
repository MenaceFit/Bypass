// Mirrors app/api/schemas.py. Kept as plain interfaces (no runtime
// validation library) since this is a trusted, same-origin local backend.

export type KeywordStatus = "ACTIVE" | "PAUSED" | "THROTTLED" | "DEGRADED" | "BACKOFF" | "ERROR";
export type DiscordStatus = "PENDING" | "SENT" | "FAILED";
export type SortOption = "newest" | "oldest" | "price_low" | "price_high" | "detection_fastest";

export interface Search {
  id: number;
  keyword: string;
  active: boolean;
  status: KeywordStatus;
  scan_interval: number;
  discord_enabled: boolean;
  min_price: number | null;
  max_price: number | null;
  category: string | null;
  brand: string | null;
  size: string | null;
  condition: string | null;
  location: string | null;
  sort: SortOption;
  include_keywords: string[];
  exclude_keywords: string[];
  consecutive_failures: number;
  last_scan_at: string | null;
  next_scan_at: string | null;
  last_scan_duration_ms: number | null;
  backoff_until: string | null;
  last_error_message: string | null;
  created_at: string;
  updated_at: string;
  new_today: number;
  total_listings: number;
}

export interface SearchWriteRequest {
  keyword: string;
  scan_interval?: number | null;
  discord_enabled: boolean;
  min_price?: number | null;
  max_price?: number | null;
  category?: string | null;
  brand?: string | null;
  size?: string | null;
  condition?: string | null;
  location?: string | null;
  sort: SortOption;
  include_keywords: string[];
  exclude_keywords: string[];
}

export interface Listing {
  id: number;
  external_id: string;
  title: string | null;
  description: string | null;
  price: number | null;
  currency: string;
  brand: string | null;
  category: string | null;
  size: string | null;
  condition: string | null;
  item_status: string | null;
  seller_username: string | null;
  seller_id: string | null;
  image_url: string | null;
  listing_url: string;
  created_at_source: string | null;
  detected_at: string;
  detection_latency_ms: number | null;
  created_at_db: string;
  matched_keywords: string[];
  discord_status: DiscordStatus | null;
}

export interface PaginatedListings {
  items: Listing[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ListingFilters {
  keyword_id?: number;
  brand?: string;
  size?: string;
  condition?: string;
  min_price?: number;
  max_price?: number;
  seller?: string;
  discord_status?: DiscordStatus;
  sort?: SortOption;
  page?: number;
  page_size?: number;
}

export interface Stats {
  listings_today: number;
  listings_this_week: number;
  listings_this_month: number;
  total_listings: number;
  avg_detection_latency_ms: number | null;
  fastest_detection_ms: number | null;
  slowest_detection_ms: number | null;
  most_active_keyword: string | null;
  most_detected_brand: string | null;
  average_price: number | null;
  discord_sent: number;
  discord_failed: number;
  discord_pending: number;
  total_requests: number;
  successful_requests: number;
  failed_requests: number;
  http_429_count: number;
  average_response_time_ms: number | null;
}

export type LogLevel = "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";

export interface LogEntry {
  timestamp: string;
  level: LogLevel;
  logger: string;
  message: string;
}

export interface Settings {
  app_host: string;
  app_port: number;
  default_scan_interval: number;
  min_scan_interval: number;
  max_concurrent_requests: number;
  min_request_interval_ms: number;
  request_timeout: number;
  retry_max_attempts: number;
  discord_configured: boolean;
  discord_webhook_masked: string | null;
  log_level: string;
  database_url: string;
  archive_after_days: number;
  first_run_mode: "import_silent" | "treat_as_new";
  theme: "dark" | "light";
  sound_notifications_enabled: boolean;
  desktop_notifications_enabled: boolean;
}

export interface SettingsUpdateRequest {
  theme?: "dark" | "light";
  sound_notifications_enabled?: boolean;
  desktop_notifications_enabled?: boolean;
  first_run_mode?: "import_silent" | "treat_as_new";
}

export interface HealthStatus {
  status: string;
  database: boolean;
  mercari: boolean;
  discord: boolean;
  websocket: boolean;
}

export interface SystemStatus {
  source_available: boolean;
  source_status: "ONLINE" | "THROTTLED" | "DEGRADED";
  source_reason: string | null;
  active_workers: number;
  globally_paused: boolean;
  websocket_connections: number;
}

export interface MessageResponse {
  success: boolean;
  message: string;
}

export interface DiscordTestResponse {
  success: boolean;
  message: string;
}

// --- WebSocket event payloads ------------------------------------------
export interface WsNewListingEvent {
  type: "new_listing";
  listing: Listing & { keyword: string; keyword_id: number };
}

export interface WsScanEvent {
  type: "scan_started" | "scan_finished";
  keyword_id: number;
  keyword?: string;
  success?: boolean;
  results_count?: number;
  new_listings_count?: number;
}

export interface WsKeywordUpdatedEvent {
  type: "keyword_updated";
  keyword_id: number;
  status: KeywordStatus;
  next_scan_at: string;
}

export interface WsSystemStatusEvent extends SystemStatus {
  type: "system_status";
}

export interface WsErrorEvent {
  type: "error";
  keyword_id?: number;
  reason: string;
  status?: string;
}

export type WsEvent =
  | WsNewListingEvent
  | WsScanEvent
  | WsKeywordUpdatedEvent
  | WsSystemStatusEvent
  | WsErrorEvent;
