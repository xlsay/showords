// Thin fetch wrappers over the local bridge's read-only endpoints.

function httpBase(): string {
  return window.meetingAssist?.backendHttp ?? "http://127.0.0.1:8766";
}

export interface AudioDevice {
  id: string;
  name: string;
  default?: boolean;
}

export interface AudioDevices {
  mics: AudioDevice[];
  loopbacks: AudioDevice[];
  system_default: AudioDevice | null;
}

export interface ServerStatus {
  reachable: boolean;
  error?: string | null;
  ready?: boolean;
  busy?: boolean;
  auth_required?: boolean;
  whisper_size?: string;
  whisper_device?: string;
  translation_enabled?: boolean;
}

export interface ClientConfig {
  server_host: string;
  server_port: number;
  token_set: boolean;
  default_source: string;
  server: ServerStatus;
}

export async function fetchAudioDevices(): Promise<AudioDevices> {
  const res = await fetch(`${httpBase()}/audio/devices`);
  if (!res.ok) throw new Error(`audio/devices ${res.status}`);
  return res.json();
}

export async function fetchConfig(): Promise<ClientConfig> {
  const res = await fetch(`${httpBase()}/config`);
  if (!res.ok) throw new Error(`config ${res.status}`);
  return res.json();
}
