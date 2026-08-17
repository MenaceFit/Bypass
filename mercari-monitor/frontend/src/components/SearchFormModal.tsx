import { useState, type FormEvent, type ReactNode } from "react";
import { X } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { Search, SearchWriteRequest } from "../types";

interface SearchFormModalProps {
  initial?: Search;
  onClose: () => void;
  onSaved: (search: Search) => void;
}

function toFormState(search?: Search): SearchWriteRequest {
  return {
    keyword: search?.keyword ?? "",
    scan_interval: search?.scan_interval ?? 5,
    discord_enabled: search?.discord_enabled ?? true,
    min_price: search?.min_price ?? null,
    max_price: search?.max_price ?? null,
    category: search?.category ?? "",
    brand: search?.brand ?? "",
    size: search?.size ?? "",
    condition: search?.condition ?? "",
    location: search?.location ?? "",
    sort: search?.sort ?? "newest",
    include_keywords: search?.include_keywords ?? [],
    exclude_keywords: search?.exclude_keywords ?? [],
  };
}

export function SearchFormModal({ initial, onClose, onSaved }: SearchFormModalProps) {
  const [form, setForm] = useState<SearchWriteRequest>(toFormState(initial));
  const [includeText, setIncludeText] = useState((initial?.include_keywords ?? []).join(", "));
  const [excludeText, setExcludeText] = useState((initial?.exclude_keywords ?? []).join(", "));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const isEdit = Boolean(initial);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSaving(true);

    const payload: SearchWriteRequest = {
      ...form,
      category: form.category || null,
      brand: form.brand || null,
      size: form.size || null,
      condition: form.condition || null,
      location: form.location || null,
      include_keywords: includeText.split(",").map((s) => s.trim()).filter(Boolean),
      exclude_keywords: excludeText.split(",").map((s) => s.trim()).filter(Boolean),
    };

    try {
      const saved = initial ? await api.updateSearch(initial.id, payload) : await api.createSearch(payload);
      onSaved(saved);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4 py-8 overflow-y-auto">
      <div className="card w-full max-w-lg p-5 my-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-[var(--color-text)]">
            {isEdit ? "Edit Search" : "Add Search"}
          </h2>
          <button onClick={onClose} className="text-[var(--color-text-dim)] hover:text-[var(--color-text)]">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <Field label="Keyword" required>
            <input
              required
              autoFocus
              value={form.keyword}
              onChange={(e) => setForm({ ...form, keyword: e.target.value })}
              placeholder="Nike ACG"
              className="input"
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Scan interval (sec)">
              <input
                type="number"
                min={1}
                value={form.scan_interval ?? 5}
                onChange={(e) => setForm({ ...form, scan_interval: Number(e.target.value) })}
                className="input"
              />
            </Field>
            <Field label="Sort">
              <select
                value={form.sort}
                onChange={(e) => setForm({ ...form, sort: e.target.value as SearchWriteRequest["sort"] })}
                className="input"
              >
                <option value="newest">Newest</option>
                <option value="price_low">Lowest price</option>
                <option value="price_high">Highest price</option>
              </select>
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Minimum price">
              <input
                type="number"
                min={0}
                value={form.min_price ?? ""}
                onChange={(e) => setForm({ ...form, min_price: e.target.value === "" ? null : Number(e.target.value) })}
                placeholder="$0"
                className="input"
              />
            </Field>
            <Field label="Maximum price">
              <input
                type="number"
                min={0}
                value={form.max_price ?? ""}
                onChange={(e) => setForm({ ...form, max_price: e.target.value === "" ? null : Number(e.target.value) })}
                placeholder="No limit"
                className="input"
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Brand">
              <input value={form.brand ?? ""} onChange={(e) => setForm({ ...form, brand: e.target.value })} className="input" />
            </Field>
            <Field label="Size">
              <input value={form.size ?? ""} onChange={(e) => setForm({ ...form, size: e.target.value })} className="input" />
            </Field>
            <Field label="Condition">
              <input value={form.condition ?? ""} onChange={(e) => setForm({ ...form, condition: e.target.value })} className="input" />
            </Field>
            <Field label="Category">
              <input value={form.category ?? ""} onChange={(e) => setForm({ ...form, category: e.target.value })} className="input" />
            </Field>
          </div>
          <p className="-mt-2 text-xs text-[var(--color-text-dim)]">
            Brand/size/condition/category are passed through to Mercari's search as-is (best-effort — see README).
            Leave blank to not filter on them.
          </p>

          <Field label="Include keywords (comma-separated, optional)">
            <input
              value={includeText}
              onChange={(e) => setIncludeText(e.target.value)}
              placeholder="ACG, Jacket"
              className="input"
            />
          </Field>
          <Field label="Exclude keywords (comma-separated, optional)">
            <input
              value={excludeText}
              onChange={(e) => setExcludeText(e.target.value)}
              placeholder="Kids, Replica"
              className="input"
            />
          </Field>

          <label className="flex items-center gap-2 text-sm text-[var(--color-text)]">
            <input
              type="checkbox"
              checked={form.discord_enabled}
              onChange={(e) => setForm({ ...form, discord_enabled: e.target.checked })}
              className="accent-[var(--color-accent)]"
            />
            Send Discord notifications for this search
          </label>

          {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="rounded-md px-3 py-1.5 text-sm text-[var(--color-text-muted)] hover:bg-[var(--color-surface-hover)]">
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded-md bg-[var(--color-accent)] px-4 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
            >
              {saving ? "Saving…" : isEdit ? "Save Changes" : "Add Search"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs text-[var(--color-text-muted)] mb-1">
        {label}
        {required && <span className="text-[var(--color-danger)]"> *</span>}
      </span>
      {children}
    </label>
  );
}
