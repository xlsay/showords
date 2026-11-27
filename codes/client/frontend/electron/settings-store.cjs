// Per-user settings store, injected into the client bridge as MEETINGASSIST_* env vars.

const { app } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

const SETTINGS_FILE = "meetingAssist-settings.json";

function settingsPath() {
  return path.join(app.getPath("userData"), SETTINGS_FILE);
}

function defaultSettings() {
  return {
    bridgePort: 8766, // local bridge, matches client config.yaml bridge.port
    serverHost: "", // empty = client config.yaml server.host
    serverPort: 8765, // matches server config.yaml server.port
    serverToken: "", // matches server config.yaml server.token
  };
}

function withDefaults(raw) {
  const d = defaultSettings();
  if (!raw || typeof raw !== "object") return d;
  const merged = { ...d };
  for (const key of Object.keys(d)) {
    if (raw[key] !== undefined && raw[key] !== null) merged[key] = raw[key];
  }
  return merged;
}

function readSettings() {
  try {
    const text = fs.readFileSync(settingsPath(), "utf-8");
    return withDefaults(JSON.parse(text));
  } catch (err) {
    if (err && err.code !== "ENOENT") {
      console.warn("[settings] failed to read settings, using defaults:", err.message);
    }
    return defaultSettings();
  }
}

function writeSettings(partial) {
  const next = withDefaults({ ...readSettings(), ...(partial || {}) });
  fs.mkdirSync(app.getPath("userData"), { recursive: true });
  const target = settingsPath();
  const tmp = `${target}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(next, null, 2), "utf-8");
  fs.renameSync(tmp, target); // atomic replace
  return next;
}

// Every setting is read at bridge startup, so any change needs a restart.
function startupSignature(settings) {
  return JSON.stringify(withDefaults(settings));
}

// Map settings -> MEETINGASSIST_* env vars; empty values are omitted so config.yaml wins.
function settingsToEnv(settings) {
  const s = withDefaults(settings);
  const env = { MEETINGASSIST_BRIDGE_PORT: String(s.bridgePort || 8766) };
  if (s.serverHost) env.MEETINGASSIST_SERVER_HOST = String(s.serverHost).trim();
  if (s.serverPort) env.MEETINGASSIST_SERVER_PORT = String(s.serverPort);
  if (s.serverToken) env.MEETINGASSIST_SERVER_TOKEN = String(s.serverToken);
  return env;
}

module.exports = {
  settingsPath,
  defaultSettings,
  readSettings,
  writeSettings,
  settingsToEnv,
  startupSignature,
};
