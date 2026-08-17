import type { LucideIcon } from "lucide-react";
import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";

export function PageHeader({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="flex items-center justify-between px-6 py-5 border-b border-[var(--color-border)]">
      <h1 className="text-lg font-semibold text-[var(--color-text)]">{title}</h1>
      {action}
    </div>
  );
}

export function EmptyState({ icon: Icon, title, description }: { icon: LucideIcon; title: string; description?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <Icon size={32} className="text-[var(--color-text-dim)] mb-3" />
      <p className="text-sm font-medium text-[var(--color-text-muted)]">{title}</p>
      {description && <p className="text-xs text-[var(--color-text-dim)] mt-1 max-w-sm">{description}</p>}
    </div>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-[var(--color-text-dim)]">
      <Loader2 size={16} className="animate-spin" />
      <span className="text-sm">{label}</span>
    </div>
  );
}

export function StatTile({
  label,
  value,
  sublabel,
}: {
  label: string;
  value: ReactNode;
  sublabel?: string;
}) {
  return (
    <div className="card px-4 py-3.5">
      <p className="text-xs text-[var(--color-text-dim)] uppercase tracking-wide">{label}</p>
      <p className="mt-1.5 text-2xl font-bold font-mono-num text-[var(--color-text)]">{value}</p>
      {sublabel && <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">{sublabel}</p>}
    </div>
  );
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const date = new Date(iso);
  const diffSec = Math.round((date.getTime() - Date.now()) / 1000);
  const abs = Math.abs(diffSec);
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  if (abs < 60) return rtf.format(diffSec, "second");
  if (abs < 3600) return rtf.format(Math.round(diffSec / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diffSec / 3600), "hour");
  return rtf.format(Math.round(diffSec / 86400), "day");
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}
