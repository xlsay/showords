// Shape of the `window.meetingAssist` bridge exposed by electron/preload.cjs.

export type BackendState = "idle" | "locating" | "starting" | "ready" | "failed" | "stopped";

export interface BackendInfo {
  state: BackendState;
  detail: string | null;
  httpBase: string;
  wsBase: string;
  logTail: string[];
}

export interface AppSettings {
  bridgePort: number;
  serverHost: string;
  serverPort: number;
  serverToken: string;
}

export interface SaveSettingsResult {
  settings: AppSettings;
  startupChanged: boolean;
  restarted: boolean;
  backend: BackendInfo;
}

export interface MeetingAssistBridge {
  backendHttp: string;
  backendWs: string;

  saveTextFile?: (suggestedName: string, content: string) => Promise<string | null>;

  getBackendInfo: () => Promise<BackendInfo>;
  onBackendStatus: (cb: (info: BackendInfo) => void) => () => void;
  retryBackend: () => Promise<BackendInfo>;
  openBackendLog: () => Promise<string>;
  setSessionActive: (active: boolean) => void;

  getSettings: () => Promise<AppSettings>;
  saveSettings: (partial: Partial<AppSettings>) => Promise<SaveSettingsResult>;
}

declare global {
  interface Window {
    meetingAssist?: MeetingAssistBridge;
  }
}
