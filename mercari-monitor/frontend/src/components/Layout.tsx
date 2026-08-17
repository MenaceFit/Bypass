import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Activity, LayoutDashboard, List, Search, Settings as SettingsIcon, Terminal, Wifi, WifiOff } from "lucide-react";
import { useApp } from "../context/AppContext";
import { Toasts } from "./Toasts";
import { FirstRunModal } from "./FirstRunModal";
import { api } from "../api/client";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/searches", label: "Searches", icon: Search },
  { to: "/listings", label: "Listings", icon: List },
  { to: "/statistics", label: "Statistics", icon: Activity },
  { to: "/logs", label: "Logs", icon: Terminal },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export function Layout() {
  const { connectionState, systemStatus } = useApp();
  const [showFirstRun, setShowFirstRun] = useState(false);

  useEffect(() => {
    api
      .listSearches()
      .then((searches) => setShowFirstRun(searches.length === 0))
      .catch(() => undefined);
  }, []);

  return (
    <div className="min-h-screen flex">
      {showFirstRun && <FirstRunModal onDone={() => setShowFirstRun(false)} />}
      <aside className="w-56 shrink-0 border-r border-[var(--color-border)] flex flex-col">
        <div className="px-4 py-5 border-b border-[var(--color-border)]">
          <h1 className="text-sm font-bold tracking-wide text-[var(--color-text)]">MERCARI MONITOR</h1>
          <div className="mt-2 flex items-center gap-1.5">
            <span
              className={`status-dot ${systemStatus?.source_available !== false ? "animate-pulse-fade" : ""}`}
              style={{
                backgroundColor:
                  systemStatus === null
                    ? "var(--color-text-dim)"
                    : systemStatus.source_available
                      ? "var(--color-online)"
                      : "var(--color-degraded)",
              }}
            />
            <span className="text-xs text-[var(--color-text-muted)]">
              {systemStatus === null ? "CONNECTING" : systemStatus.source_available ? "SYSTEM ONLINE" : systemStatus.source_status}
            </span>
          </div>
        </div>

        <nav className="flex-1 px-2 py-3 space-y-0.5">
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-[var(--color-surface)] text-[var(--color-text)]"
                    : "text-[var(--color-text-muted)] hover:bg-[var(--color-surface)] hover:text-[var(--color-text)]"
                }`
              }
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="px-4 py-3 border-t border-[var(--color-border)] flex items-center gap-1.5">
          {connectionState === "connected" ? (
            <Wifi size={13} className="text-[var(--color-online)]" />
          ) : (
            <WifiOff size={13} className={connectionState === "connecting" ? "text-[var(--color-warning)]" : "text-[var(--color-danger)]"} />
          )}
          <span className="text-xs text-[var(--color-text-dim)] capitalize">{connectionState}</span>
        </div>
      </aside>

      <main className="flex-1 min-w-0 overflow-x-hidden">
        <Outlet />
      </main>

      <Toasts />
    </div>
  );
}
