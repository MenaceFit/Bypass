import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useWebSocket, type ConnectionState } from "../hooks/useWebSocket";
import { api } from "../api/client";
import type { SystemStatus, WsEvent, WsNewListingEvent } from "../types";

const LIVE_FEED_MAX = 100;

export interface ToastMessage {
  id: number;
  kind: "success" | "error" | "info";
  message: string;
}

interface AppContextValue {
  connectionState: ConnectionState;
  systemStatus: SystemStatus | null;
  liveFeed: WsNewListingEvent["listing"][];
  toasts: ToastMessage[];
  pushToast: (kind: ToastMessage["kind"], message: string) => void;
  dismissToast: (id: number) => void;
  subscribe: (handler: (event: WsEvent) => void) => () => void;
  soundEnabled: boolean;
  setSoundEnabled: (v: boolean) => void;
  desktopEnabled: boolean;
  setDesktopEnabled: (v: boolean) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

// WS `error` events can carry a raw multi-line exception (e.g. a
// Playwright call log) — full detail belongs on the Logs page and the
// search's own error field, not crammed into a toast.
function summarizeError(reason: string): string {
  const firstLine = reason.split("\n")[0].trim();
  return firstLine.length > 140 ? `${firstLine.slice(0, 140)}…` : firstLine;
}

function playChime(): void {
  try {
    const AudioCtx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new AudioCtx();
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.connect(gain);
    gain.connect(ctx.destination);
    oscillator.frequency.value = 880;
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
    oscillator.start();
    oscillator.stop(ctx.currentTime + 0.4);
  } catch {
    // Audio unavailable/blocked by the browser — not critical.
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [liveFeed, setLiveFeed] = useState<WsNewListingEvent["listing"][]>([]);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [soundEnabled, setSoundEnabledState] = useState(false);
  const [desktopEnabled, setDesktopEnabledState] = useState(false);
  const listenersRef = useRef<Set<(event: WsEvent) => void>>(new Set());
  const toastIdRef = useRef(0);

  useEffect(() => {
    api
      .getSettings()
      .then((settings) => {
        setSoundEnabledState(settings.sound_notifications_enabled);
        setDesktopEnabledState(settings.desktop_notifications_enabled);
      })
      .catch(() => undefined);
    api.monitoringStatus().then(setSystemStatus).catch(() => undefined);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const pushToast = useCallback(
    (kind: ToastMessage["kind"], message: string) => {
      const id = ++toastIdRef.current;
      setToasts((prev) => [...prev, { id, kind, message }]);
      window.setTimeout(() => dismissToast(id), 5000);
    },
    [dismissToast],
  );

  const setSoundEnabled = useCallback((value: boolean) => {
    setSoundEnabledState(value);
    api.updateSettings({ sound_notifications_enabled: value }).catch(() => undefined);
  }, []);

  const setDesktopEnabled = useCallback((value: boolean) => {
    if (value && "Notification" in window && Notification.permission === "default") {
      Notification.requestPermission().catch(() => undefined);
    }
    setDesktopEnabledState(value);
    api.updateSettings({ desktop_notifications_enabled: value }).catch(() => undefined);
  }, []);

  const handleEvent = useCallback(
    (event: WsEvent) => {
      if (event.type === "new_listing") {
        setLiveFeed((prev) => [event.listing, ...prev].slice(0, LIVE_FEED_MAX));
        pushToast("success", `New listing: ${event.listing.title ?? event.listing.external_id}`);
        if (soundEnabled) playChime();
        if (desktopEnabled && "Notification" in window && Notification.permission === "granted") {
          const price = event.listing.price != null ? `$${event.listing.price}` : "price unknown";
          new Notification("New Mercari Listing", {
            body: `${event.listing.title ?? "Untitled listing"} — ${price}`,
          });
        }
      } else if (event.type === "system_status") {
        setSystemStatus(event);
      } else if (event.type === "error") {
        pushToast("error", summarizeError(event.reason));
      }
      for (const listener of listenersRef.current) listener(event);
    },
    [pushToast, soundEnabled, desktopEnabled],
  );

  const connectionState = useWebSocket(handleEvent);

  const subscribe = useCallback((handler: (event: WsEvent) => void) => {
    listenersRef.current.add(handler);
    return () => {
      listenersRef.current.delete(handler);
    };
  }, []);

  const value = useMemo<AppContextValue>(
    () => ({
      connectionState,
      systemStatus,
      liveFeed,
      toasts,
      pushToast,
      dismissToast,
      subscribe,
      soundEnabled,
      setSoundEnabled,
      desktopEnabled,
      setDesktopEnabled,
    }),
    [
      connectionState,
      systemStatus,
      liveFeed,
      toasts,
      pushToast,
      dismissToast,
      subscribe,
      soundEnabled,
      setSoundEnabled,
      desktopEnabled,
      setDesktopEnabled,
    ],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used within AppProvider");
  return ctx;
}
