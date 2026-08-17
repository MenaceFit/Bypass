import { Copy, ExternalLink, ImageOff } from "lucide-react";
import { useState } from "react";
import type { Listing } from "../types";
import { useApp } from "../context/AppContext";

function formatPrice(price: number | null, currency: string): string {
  if (price == null) return "Unknown price";
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(price);
  } catch {
    return `$${price.toFixed(2)}`;
  }
}

function formatLatency(ms: number | null): string | null {
  if (ms == null) return null;
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s`;
}

export function ListingCard({
  listing,
  keywordLabel,
}: {
  listing: Listing;
  keywordLabel?: string;
}) {
  const { pushToast } = useApp();
  const [imgFailed, setImgFailed] = useState(false);
  const latency = formatLatency(listing.detection_latency_ms);

  const copyUrl = async () => {
    try {
      await navigator.clipboard.writeText(listing.listing_url);
      pushToast("info", "Listing URL copied");
    } catch {
      pushToast("error", "Could not copy URL");
    }
  };

  return (
    <div className="card overflow-hidden animate-slide-in">
      <div className="aspect-square bg-[var(--color-bg)] flex items-center justify-center overflow-hidden">
        {listing.image_url && !imgFailed ? (
          <img
            src={listing.image_url}
            alt={listing.title ?? "Listing"}
            className="w-full h-full object-cover"
            onError={() => setImgFailed(true)}
            loading="lazy"
          />
        ) : (
          <ImageOff size={28} className="text-[var(--color-text-dim)]" />
        )}
      </div>
      <div className="p-3 space-y-2">
        <p className="text-sm font-medium text-[var(--color-text)] line-clamp-2 min-h-[2.5rem]">
          {listing.title ?? "Untitled listing"}
        </p>
        <p className="text-lg font-bold text-[var(--color-online)] font-mono-num">
          {formatPrice(listing.price, listing.currency)}
        </p>
        <div className="flex flex-wrap gap-1.5 text-xs text-[var(--color-text-muted)]">
          {listing.brand && <span className="rounded bg-[var(--color-surface-hover)] px-1.5 py-0.5">{listing.brand}</span>}
          {listing.size && <span className="rounded bg-[var(--color-surface-hover)] px-1.5 py-0.5">Size {listing.size}</span>}
          {listing.condition && <span className="rounded bg-[var(--color-surface-hover)] px-1.5 py-0.5">{listing.condition}</span>}
        </div>
        <div className="flex items-center justify-between text-xs text-[var(--color-text-dim)] pt-1 border-t border-[var(--color-border)]">
          <span className="truncate">Keyword: {keywordLabel ?? "—"}</span>
          {latency && <span className="font-mono-num shrink-0 ml-2">{latency}</span>}
        </div>
        <div className="flex gap-2 pt-1">
          <a
            href={listing.listing_url}
            target="_blank"
            rel="noreferrer"
            className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-md bg-[var(--color-accent)] px-2 py-1.5 text-xs font-medium text-white hover:opacity-90"
          >
            <ExternalLink size={12} /> Open Listing
          </a>
          <button
            onClick={copyUrl}
            className="inline-flex items-center justify-center gap-1.5 rounded-md border border-[var(--color-border)] px-2 py-1.5 text-xs text-[var(--color-text-muted)] hover:bg-[var(--color-surface-hover)]"
          >
            <Copy size={12} /> Copy
          </button>
        </div>
      </div>
    </div>
  );
}
