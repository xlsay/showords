const { contextBridge, ipcRenderer } = require("electron");

// Resolve the backend base URLs synchronously so they exist at module load.
let bases = { httpBase: "http://127.0.0.1:8766", wsBase: "ws://127.0.0.1:8766" };
try {
  const resolved = ipcRenderer.sendSync("meetingAssist:get-backend-bases");
  if (resolved && resolved.httpBase && resolved.wsBase) bases = resolved;
} catch {
  /* fall back to defaults */
}

contextBridge.exposeInMainWorld("meetingAssist", {
  backendHttp: bases.httpBase,
  backendWs: bases.wsBase,

  saveTextFile: (suggestedName, content) =>
    ipcRenderer.invoke("meetingAssist:save-text-file", suggestedName, content),

  // Backend lifecycle / status
  getBackendInfo: () => ipcRenderer.invoke("meetingAssist:get-backend-info"),
  onBackendStatus: (cb) => {
    const listener = (_event, info) => cb(info);
    ipcRenderer.on("meetingAssist:backend-status", listener);
    return () => ipcRenderer.removeListener("meetingAssist:backend-status", listener);
  },
  retryBackend: () => ipcRenderer.invoke("meetingAssist:retry-backend"),
  openBackendLog: () => ipcRenderer.invoke("meetingAssist:open-backend-log"),
  setSessionActive: (active) => ipcRenderer.send("meetingAssist:set-session-active", active),

  // Settings
  getSettings: () => ipcRenderer.invoke("meetingAssist:get-settings"),
  saveSettings: (partial) => ipcRenderer.invoke("meetingAssist:save-settings", partial),
});
