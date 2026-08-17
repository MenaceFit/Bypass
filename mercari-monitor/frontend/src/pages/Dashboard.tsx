import { useEffect, useState } from "react";
import { Pause, Play, Radio } from "lucide-react";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";
import { EmptyState, StatTile } from "../components/Shared";
import { ListingCard } from "../components/ListingCard";
import { StatusBadge } from "../components/StatusBadge";
import type { HealthStatus, Stats } from "../types";

export function Dashboard() {
  const { systemStatus, liveFeed, pushToast } = useApp();
  const [stats, setStats] = useState<Stats | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    api.stats().then(setStats).catch(() => undefined);
    api.health().then(setHealth).catch(() => undefined);
  };

  useEffect(() => {
    refresh();
    const interval = window.setInterval(refresh, 15000);
    return () => window.clearInterval(interval);
  }, []);

  const handlePauseAll = async () => {
    setBusy(true);
    try {
      await api.pauseAll();
      pushToast("info", "Monitoring paused for all searches.");
    } catch {
      pushToast("error", "Failed to pause monitoring.");
    } finally {
      setBusy(false);
    }
  };

  const handleResumeAll = async () => {
    setBusy(true);
    try {
      await api.resumeAll();
      pushToast("info", "Monitoring resumed for all searches.");
    } catch {
      pushToast("error", "Failed to resume monitoring.");
    } finally {
      setBusy(false);
    }
  };

  const avgLatency =
    stats?.avg_detection_latency_ms != null ? `${(stats.avg_detection_latency_ms / 1000).toFixed(1)}s` : "—";

  return (
    <div>
      <div className="flex items-center justify-between px-6 py-5 border-b border-[var(--color-border)]">
        <div>
          <h1 className="text-lg font-semibold text-[var(--color-text)]">Mercari Monitor</h1>
          <div className="mt-1">
            <StatusBadge status={systemStatus?.source_available === false ? systemStatus.source_status : "ONLINE"} pulse />
          </div>
        </div>
        <button
          onClick={systemStatus?.globally_paused ? handleResumeAll : handlePauseAll}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-md border border-[var(--color-border)] px-3 py-1.5 text-sm text-[var(--color-text-muted)] hover:bg-[var(--color-surface-hover)] disabled:opacity-50"
        >
          {systemStatus?.globally_paused ? <Play size={14} /> : <Pause size={14} />}
          {systemStatus?.globally_paused ? "Resume All" : "Pause All"}
        </button>
      </div>

      <div className="p-6 space-y-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatTile label="Active Searches" value={systemStatus?.active_workers ?? "—"} />
          <StatTile label="Listings Today" value={stats?.listings_today ?? "—"} />
          <StatTile label="Average Detection" value={avgLatency} />
          <StatTile label="Discord Alerts" value={stats?.discord_sent ?? "—"} />
        </div>

        <div className="card p-4">
          <h2 className="text-sm font-semibold text-[var(--color-text)] mb-3">System Status</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <StatusRow label="Mercari source" status={systemStatus?.source_available === false ? systemStatus.source_status : "ONLINE"} />
            <StatusRow label="Database" status={health?.database ? "ONLINE" : "ERROR"} />
            <StatusRow label="WebSocket" status={health?.websocket ? "ONLINE" : "ERROR"} />
            <StatusRow label="Discord" status={health?.discord ? "ONLINE" : "NOT_CONFIGURED"} />
          </div>
          {systemStatus?.source_reason && (
            <p className="mt-3 text-xs text-[var(--color-warning)]">Reason: {systemStatus.source_reason}</p>
          )}
        </div>

        <div>
          <div className="flex items-center gap-2 mb-3">
            <Radio size={15} className="text-[var(--color-online)]" />
            <h2 className="text-sm font-semibold text-[var(--color-text)]">Live Feed</h2>
          </div>
          {liveFeed.length === 0 ? (
            <EmptyState
              icon={Radio}
              title="Waiting for new listings…"
              description="New Mercari listings matching your active searches will appear here in real time as soon as they're detected."
            />
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
              {liveFeed.map((listing) => (
                <ListingCard key={listing.id} listing={listing} keywordLabel={listing.keyword} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatusRow({ label, status }: { label: string; status: string }) {
  return (
    <div>
      <p className="text-[var(--color-text-dim)] text-xs mb-1">{label}</p>
      <StatusBadge status={status} />
    </div>
  );
}
