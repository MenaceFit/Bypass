import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { useApp } from "../context/AppContext";

const ICONS = {
  success: CheckCircle2,
  error: XCircle,
  info: Info,
};

const COLORS = {
  success: "border-l-[var(--color-online)]",
  error: "border-l-[var(--color-danger)]",
  info: "border-l-[var(--color-accent)]",
};

export function Toasts() {
  const { toasts, dismissToast } = useApp();

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-80">
      {toasts.map((toast) => {
        const Icon = ICONS[toast.kind];
        return (
          <div
            key={toast.id}
            className={`card animate-slide-in border-l-4 ${COLORS[toast.kind]} px-3 py-2.5 flex items-start gap-2 shadow-lg`}
          >
            <Icon size={16} className="mt-0.5 shrink-0 text-[var(--color-text-muted)]" />
            <p className="text-sm text-[var(--color-text)] flex-1">{toast.message}</p>
            <button
              onClick={() => dismissToast(toast.id)}
              className="text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
              aria-label="Dismiss"
            >
              <X size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
