import { useCallback, useEffect, useState } from "react";
import type { BackendInfo, BackendState } from "../meetingAssist-bridge";

const BROWSER_FALLBACK: BackendInfo = {
  // In a plain browser there is no supervisor, so assume the backend is reachable.
  state: "ready",
  detail: null,
  httpBase: "http://127.0.0.1:8766",
  wsBase: "ws://127.0.0.1:8766",
  logTail: [],
};

export interface BackendStatusView {
  state: BackendState;
  detail: string | null;
  logTail: string[];
  isReady: boolean;
  hasBridge: boolean;
  retry: () => void;
  openLog: () => void;
}

export function useBackendStatus(): BackendStatusView {
  const bridge = typeof window !== "undefined" ? window.meetingAssist : undefined;
  const hasBridge = Boolean(bridge?.onBackendStatus);
  const [info, setInfo] = useState<BackendInfo>(hasBridge ? { ...BROWSER_FALLBACK, state: "idle" } : BROWSER_FALLBACK);

  useEffect(() => {
    if (!bridge?.onBackendStatus) return;
    // Pull the current status immediately (events may have fired before mount)…
    bridge.getBackendInfo?.().then((current) => current && setInfo(current)).catch(() => {});
    // …then subscribe to live transitions.
    const unsubscribe = bridge.onBackendStatus(setInfo);
    return unsubscribe;
  }, [bridge]);

  const retry = useCallback(() => {
    bridge?.retryBackend?.().then((current) => current && setInfo(current)).catch(() => {});
  }, [bridge]);

  const openLog = useCallback(() => {
    bridge?.openBackendLog?.().catch(() => {});
  }, [bridge]);

  return {
    state: info.state,
    detail: info.detail,
    logTail: info.logTail ?? [],
    isReady: !hasBridge || info.state === "ready",
    hasBridge,
    retry,
    openLog,
  };
}
