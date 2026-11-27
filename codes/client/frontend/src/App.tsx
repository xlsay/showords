import { useCallback, useEffect, useMemo, useState } from "react";
import { BackendGate } from "./components/BackendGate";
import { SettingsModal } from "./components/SettingsModal";
import { saveTranscript } from "./export/transcriptFile";
import { useSessionSocket } from "./session/useSessionSocket";
import { fetchAudioDevices, fetchConfig } from "./system/backendApi";
import type { AudioDevices, ClientConfig } from "./system/backendApi";
import { useBackendStatus } from "./system/useBackendStatus";
import type { AudioSourceName } from "./types";

const SOURCE_LABELS: Record<AudioSourceName, string> = {
  microphone: "Microphone",
  system: "System audio",
};

const SERVER_POLL_MS = 5000; // re-check the server while idle

export default function App() {
  const backend = useBackendStatus();
  const session = useSessionSocket();

  const [config, setConfig] = useState<ClientConfig | null>(null);
  const [devices, setDevices] = useState<AudioDevices | null>(null);
  const [source, setSource] = useState<AudioSourceName>("microphone");
  const [micDevice, setMicDevice] = useState<string>("");
  const [loopbackDevice, setLoopbackDevice] = useState<string>("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [exportNotice, setExportNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!backend.isReady) return;
    fetchConfig()
      .then((next) => {
        setConfig(next);
        if (next.default_source === "system") setSource("system");
      })
      .catch(() => {});
    fetchAudioDevices().then(setDevices).catch(() => {});
  }, [backend.isReady]);

  const refreshConfig = useCallback(() => {
    fetchConfig().then(setConfig).catch(() => {});
  }, []);

  useEffect(() => {
    if (!backend.isReady || session.isActive) return;
    const timer = window.setInterval(refreshConfig, SERVER_POLL_MS);
    return () => window.clearInterval(timer);
  }, [backend.isReady, session.isActive, refreshConfig]);

  const onStart = useCallback(() => {
    setExportNotice(null);
    session.start({ source, micDevice, loopbackDevice });
  }, [session, source, micDevice, loopbackDevice]);

  const onExport = useCallback(async () => {
    if (session.utterances.length === 0) return;
    try {
      const target = await saveTranscript(session.utterances);
      setExportNotice(target ? `Saved to ${target}` : null);
    } catch (err) {
      setExportNotice(err instanceof Error ? err.message : "Export failed");
    }
  }, [session.utterances]);

  const serverStatus = useMemo(() => {
    if (!config) return null;
    const where = `${config.server_host}:${config.server_port}`;
    const server = config.server;
    if (!server.reachable) return { text: `Server ${where} unreachable`, warn: true };
    if (server.error) return { text: `Server error: ${server.error}`, warn: true };
    if (!server.ready) return { text: `Server ${where} is loading the speech model`, warn: true };
    if (server.auth_required && !config.token_set) return { text: `Server ${where} requires a token`, warn: true };
    return { text: `Server ${where} · ${server.whisper_size} · ${server.whisper_device}`, warn: false };
  }, [config]);

  const statusText = useMemo(() => {
    if (session.state === "starting") return "Starting…";
    if (session.state === "running") return `Listening · ${session.utterances.length} sentences`;
    if (session.state === "ended") return `Stopped · ${session.utterances.length} sentences`;
    return "Ready";
  }, [session.state, session.utterances.length]);

  const latest = session.latest;

  return (
    <div className="app">
      {!backend.isReady && (
        <BackendGate
          state={backend.state}
          detail={backend.detail}
          logTail={backend.logTail}
          onRetry={backend.retry}
          onOpenLog={backend.openLog}
        />
      )}

      <header className="bar">
        <span className="bar__title">MeetingAssist</span>

        <label className="bar__field">
          <span>Source</span>
          <select
            value={source}
            onChange={(event) => setSource(event.target.value as AudioSourceName)}
            disabled={session.isActive}
          >
            <option value="microphone">{SOURCE_LABELS.microphone}</option>
            <option value="system">{SOURCE_LABELS.system}</option>
          </select>
        </label>

        {source === "microphone" && devices && devices.mics.length > 0 && (
          <label className="bar__field">
            <span>Device</span>
            <select
              value={micDevice}
              onChange={(event) => setMicDevice(event.target.value)}
              disabled={session.isActive}
            >
              <option value="">Default</option>
              {devices.mics.map((device) => (
                <option key={device.id} value={device.id}>
                  {device.name}
                </option>
              ))}
            </select>
          </label>
        )}

        {source === "system" && devices && devices.loopbacks.length > 0 && (
          <label className="bar__field">
            <span>Device</span>
            <select
              value={loopbackDevice}
              onChange={(event) => setLoopbackDevice(event.target.value)}
              disabled={session.isActive}
            >
              <option value="">Default</option>
              {devices.loopbacks.map((device) => (
                <option key={device.id} value={device.id}>
                  {device.name}
                </option>
              ))}
            </select>
          </label>
        )}

        <div className="bar__actions">
          {session.isActive ? (
            <button type="button" className="btn btn--stop" onClick={session.stop}>
              Stop
            </button>
          ) : (
            <button type="button" className="btn btn--start" onClick={onStart}>
              Start
            </button>
          )}
          <button
            type="button"
            className="btn"
            onClick={onExport}
            disabled={session.utterances.length === 0}
          >
            Export txt
          </button>
          <button type="button" className="btn" onClick={() => setSettingsOpen(true)}>
            Settings
          </button>
        </div>
      </header>

      <main className="stage">
        {latest ? (
          <div className="lines">
            <p className="lines__source" lang={latest.language === "unknown" ? undefined : latest.language}>
              {latest.text}
            </p>
            <p className="lines__target" lang={latest.targetLanguage ?? undefined}>
              {latest.translation ?? (latest.targetLanguage === null ? "" : "…")}
            </p>
          </div>
        ) : (
          <p className="stage__hint">
            {session.isActive ? "Listening…" : "Press Start and begin speaking."}
          </p>
        )}
      </main>

      <footer className="status">
        <span>{statusText}</span>
        {serverStatus && (
          <span className={serverStatus.warn ? "status__warn" : "status__meta"}>{serverStatus.text}</span>
        )}
        {config?.server.reachable && config.server.translation_enabled === false && (
          <span className="status__warn">Server has no API key — translation is off</span>
        )}
        {exportNotice && <span className="status__meta">{exportNotice}</span>}
        {session.error && (
          <button type="button" className="status__error" onClick={session.clearError}>
            {session.error}
          </button>
        )}
      </footer>

      {settingsOpen && (
        <SettingsModal onClose={() => setSettingsOpen(false)} onSaved={refreshConfig} />
      )}
    </div>
  );
}
