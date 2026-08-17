import { useEffect, useState, type ReactNode } from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useApp } from "../context/AppContext";
import { PageHeader, LoadingState } from "../components/Shared";
import { ConfirmDialog } from "../components/ConfirmDialog";
import type { Settings } from "../types";

export function SettingsPage() {
  const { pushToast, soundEnabled, setSoundEnabled, desktopEnabled, setDesktopEnabled } = useApp();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [archiveDays, setArchiveDays] = useState(90);

  const load = () => {
    api.getSettings().then(setSettings).catch(() => undefined);
  };
  useEffect(load, []);

  const handleTestDiscord = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.testDiscord();
      setTestResult(result);
    } catch (err) {
      setTestResult({ success: false, message: err instanceof ApiError ? err.message : "Test failed." });
    } finally {
      setTesting(false);
    }
  };

  const handleThemeChange = async (theme: "dark" | "light") => {
    try {
      const updated = await api.updateSettings({ theme });
      setSettings(updated);
      if (theme === "light") {
        pushToast("info", "Light theme saved. This dashboard is designed dark-first — full light styling isn't implemented yet.");
      }
    } catch {
      pushToast("error", "Could not update theme.");
    }
  };

  const handleFirstRunModeChange = async (mode: "import_silent" | "treat_as_new") => {
    try {
      const updated = await api.updateSettings({ first_run_mode: mode });
      setSettings(updated);
    } catch {
      pushToast("error", "Could not update setting.");
    }
  };

  const handleReset = async () => {
    try {
      await api.resetDatabase("DELETE ALL DATA");
      pushToast("success", "Database reset. All listings, searches, and history were deleted.");
    } catch {
      pushToast("error", "Reset failed.");
    } finally {
      setConfirmReset(false);
    }
  };

  const handleArchive = async () => {
    try {
      const result = await api.archiveListings(archiveDays);
      pushToast("success", result.message);
    } catch {
      pushToast("error", "Archive failed.");
    } finally {
      setConfirmArchive(false);
    }
  };

  if (settings === null) {
    return (
      <div>
        <PageHeader title="Settings" />
        <LoadingState />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="Settings" />
      <div className="p-6 space-y-6 max-w-2xl">
        <SettingsSection title="Scan &amp; Concurrency">
          <ReadOnlyRow label="Default scan interval" value={`${settings.default_scan_interval}s`} />
          <ReadOnlyRow label="Minimum scan interval" value={`${settings.min_scan_interval}s`} />
          <ReadOnlyRow label="Max concurrent requests" value={String(settings.max_concurrent_requests)} />
          <ReadOnlyRow label="Min interval between requests" value={`${settings.min_request_interval_ms}ms`} />
          <ReadOnlyRow label="Request timeout" value={`${settings.request_timeout}s`} />
          <ReadOnlyRow label="Retry attempts" value={String(settings.retry_max_attempts)} />
          <p className="text-xs text-[var(--color-text-dim)] pt-1">
            These are infrastructure limits — edit <code className="font-mono-num">.env</code> and restart to change them
            (see README). Kept read-only here on purpose, so nothing can accidentally configure excessive load.
          </p>
        </SettingsSection>

        <SettingsSection title="Discord">
          <ReadOnlyRow label="Webhook" value={settings.discord_configured ? settings.discord_webhook_masked ?? "configured" : "Not configured"} />
          <div className="pt-2">
            <button
              onClick={handleTestDiscord}
              disabled={testing || !settings.discord_configured}
              className="rounded-md border border-[var(--color-border)] px-3 py-1.5 text-sm text-[var(--color-text-muted)] hover:bg-[var(--color-surface-hover)] disabled:opacity-40"
            >
              {testing ? "Sending…" : "Test Webhook"}
            </button>
            {testResult && (
              <p className={`mt-2 text-sm flex items-center gap-1.5 ${testResult.success ? "text-[var(--color-online)]" : "text-[var(--color-danger)]"}`}>
                {testResult.success ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                {testResult.message}
              </p>
            )}
            {!settings.discord_configured && (
              <p className="mt-2 text-xs text-[var(--color-text-dim)]">
                Set <code className="font-mono-num">DISCORD_WEBHOOK_URL</code> in <code className="font-mono-num">.env</code> and restart to enable.
              </p>
            )}
          </div>
        </SettingsSection>

        <SettingsSection title="Notifications">
          <ToggleRow label="Sound notification on new listing" checked={soundEnabled} onChange={setSoundEnabled} />
          <ToggleRow label="Desktop notification on new listing" checked={desktopEnabled} onChange={setDesktopEnabled} />
        </SettingsSection>

        <SettingsSection title="First run behavior">
          <p className="text-xs text-[var(--color-text-muted)] mb-2">
            Applied to each search's very first scan — existing results found at that point:
          </p>
          <div className="flex gap-2">
            <RadioPill
              label="Import silently"
              active={settings.first_run_mode === "import_silent"}
              onClick={() => handleFirstRunModeChange("import_silent")}
            />
            <RadioPill
              label="Treat as new"
              active={settings.first_run_mode === "treat_as_new"}
              onClick={() => handleFirstRunModeChange("treat_as_new")}
            />
          </div>
        </SettingsSection>

        <SettingsSection title="Theme">
          <div className="flex gap-2">
            <RadioPill label="Dark" active={settings.theme === "dark"} onClick={() => handleThemeChange("dark")} />
            <RadioPill label="Light" active={settings.theme === "light"} onClick={() => handleThemeChange("light")} />
          </div>
        </SettingsSection>

        <SettingsSection title="Logging">
          <ReadOnlyRow label="Log level" value={settings.log_level} />
          <p className="text-xs text-[var(--color-text-dim)] pt-1">
            Set <code className="font-mono-num">LOG_LEVEL</code> in <code className="font-mono-num">.env</code> to change.
          </p>
        </SettingsSection>

        <SettingsSection title="Database" danger>
          <ReadOnlyRow label="Location" value={settings.database_url} mono />
          <div className="pt-2 flex flex-wrap items-center gap-2">
            <input
              type="number"
              min={1}
              value={archiveDays}
              onChange={(e) => setArchiveDays(Number(e.target.value))}
              className="input w-20"
            />
            <button
              onClick={() => setConfirmArchive(true)}
              className="rounded-md border border-[var(--color-border)] px-3 py-1.5 text-sm text-[var(--color-text-muted)] hover:bg-[var(--color-surface-hover)]"
            >
              Delete listings older than {archiveDays} days
            </button>
          </div>
          <div className="pt-3 border-t border-[var(--color-border)] mt-3">
            <button
              onClick={() => setConfirmReset(true)}
              className="rounded-md border border-[var(--color-danger)] px-3 py-1.5 text-sm text-[var(--color-danger)] hover:bg-[var(--color-danger)]/10"
            >
              Reset Database
            </button>
            <p className="mt-2 text-xs text-[var(--color-text-dim)]">
              Permanently deletes all listings, searches, and history. This cannot be undone.
            </p>
          </div>
        </SettingsSection>
      </div>

      {confirmReset && (
        <ConfirmDialog
          title="Reset database?"
          description="This will permanently delete all listings and history, including every configured search. This cannot be undone."
          confirmLabel="Delete everything"
          danger
          requireText="DELETE ALL DATA"
          onConfirm={handleReset}
          onCancel={() => setConfirmReset(false)}
        />
      )}

      {confirmArchive && (
        <ConfirmDialog
          title={`Delete listings older than ${archiveDays} days?`}
          description="These listings will be permanently removed from your history. This cannot be undone."
          confirmLabel="Delete"
          danger
          onConfirm={handleArchive}
          onCancel={() => setConfirmArchive(false)}
        />
      )}
    </div>
  );
}

function SettingsSection({ title, children, danger }: { title: string; children: ReactNode; danger?: boolean }) {
  return (
    <div className={`card p-4 ${danger ? "border-[var(--color-danger)]/30" : ""}`}>
      <h2 className="text-sm font-semibold text-[var(--color-text)] mb-3">{title}</h2>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function ReadOnlyRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between text-sm py-0.5">
      <span className="text-[var(--color-text-muted)]">{label}</span>
      <span className={`text-[var(--color-text)] ${mono ? "font-mono-num text-xs" : ""}`}>{value}</span>
    </div>
  );
}

function ToggleRow({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center justify-between text-sm py-1 cursor-pointer">
      <span className="text-[var(--color-text)]">{label}</span>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="accent-[var(--color-accent)] w-4 h-4" />
    </label>
  );
}

function RadioPill({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-md px-3 py-1.5 text-sm border ${
        active ? "border-[var(--color-accent)] text-[var(--color-accent)] bg-[var(--color-accent)]/10" : "border-[var(--color-border)] text-[var(--color-text-muted)] hover:bg-[var(--color-surface-hover)]"
      }`}
    >
      {label}
    </button>
  );
}
