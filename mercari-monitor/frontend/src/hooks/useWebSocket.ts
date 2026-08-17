import { useCallback, useEffect, useRef, useState } from "react";
import type { WsEvent } from "../types";

// Spec section 22: 1s -> 2s -> 5s -> 10s, then hold at 10s.
const RECONNECT_LADDER_MS = [1000, 2000, 5000, 10000];

export type ConnectionState = "connecting" | "connected" | "disconnected";

export function useWebSocket(onEvent: (event: WsEvent) => void): ConnectionState {
  const [state, setState] = useState<ConnectionState>("connecting");
  const attemptRef = useRef(0);
  const socketRef = useRef<WebSocket | null>(null);
  const timeoutRef = useRef<number | undefined>(undefined);
  const closedByUsRef = useRef(false);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const connect = useCallback(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${window.location.host}/ws`;
    setState("connecting");

    const socket = new WebSocket(url);
    socketRef.current = socket;

    socket.onopen = () => {
      attemptRef.current = 0;
      setState("connected");
    };

    socket.onmessage = (event: MessageEvent<string>) => {
      try {
        const data = JSON.parse(event.data) as WsEvent;
        onEventRef.current(data);
      } catch {
        // Ignore malformed frames rather than crashing the dashboard.
      }
    };

    socket.onclose = () => {
      setState("disconnected");
      if (closedByUsRef.current) return;
      const delay = RECONNECT_LADDER_MS[Math.min(attemptRef.current, RECONNECT_LADDER_MS.length - 1)];
      attemptRef.current += 1;
      timeoutRef.current = window.setTimeout(connect, delay);
    };

    socket.onerror = () => {
      socket.close();
    };
  }, []);

  useEffect(() => {
    closedByUsRef.current = false;
    connect();
    return () => {
      closedByUsRef.current = true;
      if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
      socketRef.current?.close();
    };
  }, [connect]);

  return state;
}
