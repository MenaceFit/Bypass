import { useEffect, useState, type ReactNode } from "react";
import { Download, ExternalLink, List as ListIcon } from "lucide-react";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";
import { EmptyState, LoadingState, formatDateTime } from "../components/Shared";
import { StatusBadge } from "../components/StatusBadge";
import type { Listing, ListingFilters, PaginatedListings, Search, SortOption } from "../types";

const SORT_OPTIONS: { value: SortOption; label: string }[] = [
  { value: "newest", label: "Newest" },
  { value: "oldest", label: "Oldest" },
  { value: "price_low", label: "Lowest price" },
  { value: "price_high", label: "Highest price" },
  { value: "detection_fastest", label: "Fastest detection" },
];

export function Listings() {
  const { subscribe, pushToast } = useApp();
  const [data, setData] = useState<PaginatedListings | null>(null);
  const [searches, setSearches] = useState<Search[]>([]);
  const [filters, setFilters] = useState<ListingFilters>({ sort: "newest", page: 1, page_size: 25 });
  const [brandInput, setBrandInput] = useState("");

  useEffect(() => {
    api.listSearches().then(setSearches).catch(() => undefined);
  }, []);

  const load = () => {
    api.listListings(filters).then(setData).catch(() => pushToast("error", "Failed to load listings."));
  };

  useEffect(load, [filters]);

  useEffect(
    () =>
      subscribe((event) => {
        if (event.type === "new_listing" && filters.page === 1) load();
      }),
    [subscribe, filters],
  );

  const setFilter = <K extends keyof ListingFilters>(key: K, value: ListingFilters[K]) => {
    setFilters((prev) => ({ ...prev, [key]: value, page: key === "page" ? (value as number) : 1 }));
  };

  return (
    <div>
      <div className="flex items-center justify-between px-6 py-5 border-b border-[var(--color-border)]">
        <h1 className="text-lg font-semibold text-[var(--color-text)]">Listings</h1>
        <a
          href={api.exportListingsCsvUrl(filters)}
          className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-border)] px-3 py-1.5 text-sm text-[var(--color-text-muted)] hover:bg-[var(--color-surface-hover)]"
        >
          <Download size={14} /> Export CSV
        </a>
      </div>

      <div className="px-6 pt-4 flex flex-wrap gap-2 items-end">
        <FilterField label="Keyword">
          <select
            className="input"
            value={filters.keyword_id ?? ""}
            onChange={(e) => setFilter("keyword_id", e.target.value ? Number(e.target.value) : undefined)}
          >
            <option value="">All</option>
            {searches.map((s) => (
              <option key={s.id} value={s.id}>
                {s.keyword}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label="Brand">
          <input
            className="input"
            value={brandInput}
            onChange={(e) => setBrandInput(e.target.value)}
            onBlur={() => setFilter("brand", brandInput || undefined)}
            placeholder="Any"
          />
        </FilterField>
        <FilterField label="Min price">
          <input
            type="number"
            className="input w-24"
            value={filters.min_price ?? ""}
            onChange={(e) => setFilter("min_price", e.target.value ? Number(e.target.value) : undefined)}
          />
        </FilterField>
        <FilterField label="Max price">
          <input
            type="number"
            className="input w-24"
            value={filters.max_price ?? ""}
            onChange={(e) => setFilter("max_price", e.target.value ? Number(e.target.value) : undefined)}
          />
        </FilterField>
        <FilterField label="Discord">
          <select
            className="input"
            value={filters.discord_status ?? ""}
            onChange={(e) => setFilter("discord_status", (e.target.value || undefined) as ListingFilters["discord_status"])}
          >
            <option value="">Any</option>
            <option value="SENT">Sent</option>
            <option value="PENDING">Pending</option>
            <option value="FAILED">Failed</option>
          </select>
        </FilterField>
        <FilterField label="Sort">
          <select className="input" value={filters.sort} onChange={(e) => setFilter("sort", e.target.value as SortOption)}>
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </FilterField>
      </div>

      <div className="p-6">
        {data === null ? (
          <LoadingState />
        ) : data.items.length === 0 ? (
          <EmptyState icon={ListIcon} title="No listings match these filters" />
        ) : (
          <>
            <div className="card overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-dim)] uppercase tracking-wide">
                    <th className="px-3 py-2.5 font-medium">Title</th>
                    <th className="px-3 py-2.5 font-medium">Price</th>
                    <th className="px-3 py-2.5 font-medium">Brand</th>
                    <th className="px-3 py-2.5 font-medium">Size</th>
                    <th className="px-3 py-2.5 font-medium">Keywords</th>
                    <th className="px-3 py-2.5 font-medium">Detected</th>
                    <th className="px-3 py-2.5 font-medium">Discord</th>
                    <th className="px-3 py-2.5 font-medium"></th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((listing) => (
                    <ListingRow key={listing.id} listing={listing} />
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex items-center justify-between text-sm text-[var(--color-text-muted)]">
              <span>
                {data.total} listing{data.total === 1 ? "" : "s"} · page {data.page} of {data.total_pages}
              </span>
              <div className="flex gap-2">
                <button
                  disabled={data.page <= 1}
                  onClick={() => setFilter("page", data.page - 1)}
                  className="rounded-md border border-[var(--color-border)] px-3 py-1 disabled:opacity-40 hover:bg-[var(--color-surface-hover)]"
                >
                  Previous
                </button>
                <button
                  disabled={data.page >= data.total_pages}
                  onClick={() => setFilter("page", data.page + 1)}
                  className="rounded-md border border-[var(--color-border)] px-3 py-1 disabled:opacity-40 hover:bg-[var(--color-surface-hover)]"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ListingRow({ listing }: { listing: Listing }) {
  return (
    <tr className="border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-surface-hover)]">
      <td className="px-3 py-2.5 max-w-xs truncate text-[var(--color-text)]">{listing.title ?? "Untitled listing"}</td>
      <td className="px-3 py-2.5 font-mono-num">{listing.price != null ? `$${listing.price}` : "—"}</td>
      <td className="px-3 py-2.5 text-[var(--color-text-muted)]">{listing.brand ?? "—"}</td>
      <td className="px-3 py-2.5 text-[var(--color-text-muted)]">{listing.size ?? "—"}</td>
      <td className="px-3 py-2.5 text-[var(--color-text-muted)] max-w-[160px] truncate">{listing.matched_keywords.join(", ")}</td>
      <td className="px-3 py-2.5 text-[var(--color-text-dim)] whitespace-nowrap">{formatDateTime(listing.detected_at)}</td>
      <td className="px-3 py-2.5">{listing.discord_status ? <StatusBadge status={listing.discord_status} /> : "—"}</td>
      <td className="px-3 py-2.5">
        <a href={listing.listing_url} target="_blank" rel="noreferrer" className="text-[var(--color-accent)] hover:opacity-80">
          <ExternalLink size={14} />
        </a>
      </td>
    </tr>
  );
}

function FilterField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs text-[var(--color-text-dim)] mb-1">{label}</span>
      {children}
    </label>
  );
}
