import { useEffect, useState, type ChangeEvent, type ReactNode } from "react";
import { Download, Pause, Pencil, Play, Plus, Search as SearchIcon, Trash2, Upload } from "lucide-react";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";
import { EmptyState, LoadingState, formatDateTime, relativeTime } from "../components/Shared";
import { StatusBadge } from "../components/StatusBadge";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { SearchFormModal } from "../components/SearchFormModal";
import type { Search } from "../types";

export function Searches() {
  const { pushToast, subscribe } = useApp();
  const [searches, setSearches] = useState<Search[] | null>(null);
  const [editing, setEditing] = useState<Search | "new" | null>(null);
  const [deleting, setDeleting] = useState<Search | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = () => {
    api.listSearches().then(setSearches).catch(() => pushToast("error", "Failed to load searches."));
  };

  useEffect(load, []);

  useEffect(
    () =>
      subscribe((event) => {
        if (event.type === "keyword_updated" || event.type === "scan_finished") load();
      }),
    [subscribe],
  );

  const togglePause = async (search: Search) => {
    setBusyId(search.id);
    try {
      const updated = search.active ? await api.pauseSearch(search.id) : await api.resumeSearch(search.id);
      setSearches((prev) => prev?.map((s) => (s.id === updated.id ? updated : s)) ?? null);
    } catch {
      pushToast("error", "Could not update search status.");
    } finally {
      setBusyId(null);
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    try {
      await api.deleteSearch(deleting.id);
      setSearches((prev) => prev?.filter((s) => s.id !== deleting.id) ?? null);
      pushToast("info", `Deleted search "${deleting.keyword}".`);
    } catch {
      pushToast("error", "Could not delete search.");
    } finally {
      setDeleting(null);
    }
  };

  const handleExport = async () => {
    try {
      const data = await api.exportSearches();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "mercari-searches.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      pushToast("error", "Export failed.");
    }
  };

  const handleImport = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    file
      .text()
      .then((text) => api.importSearches(JSON.parse(text)))
      .then((imported) => {
        pushToast("success", `Imported ${imported.length} search(es).`);
        load();
      })
      .catch(() => pushToast("error", "Import failed — check the file format."))
      .finally(() => {
        event.target.value = "";
      });
  };

  return (
    <div>
      <div className="flex items-center justify-between px-6 py-5 border-b border-[var(--color-border)]">
        <h1 className="text-lg font-semibold text-[var(--color-text)]">Searches</h1>
        <div className="flex gap-2">
          <button onClick={handleExport} className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-border)] px-3 py-1.5 text-sm text-[var(--color-text-muted)] hover:bg-[var(--color-surface-hover)]">
            <Download size={14} /> Export
          </button>
          <label className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-border)] px-3 py-1.5 text-sm text-[var(--color-text-muted)] hover:bg-[var(--color-surface-hover)] cursor-pointer">
            <Upload size={14} /> Import
            <input type="file" accept="application/json" className="hidden" onChange={handleImport} />
          </label>
          <button
            onClick={() => setEditing("new")}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--color-accent)] px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
          >
            <Plus size={14} /> Add Search
          </button>
        </div>
      </div>

      <div className="p-6">
        {searches === null ? (
          <LoadingState />
        ) : searches.length === 0 ? (
          <EmptyState icon={SearchIcon} title="No searches yet" description='Click "Add Search" to start monitoring a keyword on Mercari US.' />
        ) : (
          <div className="space-y-3">
            {searches.map((search) => (
              <div key={search.id} className="card p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2.5">
                      <h3 className="text-sm font-semibold text-[var(--color-text)] truncate">{search.keyword}</h3>
                      <StatusBadge status={search.status} pulse={search.status === "ACTIVE"} />
                    </div>
                    <p className="mt-1 text-xs text-[var(--color-text-dim)]">
                      Last scan: {relativeTime(search.last_scan_at)} · Every {search.scan_interval}s
                      {search.discord_enabled ? " · Discord ON" : " · Discord OFF"}
                    </p>
                    {search.last_error_message && search.status !== "ACTIVE" && (
                      <p className="mt-1 text-xs text-[var(--color-warning)] truncate">{search.last_error_message}</p>
                    )}
                    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--color-text-muted)]">
                      <span>
                        New today: <span className="font-mono-num text-[var(--color-text)]">{search.new_today}</span>
                      </span>
                      <span>
                        Total: <span className="font-mono-num text-[var(--color-text)]">{search.total_listings}</span>
                      </span>
                      {(search.min_price != null || search.max_price != null) && (
                        <span>
                          Price: {search.min_price ?? 0} – {search.max_price ?? "∞"}
                        </span>
                      )}
                      {search.next_scan_at && <span title={formatDateTime(search.next_scan_at)}>Next: {relativeTime(search.next_scan_at)}</span>}
                    </div>
                  </div>

                  <div className="flex shrink-0 gap-1.5">
                    <IconButton label="Edit" onClick={() => setEditing(search)}>
                      <Pencil size={14} />
                    </IconButton>
                    <IconButton label={search.active ? "Pause" : "Resume"} onClick={() => togglePause(search)} busy={busyId === search.id}>
                      {search.active ? <Pause size={14} /> : <Play size={14} />}
                    </IconButton>
                    <IconButton label="Delete" onClick={() => setDeleting(search)} danger>
                      <Trash2 size={14} />
                    </IconButton>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {editing && (
        <SearchFormModal
          initial={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={(saved) => {
            setSearches((prev) => {
              if (!prev) return [saved];
              const exists = prev.some((s) => s.id === saved.id);
              return exists ? prev.map((s) => (s.id === saved.id ? saved : s)) : [...prev, saved];
            });
            pushToast("success", editing === "new" ? `Search "${saved.keyword}" added.` : `Search "${saved.keyword}" updated.`);
            setEditing(null);
          }}
        />
      )}

      {deleting && (
        <ConfirmDialog
          title={`Delete "${deleting.keyword}"?`}
          description="This removes the search and stops monitoring it. Listings already found stay in your history."
          confirmLabel="Delete"
          danger
          onConfirm={confirmDelete}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  );
}

function IconButton({
  children,
  label,
  onClick,
  danger,
  busy,
}: {
  children: ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
  busy?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      title={label}
      aria-label={label}
      className={`inline-flex items-center justify-center rounded-md border border-[var(--color-border)] p-2 hover:bg-[var(--color-surface-hover)] disabled:opacity-50 ${
        danger ? "text-[var(--color-danger)]" : "text-[var(--color-text-muted)]"
      }`}
    >
      {children}
    </button>
  );
}
