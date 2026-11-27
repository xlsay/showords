import { useEffect, useState } from "react";
import type { AppSettings } from "../meetingAssist-bridge";

interface SettingsModalProps {
  onClose: () => void;
  onSaved: () => void;
}

export function SettingsModal({ onClose, onSaved }: SettingsModalProps) {
  const bridge = typeof window !== "undefined" ? window.meetingAssist : undefined;
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    bridge?.getSettings?.().then(setSettings).catch(() => setNotice("Settings are unavailable in the browser."));
  }, [bridge]);

  const save = async () => {
    if (!settings || !bridge?.saveSettings) return;
    setSaving(true);
    try {
      const result = await bridge.saveSettings({
        ...settings,
        serverHost: settings.serverHost.trim(),
        serverPort: Number(settings.serverPort) || 8765,
      });
      onSaved();
      setNotice(result.restarted ? "Saved. Reconnected to the server." : "Saved. Applies after the current session.");
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Could not save settings.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal" role="dialog" aria-label="Settings">
      <div className="modal__card">
        <h2 className="modal__title">Settings</h2>

        {!settings && <p className="modal__note">{notice ?? "Loading..."}</p>}

        {settings && (
          <>
            <p className="modal__section">Server</p>

            <label className="modal__field">
              <span>Address (IP or hostname)</span>
              <input
                type="text"
                value={settings.serverHost}
                placeholder="192.168.1.20"
                onChange={(event) => setSettings({ ...settings, serverHost: event.target.value })}
              />
            </label>

            <label className="modal__field">
              <span>Port</span>
              <input
                type="number"
                min={1}
                max={65535}
                value={settings.serverPort}
                onChange={(event) => setSettings({ ...settings, serverPort: Number(event.target.value) })}
              />
            </label>

            <label className="modal__field">
              <span>Token (leave empty if the server has none)</span>
              <input
                type="password"
                value={settings.serverToken}
                onChange={(event) => setSettings({ ...settings, serverToken: event.target.value })}
              />
            </label>

            {notice && <p className="modal__note">{notice}</p>}
          </>
        )}

        <div className="modal__actions">
          <button type="button" className="btn" onClick={onClose}>
            Close
          </button>
          <button type="button" className="btn btn--start" onClick={save} disabled={!settings || saving}>
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
