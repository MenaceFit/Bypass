import { useEffect, useState } from "react";
import { RefreshCw, Terminal } from "lucide-react";
import { api } from "../api/client";
import { PageHeader, EmptyState, LoadingState } from "../components/Shared";
import type { LogEntry, LogLevel } from "../types";

const LEVELS: LogLevel[] = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];

const LEVEL_COLORS: Record<LogLevel, string> = {
  DEBUG: "text-[var(--color-text-dim)]",
  INFO: "text-[var(--color-accent)]",
  WARNING: "text-[var(--color-warning)]",
  ERROR: "text-[var(--color-danger)]",
  CRITICAL: "text-[var(--color-danger)] font-bold",
};

export function Logs() {
  const [logs, setLogs] = useState<LogEntry[] | null>(null);
  const [level, setLevel] = useState<LogLevel | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const load = () => {
    api
      .logs(300, level ?? undefined)
      .then(setLogs)
      .catch(() => undefined);
  };

  useEffect(load, [level]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = window.setInterval(load, 3000);
    return () => window.clearInterval(interval);
  }, [autoRefresh, level]);

  return (
    <div>
      <PageHeader
        title="System Logs"
        action={
          <button
            onClick={() => setAutoRefresh((v) => !v)}
            className={`inline-flex items-center gap-1.5 rounded-md border border-[var(--color-border)] px-3 py-1.5 text-sm ${
              autoRefresh ? "text-[var(--color-online)]" : "text-[var(--color-text-muted)]"
            } hover:bg-[var(--color-surface-hover)]`}
          >
            <RefreshCw size={14} className={autoRefresh ? "animate-spin" : ""} style={{ animationDuration: "2s" }} />
            {autoRefresh ? "Live" : "Paused"}
          </button>
        }
      />

      <div className="px-6 pt-4 flex gap-1.5">
        <button
          onClick={() => setLevel(null)}
          className={`rounded-md px-2.5 py-1 text-xs border ${
            level === null ? "border-[var(--color-accent)] text-[var(--color-accent)]" : "border-[var(--color-border)] text-[var(--color-text-muted)]"
          }`}
        >
          ALL
        </button>
        {LEVELS.map((l) => (
          <button
            key={l}
            onClick={() => setLevel(l)}
            className={`rounded-md px-2.5 py-1 text-xs border ${
              level === l ? "border-[var(--color-accent)] text-[var(--color-accent)]" : "border-[var(--color-border)] text-[var(--color-text-muted)]"
            }`}
          >
            {l}
          </button>
        ))}
      </div>

      <div className="p-6">
        {logs === null ? (
          <LoadingState />
        ) : logs.length === 0 ? (
          <EmptyState icon={Terminal} title="No log entries yet" />
        ) : (
          <div className="card p-3 font-mono text-xs leading-relaxed max-h-[70vh] overflow-y-auto">
            {logs.map((entry, i) => (
              <div key={i} className="whitespace-pre-wrap break-words py-0.5">
                <span className="text-[var(--color-text-dim)]">{new Date(entry.timestamp).toLocaleTimeString()}</span>{" "}
                <span className={LEVEL_COLORS[entry.level]}>{entry.level.padEnd(8)}</span>{" "}
                <span className="text-[var(--color-text-dim)]">{entry.logger}</span>{" "}
                <span className="text-[var(--color-text)]">{entry.message}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
