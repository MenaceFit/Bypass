import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { PageHeader, StatTile } from "../components/Shared";
import type { Stats } from "../types";

function formatMs(ms: number | null): string {
  if (ms == null) return "—";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s`;
}

export function Statistics() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    const load = () => api.stats().then(setStats).catch(() => undefined);
    load();
    const interval = window.setInterval(load, 15000);
    return () => window.clearInterval(interval);
  }, []);

  return (
    <div>
      <PageHeader title="Statistics" />
      <div className="p-6 space-y-6">
        <Section title="Detection volume">
          <StatTile label="Detected today" value={stats?.listings_today ?? "—"} />
          <StatTile label="Detected this week" value={stats?.listings_this_week ?? "—"} />
          <StatTile label="Detected this month" value={stats?.listings_this_month ?? "—"} />
          <StatTile label="Total listings" value={stats?.total_listings ?? "—"} />
        </Section>

        <Section title="Detection latency">
          <StatTile label="Average" value={formatMs(stats?.avg_detection_latency_ms ?? null)} />
          <StatTile label="Fastest" value={formatMs(stats?.fastest_detection_ms ?? null)} />
          <StatTile label="Slowest" value={formatMs(stats?.slowest_detection_ms ?? null)} />
        </Section>

        <Section title="Trends">
          <StatTile label="Most active keyword" value={stats?.most_active_keyword ?? "—"} />
          <StatTile label="Most detected brand" value={stats?.most_detected_brand ?? "—"} />
          <StatTile
            label="Average listing price"
            value={stats?.average_price != null ? `$${stats.average_price.toFixed(2)}` : "—"}
          />
        </Section>

        <Section title="Discord">
          <StatTile label="Sent" value={stats?.discord_sent ?? "—"} />
          <StatTile label="Pending" value={stats?.discord_pending ?? "—"} />
          <StatTile label="Failed" value={stats?.discord_failed ?? "—"} />
        </Section>

        <Section title="Network (since this process started)">
          <StatTile label="Total requests" value={stats?.total_requests ?? "—"} />
          <StatTile label="Successful" value={stats?.successful_requests ?? "—"} />
          <StatTile label="Failed" value={stats?.failed_requests ?? "—"} />
          <StatTile label="HTTP 429" value={stats?.http_429_count ?? "—"} />
          <StatTile label="Avg response time" value={formatMs(stats?.average_response_time_ms ?? null)} />
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h2 className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-dim)] mb-2.5">{title}</h2>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">{children}</div>
    </div>
  );
}
