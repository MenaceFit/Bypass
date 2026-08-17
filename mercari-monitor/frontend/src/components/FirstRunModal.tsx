import { useState } from "react";
import { api } from "../api/client";

export function FirstRunModal({ onDone }: { onDone: () => void }) {
  const [saving, setSaving] = useState<"import_silent" | "treat_as_new" | null>(null);

  const choose = async (mode: "import_silent" | "treat_as_new") => {
    setSaving(mode);
    try {
      await api.updateSettings({ first_run_mode: mode });
    } finally {
      onDone();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm px-4">
      <div className="card w-full max-w-md p-6">
        <h2 className="text-base font-semibold text-[var(--color-text)]">Mercari Monitor has no existing listings</h2>
        <p className="mt-2 text-sm text-[var(--color-text-muted)]">
          How should results already on Mercari be treated the first time a new search runs?
        </p>
        <div className="mt-5 space-y-2">
          <button
            onClick={() => choose("import_silent")}
            disabled={saving !== null}
            className="w-full text-left rounded-md border border-[var(--color-accent)] bg-[var(--color-accent)]/10 px-4 py-3 hover:bg-[var(--color-accent)]/20 disabled:opacity-50"
          >
            <p className="text-sm font-medium text-[var(--color-text)]">Import without notifications (recommended)</p>
            <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
              Existing results are saved as a baseline. Only listings that appear afterward trigger alerts.
            </p>
          </button>
          <button
            onClick={() => choose("treat_as_new")}
            disabled={saving !== null}
            className="w-full text-left rounded-md border border-[var(--color-border)] px-4 py-3 hover:bg-[var(--color-surface-hover)] disabled:opacity-50"
          >
            <p className="text-sm font-medium text-[var(--color-text)]">Treat as new</p>
            <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
              Every result found on a search's first scan fires a normal alert (Discord + live feed).
            </p>
          </button>
        </div>
        <p className="mt-4 text-xs text-[var(--color-text-dim)]">You can change this later in Settings.</p>
      </div>
    </div>
  );
}
