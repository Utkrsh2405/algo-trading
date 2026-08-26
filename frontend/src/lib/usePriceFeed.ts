import { useEffect, useRef, useState } from "react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface LiveQuote {
  symbol: string;
  last_price: number;
  timestamp: string;
  /** "up" | "down" | "neutral" — for flash animation */
  direction?: "up" | "down" | "neutral";
}

/**
 * Subscribes to the backend's live price WebSocket and reconnects with
 * backoff on drop — a silently dead connection here would leave the
 * dashboard showing stale prices without any indication of it.
 *
 * Also handles `feed_status` messages emitted by the Phase 3 watchdog
 * so the UI can warn users when the upstream broker feed is stale.
 */
export function usePriceFeed() {
  const [quotes, setQuotes] = useState<Record<string, LiveQuote>>({});
  const [connected, setConnected] = useState(false);
  const [feedDown, setFeedDown] = useState(false);
  const attemptRef = useRef(0);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let closedByEffect = false;
    let retryTimer: ReturnType<typeof setTimeout>;

    function connect() {
      const wsUrl = API_BASE_URL.replace(/^http/, "ws") + "/api/prices/ws";
      socket = new WebSocket(wsUrl);

      socket.onopen = () => {
        attemptRef.current = 0;
        setConnected(true);
      };

      socket.onmessage = (event) => {
        const data = JSON.parse(event.data) as LiveQuote & { type: string; status?: string };

        if (data.type === "feed_status") {
          setFeedDown(data.status === "down");
          return;
        }

        if (data.type === "quote") {
          setQuotes((prev) => {
            const prevPrice = prev[data.symbol]?.last_price;
            const direction =
              prevPrice === undefined || prevPrice === data.last_price
                ? "neutral"
                : data.last_price > prevPrice
                ? "up"
                : "down";
            return {
              ...prev,
              [data.symbol]: { ...data, direction },
            };
          });
        }
      };

      socket.onclose = () => {
        setConnected(false);
        if (closedByEffect) return;
        const delay = Math.min(1000 * 2 ** attemptRef.current, 15000);
        attemptRef.current += 1;
        retryTimer = setTimeout(connect, delay);
      };
    }

    connect();

    return () => {
      closedByEffect = true;
      clearTimeout(retryTimer);
      socket?.close();
    };
  }, []);

  return { quotes: Object.values(quotes), connected, feedDown };
}
