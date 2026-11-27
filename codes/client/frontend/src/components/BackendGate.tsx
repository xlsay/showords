import type { BackendState } from "../meetingAssist-bridge";

interface BackendGateProps {
  state: BackendState;
  detail: string | null;
  logTail: string[];
  onRetry: () => void;
  onOpenLog: () => void;
}

const TITLES: Partial<Record<BackendState, string>> = {
  locating: "Starting MeetingAssist...",
  starting: "Starting MeetingAssist…",
  failed: "Couldn't start MeetingAssist",
  stopped: "Backend stopped",
};

const SUBTITLES: Partial<Record<BackendState, string>> = {
  failed: "The local capture service could not start.",
};

// Full-screen overlay shown until the backend is ready.
export function BackendGate({ state, detail, logTail, onRetry, onOpenLog }: BackendGateProps) {
  const isError = state === "failed" || state === "stopped";
  const isWorking = state === "locating" || state === "starting";
  const title = TITLES[state] ?? "Connecting…";
  const subtitle = SUBTITLES[state];

  return (
    <div className="backend-gate" role="alertdialog" aria-busy={isWorking} aria-label={title}>
      <div className="backend-gate__card">
        {isWorking && <div className="backend-gate__spinner" aria-hidden="true" />}
        {isError && <div className="backend-gate__icon" aria-hidden="true">⚠️</div>}
        <h1 className="backend-gate__title">{title}</h1>
        {subtitle && <p className="backend-gate__subtitle">{subtitle}</p>}
        {detail && <p className="backend-gate__detail">{detail}</p>}

        {isError && (
          <div className="backend-gate__actions">
            <button type="button" className="backend-gate__btn backend-gate__btn--primary" onClick={onRetry}>
              Retry
            </button>
            <button type="button" className="backend-gate__btn" onClick={onOpenLog}>
              View log
            </button>
          </div>
        )}

        {isError && logTail.length > 0 && (
          <pre className="backend-gate__log">{logTail.slice(-12).join("\n")}</pre>
        )}
      </div>
    </div>
  );
}
