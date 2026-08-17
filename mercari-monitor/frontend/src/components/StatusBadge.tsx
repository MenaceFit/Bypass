const STATUS_STYLES: Record<string, { color: string; label: string }> = {
  ACTIVE: { color: "var(--color-online)", label: "ACTIVE" },
  ONLINE: { color: "var(--color-online)", label: "ONLINE" },
  PAUSED: { color: "var(--color-text-dim)", label: "PAUSED" },
  NOT_CONFIGURED: { color: "var(--color-text-dim)", label: "NOT CONFIGURED" },
  THROTTLED: { color: "var(--color-warning)", label: "THROTTLED" },
  DEGRADED: { color: "var(--color-degraded)", label: "DEGRADED" },
  BACKOFF: { color: "var(--color-degraded)", label: "BACKOFF" },
  ERROR: { color: "var(--color-danger)", label: "ERROR" },
  SENT: { color: "var(--color-online)", label: "SENT" },
  PENDING: { color: "var(--color-warning)", label: "PENDING" },
  FAILED: { color: "var(--color-danger)", label: "FAILED" },
};

export function StatusBadge({ status, pulse = false }: { status: string; pulse?: boolean }) {
  const style = STATUS_STYLES[status] ?? { color: "var(--color-text-dim)", label: status };
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium tracking-wide">
      <span
        className={`status-dot ${pulse ? "animate-pulse-fade" : ""}`}
        style={{ backgroundColor: style.color }}
      />
      <span style={{ color: style.color }}>{style.label}</span>
    </span>
  );
}
