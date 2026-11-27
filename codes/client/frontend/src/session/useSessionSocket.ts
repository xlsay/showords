import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AudioSourceName,
  ServerEvent,
  SessionState,
  Utterance,
} from "../types";

function wsBase(): string {
  return window.meetingAssist?.backendWs ?? "ws://127.0.0.1:8766";
}

export interface StartOptions {
  source: AudioSourceName;
  micDevice?: string;
  loopbackDevice?: string;
}

export interface SessionView {
  state: SessionState | "idle";
  isActive: boolean;
  utterances: Utterance[];
  latest: Utterance | null;
  error: string | null;
  start: (options: StartOptions) => void;
  stop: () => void;
  clearError: () => void;
}

export function useSessionSocket(): SessionView {
  const socketRef = useRef<WebSocket | null>(null);
  const [state, setState] = useState<SessionState | "idle">("idle");
  const [utterances, setUtterances] = useState<Utterance[]>([]);
  const [error, setError] = useState<string | null>(null);

  const stop = useCallback(() => {
    const socket = socketRef.current;
    if (!socket) return;
    if (socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "stop" }));
    }
    socket.close();
    socketRef.current = null;
    setState("ended");
    window.meetingAssist?.setSessionActive?.(false);
  }, []);

  const start = useCallback((options: StartOptions) => {
    if (socketRef.current) return;
    const params = new URLSearchParams({ source: options.source });
    if (options.micDevice) params.set("mic_device", options.micDevice);
    if (options.loopbackDevice) params.set("loopback_device", options.loopbackDevice);

    setUtterances([]);
    setError(null);
    setState("starting");

    const socket = new WebSocket(`${wsBase()}/ws/session?${params.toString()}`);
    socketRef.current = socket;
    window.meetingAssist?.setSessionActive?.(true);

    socket.onmessage = (event) => {
      let parsed: ServerEvent;
      try {
        parsed = JSON.parse(event.data as string) as ServerEvent;
      } catch {
        return;
      }
      switch (parsed.type) {
        case "session_state":
          setState(parsed.payload.state);
          break;
        case "utterance": {
          const p = parsed.payload;
          setUtterances((prev) => [
            ...prev,
            {
              id: p.id,
              index: p.index,
              startTime: p.start_time,
              endTime: p.end_time,
              language: p.language,
              text: p.text,
              targetLanguage: p.target_language,
              translation: null,
            },
          ]);
          break;
        }
        case "translation": {
          const p = parsed.payload;
          setUtterances((prev) =>
            prev.map((item) =>
              item.id === p.id
                ? { ...item, translation: p.translation, targetLanguage: p.target_language }
                : item,
            ),
          );
          break;
        }
        case "error":
          setError(parsed.payload.message);
          break;
      }
    };

    socket.onerror = () => setError("Lost the connection to the backend.");
    socket.onclose = () => {
      socketRef.current = null;
      setState((prev) => (prev === "idle" ? "idle" : "ended"));
      window.meetingAssist?.setSessionActive?.(false);
    };
  }, []);

  // Close the socket if the window unmounts mid-session.
  useEffect(() => () => socketRef.current?.close(), []);

  return {
    state,
    isActive: state === "starting" || state === "running",
    utterances,
    latest: utterances.length > 0 ? utterances[utterances.length - 1] : null,
    error,
    start,
    stop,
    clearError: () => setError(null),
  };
}
